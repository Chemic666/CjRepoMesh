#!/usr/bin/env python3
"""Sync recovery against a real destination and deterministic HTTP interruption gates."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
from urllib.parse import urlsplit, parse_qs
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    ManagedProcesses, TestFailure, assert_contains, assert_equal, assert_ports_available,
    http_request, platform_executable, wait_for_health, wait_for_ports_closed,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path,
                        default=platform_executable(TESTS.parent / "server/target/release/bin/main"))
    parser.add_argument("--port", type=int, default=39620, help="first of three consecutive ports")
    args = parser.parse_args()
    server = args.server.resolve()
    if not server.is_file():
        parser.error("build the server first")
    ports = tuple(range(args.port, args.port + 3))
    assert_ports_available(ports)
    root = TESTS / ".tmp" / f"sync-recovery-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    storage = root / "storage"
    source = f"http://127.0.0.1:{ports[0]}"
    destination = f"http://127.0.0.1:{ports[1]}"
    gateway = f"http://127.0.0.1:{ports[2]}"
    artifact = b"CjRepoMesh Sync recovery protocol fixture" * 256
    checksum = hashlib.sha256(artifact).hexdigest()
    version = "1.0.0"
    env = {key: value for key, value in os.environ.items() if not key.startswith("CJREPO_")}
    env.update(CJREPO_UPSTREAM_TOKEN="fixture-source", CJREPO_SYNC_DESTINATION_TOKEN="fixture-publish",
               CJREPO_SYNC_DESTINATION_READ_TOKEN="fixture-read")
    destination_env = dict(env, CJREPO_ADDRESS="127.0.0.1", CJREPO_PORT=str(ports[1]),
                           CJREPO_STORAGE=str(storage), CJREPO_PUBLISH_TOKEN="fixture-publish",
                           CJREPO_READ_TOKEN="fixture-read")
    arrived = threading.Event()
    release = threading.Event()
    source_requests: list[str] = []
    mode = ""
    failures: list[str] = []
    completed = 0
    servers: list[ThreadingHTTPServer] = []

    def paths(name: str, org: str = "default") -> tuple[Path, Path]:
        return (storage / "index" / org / name[:2] / name[2:4] / name,
                storage / "artifacts" / org / name / version / f"{name}-{version}.cjp")

    def record(name: str, org: str = "default", digest: str = checksum) -> bytes:
        return (json.dumps(dict(name=name, organization="" if org == "default" else org,
                                version=version, sha256sum=digest, dependencies=[])) + "\n").encode()

    def seed(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status: int, body: bytes) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # An intentionally killed client may close before the response.

        def do_GET(self):
            if self.server.server_port == ports[0]:
                source_requests.append(self.path)
                if self.headers.get("Authorization") != "fixture-source":
                    self.respond(401, b"unauthorized")
                    return
                parsed = urlsplit(self.path)
                org = parse_qs(parsed.query).get("organization", ["default"])[0]
                parts = parsed.path.split("/")
                if parsed.path.startswith("/index/"):
                    self.respond(200, record(parts[-1], org))
                elif parsed.path.startswith("/pkg/"):
                    if mode == "download" and parts[2] == "synckilldownload":
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(artifact)))
                        self.end_headers()
                        self.wfile.write(artifact[:32])
                        self.wfile.flush()
                        arrived.set()
                        if release.wait(10):
                            try:
                                self.wfile.write(artifact[32:])
                            except (BrokenPipeError, ConnectionResetError):
                                pass
                    else:
                        self.respond(200, artifact)
                else:
                    self.respond(404, b"missing")
                return
            if mode == "forbidden" and self.path.startswith("/pkg/"):
                self.respond(403, b"forbidden")
                return
            result = http_request("GET", destination + self.path,
                                  headers={"Authorization": self.headers.get("Authorization", "")})
            self.respond(result.status, result.body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if mode == "partial":
                try:
                    with socket.create_connection(("127.0.0.1", ports[1]), timeout=5) as connection:
                        headers = (f"POST {self.path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                   f"Authorization: fixture-publish\r\nContent-Length: {len(body)}\r\n"
                                   "Connection: close\r\n\r\n").encode()
                        connection.sendall(headers + body[:len(body) // 2])
                        arrived.set()
                        if release.wait(10):
                            connection.sendall(body[len(body) // 2:])
                            connection.recv(1024)
                except OSError:
                    pass  # The destination is intentionally terminated mid-upload.
                self.respond(502, b"destination interrupted")
                return
            result = http_request("POST", destination + self.path,
                                  headers={"Authorization": self.headers.get("Authorization", "")}, body=body)
            if mode == "ack" and result.status == 200:
                arrived.set()
                release.wait(10)
            self.respond(result.status, result.body)

    def command(name: str, org: str = "default", target: str = destination) -> tuple:
        return (server, "sync", source, target,
                name if org == "default" else f"{org}::{name}", version)

    def sync(name: str, org: str = "default", target: str = destination,
             expected_success: bool = True, environment: dict | None = None) -> str:
        result = subprocess.run(command(name, org, target), cwd=server.parent, env=environment or env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", timeout=15)
        (root / f"sync-{uuid.uuid4().hex[:8]}.log").write_text(result.stdout, encoding="utf-8")
        assert_equal(result.returncode == 0, expected_success, label=f"Sync exit status: {result.stdout}")
        return result.stdout

    def consistent(name: str, org: str = "default") -> None:
        index, stored = paths(name, org)
        rows = [json.loads(line) for line in index.read_bytes().splitlines() if line]
        assert_equal(len(rows), 1, label="single index record")
        assert_equal(rows[0]["sha256sum"], checksum, label="index checksum")
        assert_equal(stored.read_bytes(), artifact, label="destination artifact")

    def check(label: str, action) -> None:
        nonlocal completed
        completed += 1
        try:
            action()
            print(f"PASS {label}", flush=True)
        except (TestFailure, OSError, ValueError, subprocess.TimeoutExpired) as error:
            failures.append(label)
            print(f"FAIL {label}: {error}", flush=True)

    try:
        for port in (ports[0], ports[2]):
            fixture = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            fixture.daemon_threads = True
            servers.append(fixture)
            threading.Thread(target=fixture.serve_forever, daemon=True).start()
        with ManagedProcesses() as processes:
            def start_destination():
                process = processes.start((server,), cwd=server.parent, env=destination_env,
                                          output_path=root / f"destination-{uuid.uuid4().hex[:8]}.log")
                wait_for_health(ports[1])
                return process

            destination_process = start_destination()

            def fresh():
                assert_contains(sync("syncfresh"), "result=SYNCED")
                count = len(source_requests)
                assert_contains(sync("syncfresh"), "result=SKIP")
                assert_equal(source_requests[count:], ["/index/sy/nc/syncfresh"],
                             label="valid target skips source artifact fetch")
                consistent("syncfresh")
            check("fresh Sync and verified idempotent rerun", fresh)

            def orphan():
                seed(paths("syncorphan")[1], artifact)
                assert_contains(sync("syncorphan"), "result=SYNCED")
                consistent("syncorphan")
            check("artifact-only destination repairs index", orphan)

            for org in ("default", "meshcorp"):
                def index_only(org=org):
                    name = "syncindexonly"
                    index, _ = paths(name, org)
                    original = record(name, org)
                    seed(index, original)
                    assert_contains(sync(name, org), "result=SYNCED")
                    consistent(name, org)
                    assert_equal(index.read_bytes(), original, label="preserve existing index bytes")
                check(f"index-only destination repairs artifact ({org})", index_only)

            def corrupt():
                name = "synccorrupt"
                index, stored = paths(name)
                seed(index, record(name))
                seed(stored, b"damaged artifact")
                sync(name, expected_success=False)
                assert_equal(stored.read_bytes(), b"damaged artifact", label="do not overwrite corruption")
                assert_equal(index.read_bytes(), record(name), label="preserve index on corruption")
            check("corrupt destination cannot be reported as synchronized", corrupt)

            def conflict():
                name = "syncconflict"
                index, stored = paths(name)
                previous = record(name, digest="0" * 64)
                seed(index, previous)
                seed(stored, b"other published content")
                sync(name, expected_success=False)
                assert_equal(index.read_bytes(), previous, label="conflicting index unchanged")
                assert_equal(stored.read_bytes(), b"other published content", label="conflicting artifact unchanged")
            check("conflicting destination remains immutable", conflict)

            def commit_failure():
                name = "synccommitfailure"
                index, stored = paths(name)
                temporary = index.with_name(f".{index.name}.tmp")
                temporary.mkdir(parents=True)
                sync(name, expected_success=False)
                assert_equal(index.exists(), False, label="failed commit does not advertise version")
                assert_equal(stored.exists(), False, label="new artifact rolled back")
                if temporary.exists():
                    temporary.rmdir()
                assert_contains(sync(name), "result=SYNCED")
                consistent(name)
            check("failed destination index commit is safely retried", commit_failure)

            def denied_read():
                restricted = dict(env, CJREPO_SYNC_DESTINATION_READ_TOKEN="wrong")
                sync("syncdenied", environment=restricted, expected_success=False)
                assert_equal(paths("syncdenied")[0].exists(), False, label="read denial cannot trigger publish")
            check("destination read denial blocks Sync writes", denied_read)

            def forbidden_artifact():
                nonlocal mode
                name = "syncforbidden"
                sync(name)
                mode = "forbidden"
                try:
                    sync(name, target=gateway, expected_success=False)
                finally:
                    mode = ""
                consistent(name)
            check("destination artifact permission failure is not a successful skip", forbidden_artifact)

            def interrupted_download():
                nonlocal mode
                name = "synckilldownload"
                mode = "download"
                arrived.clear()
                release.clear()
                worker = processes.start(command(name), cwd=server.parent, env=env,
                                         output_path=root / "interrupted-download.log")
                try:
                    assert_equal(arrived.wait(5), True, label="source download gate reached")
                    worker.kill()
                    worker.wait(timeout=5)
                finally:
                    processes.stop(worker)
                    release.set()
                    mode = ""
                assert_equal(paths(name)[0].exists(), False, label="killed download has no target index")
                assert_equal(paths(name)[1].exists(), False, label="killed download has no target artifact")
                sync(name)
                consistent(name)
            check("real Sync process termination during download permits safe rerun", interrupted_download)

            def lost_ack():
                nonlocal mode
                name = "synclostack"
                mode = "ack"
                arrived.clear()
                release.clear()
                worker = processes.start(command(name, target=gateway), cwd=server.parent, env=env,
                                         output_path=root / "lost-ack.log")
                try:
                    assert_equal(arrived.wait(5), True, label="destination committed before response gate")
                    consistent(name)
                    worker.kill()
                    worker.wait(timeout=5)
                finally:
                    processes.stop(worker)
                    release.set()
                    mode = ""
                assert_contains(sync(name), "result=SKIP")
                consistent(name)
            check("lost acknowledgement and real worker kill do not duplicate publication", lost_ack)

            def interrupted_destination():
                nonlocal mode, destination_process
                name = "synckilldestination"
                mode = "partial"
                arrived.clear()
                release.clear()
                worker = processes.start(command(name, target=gateway), cwd=server.parent, env=env,
                                         output_path=root / "interrupted-destination.log")
                try:
                    assert_equal(arrived.wait(5), True, label="partial destination upload reached")
                    destination_process.kill()
                    destination_process.wait(timeout=5)
                    processes.stop(destination_process)
                    release.set()
                    assert_equal(worker.wait(timeout=10) != 0, True, label="Sync reports destination interruption")
                finally:
                    release.set()
                    processes.stop(worker)
                    mode = ""
                    destination_process = start_destination()
                assert_equal(paths(name)[0].exists(), False, label="partial upload not advertised")
                assert_equal(paths(name)[1].exists(), False, label="partial upload not committed")
                sync(name)
                consistent(name)
                consistent("synclostack")
            check("real destination termination mid-upload and restart preserve committed data", interrupted_destination)
    finally:
        release.set()
        for fixture in servers:
            fixture.shutdown()
            fixture.server_close()
        wait_for_ports_closed(ports)
        if failures or sys.exc_info()[0] is not None:
            print(f"Failure evidence retained: {root}", flush=True)
        else:
            shutil.rmtree(root)
            try:
                root.parent.rmdir()
            except OSError:
                pass
    print(f"Sync recovery: {completed - len(failures)}/{completed} passed.", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
