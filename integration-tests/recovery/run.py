#!/usr/bin/env python3
"""Hosted recovery: inject persisted crash states and kill an incomplete upload."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    ManagedProcesses, TestFailure, assert_equal, assert_ports_available,
    http_request, platform_executable, publish_frame, wait_for_health, wait_for_ports_closed,
)


def main() -> int:
    project = TESTS.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path,
                        default=platform_executable(project / "server/target/release/bin/main"))
    parser.add_argument("--port", type=int, default=39610)
    args = parser.parse_args()
    server = args.server.resolve()
    if not server.is_file():
        parser.error("build the server first")
    assert_ports_available((args.port,))
    parent = TESTS / ".tmp"
    root = parent / f"recovery-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    storage = root / "storage"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("CJREPO_")}
    environment.update(CJREPO_ADDRESS="127.0.0.1", CJREPO_PORT=str(args.port),
                       CJREPO_STORAGE=str(storage), CJREPO_PUBLISH_TOKEN="fixture-publish",
                       CJREPO_READ_TOKEN="fixture-read")
    base = f"http://127.0.0.1:{args.port}"
    artifact = b"CjRepoMesh recovery protocol fixture"
    checksum = hashlib.sha256(artifact).hexdigest()
    version = "1.0.0"
    failures: list[str] = []
    completed = 0

    def paths(name: str, org: str = "default", ver: str = version) -> tuple[Path, Path]:
        return (storage / "index" / org / name[:2] / name[2:4] / name,
                storage / "artifacts" / org / name / ver / f"{name}-{ver}.cjp")

    def record(name: str, org: str = "default", ver: str = version,
               digest: str = checksum) -> dict:
        return dict(name=name, version=ver, organization="" if org == "default" else org,
                    sha256sum=digest, dependencies=[])

    def frame(name: str, org: str = "default") -> bytes:
        index = record(name, org)
        metadata = dict(name=name, version=version, organization=index["organization"], index=index)
        return publish_frame(json.dumps(metadata).encode(), artifact)

    def seed(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def encoded(value: dict) -> bytes:
        return json.dumps(value, separators=(",", ":")).encode() + b"\n"

    def publish(name: str, org: str = "default", token: str = "fixture-publish") -> int:
        query = "" if org == "default" else f"?organization={org}"
        return http_request("POST", f"{base}/pkg/{name}{query}",
                            headers={"Authorization": token}, body=frame(name, org)).status

    def consistent(name: str, org: str = "default", count: int = 1) -> None:
        index, stored = paths(name, org)
        rows = [json.loads(line) for line in index.read_bytes().splitlines() if line]
        assert_equal(len(rows), count, label="index record count")
        assert_equal([row["version"] for row in rows].count(version), 1, label="selected version count")
        assert_equal(stored.read_bytes(), artifact, label="stored artifact")
        query = "" if org == "default" else f"?organization={org}"
        response = http_request("GET", f"{base}/pkg/{name}/{version}{query}",
                                headers={"Authorization": "fixture-read"})
        assert_equal(response.status, 200, label="download after recovery")
        assert_equal(hashlib.sha256(response.body).hexdigest(), checksum, label="download checksum")

    def check(label: str, action) -> None:
        nonlocal completed
        completed += 1
        try:
            action()
            print(f"PASS {label}", flush=True)
        except (TestFailure, OSError, ValueError) as error:
            failures.append(label)
            print(f"FAIL {label}: {error}", flush=True)

    try:
        with ManagedProcesses() as processes:
            def start():
                process = processes.start((server,), cwd=server.parent, env=environment,
                                          output_path=root / f"server-{uuid.uuid4().hex[:8]}.log")
                wait_for_health(args.port)
                return process

            process = start()

            def normal() -> None:
                name = "recoverfresh"
                assert_equal(publish(name), 200, label="fresh publish")
                before = paths(name)[0].read_bytes()
                assert_equal(publish(name), 409, label="complete duplicate remains immutable")
                assert_equal(paths(name)[0].read_bytes(), before, label="duplicate leaves index unchanged")
                consistent(name)
            check("normal publication and immutable duplicate", normal)

            def neighboring_package() -> None:
                name = "recoverneighbor"
                neighbor = name + ".tmp"
                assert_equal(publish(neighbor), 200, label="dotted package publish")
                neighbor_index, neighbor_artifact = paths(neighbor)
                previous = neighbor_index.read_bytes()
                assert_equal(publish(name), 200, label="neighboring package publish")
                assert_equal(neighbor_index.read_bytes(), previous, label="neighbor index must survive atomic commit")
                assert_equal(neighbor_artifact.read_bytes(), artifact, label="neighbor artifact is preserved")
                consistent(neighbor)
                consistent(name)
            check("temporary index filename cannot overwrite another valid package", neighboring_package)

            def stale_temporary_files() -> None:
                name = "recovertemporary"
                index, stored = paths(name)
                index_temporary = index.with_name(f".{index.name}.tmp")
                artifact_temporary = stored.with_name(f".{stored.name}.tmp")
                seed(index_temporary, b"partial temporary index" * 100)
                seed(artifact_temporary, b"partial temporary artifact" * 100)
                for path in (f"/index/{name[:2]}/{name[2:4]}/{name}",
                             f"/index/{name[:2]}/{name[2:4]}/.{name}.tmp",
                             f"/pkg/{name}/{version}"):
                    response = http_request("GET", base + path,
                                            headers={"Authorization": "fixture-read"})
                    assert_equal(response.status, 404, label="unfinished data is not readable")
                assert_equal(publish(name), 200, label="retry overwrites incomplete temporary files")
                consistent(name)
                assert_equal(index_temporary.exists(), False, label="index temporary file renamed")
                assert_equal(artifact_temporary.exists(), False, label="artifact temporary file renamed")
            check("stale temporary files are private and do not prevent a fresh retry", stale_temporary_files)

            def orphan() -> None:
                name = "recoverorphan"
                index, stored = paths(name)
                seed(stored, artifact)
                timestamp = stored.stat().st_mtime_ns
                assert_equal(publish(name, token="invalid"), 401, label="unauthorized repair")
                assert_equal(index.exists(), False, label="unauthorized request does not create index")
                assert_equal(publish(name), 200, label="recover matching orphan")
                assert_equal(stored.stat().st_mtime_ns, timestamp, label="orphan artifact is not rewritten")
                assert_equal(publish(name), 409, label="recovered version becomes immutable")
                consistent(name)
            check("artifact-only crash state recovers after authenticated retry", orphan)

            def previous_version() -> None:
                name = "recoverprevious"
                index, stored = paths(name)
                old_index, old_artifact = paths(name, ver="0.9.0")
                seed(old_artifact, artifact)
                previous = encoded(record(name, ver="0.9.0")).rstrip(b"\n")
                seed(old_index, previous)
                seed(stored, artifact)
                assert_equal(publish(name), 200, label="repair preserves other version")
                assert_equal(index.read_bytes().splitlines()[0], previous, label="old metadata is preserved")
                consistent(name, count=2)
            check("repair preserves prior versions and handles missing final newline", previous_version)

            def conflict() -> None:
                name = "recoverconflict"
                index, stored = paths(name)
                seed(stored, b"different immutable bytes")
                assert_equal(publish(name), 409, label="conflicting orphan")
                assert_equal(stored.read_bytes(), b"different immutable bytes", label="orphan is not overwritten")
                assert_equal(index.exists(), False, label="conflicting orphan is not advertised")
            check("different orphan content is rejected without overwrite", conflict)

            def missing_artifact() -> None:
                name = "recovermissing"
                index, _stored = paths(name)
                published = record(name)
                published["retained-metadata"] = "must not be replaced by retry"
                previous = encoded(published)
                seed(index, previous)
                assert_equal(publish(name), 200, label="restore missing artifact")
                assert_equal(index.read_bytes(), previous, label="existing metadata is not appended or replaced")
                consistent(name)
            check("index-only state restores matching bytes without duplicate metadata", missing_artifact)

            def conflicting_index() -> None:
                name = "recoverindexconflict"
                index, stored = paths(name)
                previous = encoded(record(name, digest="0" * 64))
                seed(index, previous)
                assert_equal(publish(name), 409, label="published checksum is immutable")
                assert_equal(index.read_bytes(), previous, label="conflicting metadata is preserved")
                assert_equal(stored.exists(), False, label="conflicting bytes are not written")
            check("published checksum cannot be replaced when the artifact is absent", conflicting_index)

            def organization() -> None:
                name, org = "recovernamespace", "meshcorp"
                default_index, default_artifact = paths(name)
                seed(default_artifact, b"default namespace bytes")
                previous = encoded(record(name, digest=hashlib.sha256(default_artifact.read_bytes()).hexdigest()))
                seed(default_index, previous)
                seed(paths(name, org)[1], artifact)
                assert_equal(publish(name, org), 200, label="organization repair")
                consistent(name, org)
                assert_equal(default_index.read_bytes(), previous, label="default index isolation")
                assert_equal(default_artifact.read_bytes(), b"default namespace bytes", label="default artifact isolation")
            check("organization recovery does not alter the default namespace", organization)

            def concurrent() -> None:
                name = "recoverconcurrent"
                seed(paths(name)[1], artifact)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    statuses = sorted(executor.map(lambda _: publish(name), range(2)))
                assert_equal(statuses, [200, 409], label="concurrent repair outcomes")
                consistent(name)
            check("concurrent orphan retries produce one index entry", concurrent)

            def concurrent_missing() -> None:
                name = "recoverconcurrentmissing"
                index, _stored = paths(name)
                previous = encoded(record(name))
                seed(index, previous)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    statuses = sorted(executor.map(lambda _: publish(name), range(2)))
                assert_equal(statuses, [200, 409], label="concurrent artifact restoration")
                assert_equal(index.read_bytes(), previous, label="restoration leaves metadata unchanged")
                consistent(name)
            check("concurrent missing-artifact retries preserve one published record", concurrent_missing)

            def failed_orphan_repair() -> None:
                name = "recoverfailedindex"
                index, stored = paths(name)
                seed(stored, artifact)
                blocked = index.with_name(f".{index.name}.tmp")
                blocked.mkdir(parents=True)
                assert_equal(publish(name), 400, label="blocked index write fails")
                assert_equal(stored.read_bytes(), artifact, label="failed repair preserves existing orphan")
                assert_equal(index.exists(), False, label="failed repair does not advertise artifact")
                if blocked.exists():
                    blocked.rmdir()
                assert_equal(publish(name), 200, label="retry after index write failure")
                consistent(name)
            check("index-write failure preserves an existing orphan for retry", failed_orphan_repair)

            def failed_fresh_publish() -> None:
                name = "recoverrollback"
                index, stored = paths(name)
                old_index, old_artifact = paths(name, ver="0.9.0")
                seed(old_artifact, artifact)
                previous = encoded(record(name, ver="0.9.0"))
                seed(old_index, previous)
                blocked = index.with_name(f".{index.name}.tmp")
                blocked.mkdir()
                assert_equal(publish(name), 400, label="fresh index commit fails")
                assert_equal(stored.exists(), False, label="only the new artifact is rolled back")
                assert_equal(index.read_bytes(), previous, label="previous index survives failure")
                assert_equal(old_artifact.read_bytes(), artifact, label="previous artifact survives failure")
                if blocked.exists():
                    blocked.rmdir()
                assert_equal(publish(name), 200, label="fresh retry after rollback")
                consistent(name, count=2)
            check("failed fresh publication rolls back only new bytes", failed_fresh_publish)

            def corrupt_index() -> None:
                name = "recovercorruptindex"
                index, stored = paths(name)
                previous = encoded(record(name)) * 2
                seed(index, previous)
                assert_equal(publish(name), 400, label="ambiguous stored index is rejected")
                assert_equal(index.read_bytes(), previous, label="ambiguous index stays untouched")
                assert_equal(stored.exists(), False, label="ambiguous index cannot trigger a write")
            check("duplicate stored version records fail without mutation", corrupt_index)

            def malformed_index() -> None:
                name = "recovermalformed"
                index, stored = paths(name)
                previous = b"{invalid-json}\n"
                seed(index, previous)
                assert_equal(publish(name), 400, label="malformed stored index is rejected")
                assert_equal(index.read_bytes(), previous, label="malformed index is not overwritten")
                assert_equal(stored.exists(), False, label="malformed index cannot trigger a write")
            check("malformed stored index fails before filesystem mutation", malformed_index)

            for mode in ("fresh", "orphan", "indexonly"):
                for number, invalid_checksum in enumerate(("abc", "g" * 64)):
                    def invalid_stored_checksum(mode=mode, number=number, digest=invalid_checksum) -> None:
                        name = f"recoverbadsha{mode}{number}"
                        index, stored = paths(name)
                        bad_record = encoded(record(name, ver="0.9.0", digest=digest))
                        previous = (encoded(record(name)) if mode == "indexonly" else b"") + bad_record
                        seed(index, previous)
                        if mode == "orphan":
                            seed(stored, artifact)
                        assert_equal(publish(name), 400, label="invalid stored checksum blocks commit")
                        assert_equal(index.read_bytes(), previous, label="invalid index is preserved")
                        assert_equal(stored.exists(), mode == "orphan", label="no artifact created or deleted")
                        if stored.exists():
                            assert_equal(stored.read_bytes(), artifact, label="existing artifact stays unchanged")
                    check(f"invalid stored SHA blocks {mode} commit ({number})", invalid_stored_checksum)

            def invalid_stored_version() -> None:
                name = "recoverbadversion"
                index, stored = paths(name)
                previous = encoded(record(name, ver="../invalid"))
                seed(index, previous)
                assert_equal(publish(name), 400, label="invalid stored version blocks commit")
                assert_equal(index.read_bytes(), previous, label="invalid stored version is preserved")
                assert_equal(stored.exists(), False, label="invalid version cannot trigger artifact write")
            check("unsafe stored version blocks publication without mutation", invalid_stored_version)

            def interrupted_upload() -> None:
                nonlocal process
                name = "recoverupload"
                payload = frame(name)
                with socket.create_connection(("127.0.0.1", args.port), timeout=2) as client:
                    request = (f"POST /pkg/{name} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                               f"Authorization: fixture-publish\r\nContent-Length: {len(payload)}\r\n\r\n").encode()
                    client.sendall(request + payload[:len(payload) // 2])
                    process.kill()
                    process.wait(timeout=5)
                processes.stop(process)
                wait_for_ports_closed((args.port,))
                assert_equal(paths(name)[0].exists(), False, label="incomplete upload has no index")
                assert_equal(paths(name)[1].exists(), False, label="incomplete upload has no artifact")
                process = start()
                assert_equal(publish(name), 200, label="publish after abrupt termination and restart")
                consistent(name)
                consistent("recoverorphan")
                consistent("recovermissing")
                consistent("recovernamespace", "meshcorp")
            check("partial upload survives real process termination and restart", interrupted_upload)
        wait_for_ports_closed((args.port,))
    finally:
        if failures or sys.exc_info()[0] is not None:
            print(f"Failure evidence retained: {root}", flush=True)
        else:
            shutil.rmtree(root)
            try:
                parent.rmdir()
            except OSError:
                pass
    print(f"Hosted recovery: {completed - len(failures)}/{completed} passed.", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
