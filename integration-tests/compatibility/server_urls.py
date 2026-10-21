#!/usr/bin/env python3
"""Reject unsafe native server/Mirror/Sync URLs before network or storage access."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    ManagedProcesses, TestFailure, assert_ports_available, http_request, platform_executable,
    remove_within, wait_for_health, wait_for_ports_closed,
)


class Registry(BaseHTTPRequestHandler):
    requests: list[tuple[str, str | None]] = []

    def do_GET(self) -> None:
        self.requests.append((self.path, self.headers.get("Authorization")))
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass


def snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path,
                        default=platform_executable(TESTS.parent / "server/target/release/bin/main"))
    parser.add_argument("--port", type=int, default=39650)
    parser.add_argument("--evidence-dir", type=Path, help="new directory retaining individual outputs")
    args = parser.parse_args()
    executable = args.server.resolve()
    if not executable.is_file():
        parser.error("server executable does not exist")
    assert_ports_available((args.port,))
    root = TESTS / ".tmp" / ("server-urls-" + uuid.uuid4().hex)
    logs = root / "logs" if args.evidence_dir is None else args.evidence_dir.resolve()
    logs.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    home.mkdir()
    manifest = root / "manifest.txt"
    manifest.write_text("meshdep 1.0.0\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    env.update(HOME=str(home), USERPROFILE=str(home), CJREPO_ADDRESS="127.0.0.1",
               CJREPO_PORT=str(args.port), CJREPO_PUBLISH_TOKEN="publish-fixture",
               CJREPO_UPSTREAM_TOKEN="header-token-fixture")
    registry = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
    worker = threading.Thread(target=registry.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{registry.server_port}"
    secret = "unsafe-url-fixture-secret"
    unsafe = {
        "userinfo": origin.replace("http://", f"http://fixture-user:{secret}@"),
        "query": origin + "?token=" + secret,
        "fragment": origin + "#" + secret,
        "backslash": origin + "/repo\\" + secret,
        "newline": origin + "/repo\n" + secret,
        "scheme": "file:///" + secret,
        "relative": "/relative/" + secret,
        "encoded-authority": origin.replace("127.0.0.1", "127%2e0.0.1") + "/" + secret,
    }
    results: list[dict] = []

    def command_cases(address: str) -> list[tuple[str, list[str]]]:
        return [
            ("mirror", ["mirror", address, "meshdep", "1.0.0"]),
            ("mirror-manifest", ["mirror-manifest", address, str(manifest)]),
            ("mirror-watch", ["mirror-watch", address, str(manifest), "1"]),
            ("sync-source", ["sync", address, origin, "meshdep", "1.0.0"]),
            ("sync-destination", ["sync", origin, address, "meshdep", "1.0.0"]),
            ("sync-manifest-source", ["sync-manifest", address, origin, str(manifest)]),
            ("sync-manifest-destination", ["sync-manifest", origin, address, str(manifest)]),
            ("sync-watch-source", ["sync-watch", address, origin, str(manifest), "1"]),
            ("sync-watch-destination", ["sync-watch", origin, address, str(manifest), "1"]),
        ]

    def negative(label: str, address: str, arguments: list[str], *, startup: bool = False,
                 cached: bool = False) -> None:
        storage = root / label
        storage.mkdir()
        (storage / "keep.txt").write_text("existing-storage", encoding="utf-8")
        if cached:
            artifact = b"owned cached archive fixture"
            index = storage / "index/default/me/sh/meshdep"
            package = storage / "artifacts/default/meshdep/1.0.0/meshdep-1.0.0.cjp"
            index.parent.mkdir(parents=True)
            package.parent.mkdir(parents=True)
            package.write_bytes(artifact)
            index.write_text(json.dumps(dict(name="meshdep", version="1.0.0", organization="",
                sha256sum=hashlib.sha256(artifact).hexdigest())) + "\n", encoding="utf-8")
        previous = snapshot(storage)
        output_path = logs / (label + ".log")
        variables = dict(env, CJREPO_STORAGE=str(storage))
        if startup:
            variables["CJREPO_UPSTREAM"] = address
        Registry.requests.clear()
        with ManagedProcesses() as processes:
            process = processes.start((executable, *arguments), cwd=root, env=variables,
                                      output_path=output_path)
            try:
                code = process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                code = None
            processes.stop(process)
        output = output_path.read_text(encoding="utf-8", errors="replace")
        errors = []
        if code is None or code == 0:
            errors.append("did not reject promptly")
        if "invalid" not in output or "URL" not in output:
            errors.append("missing safe URL diagnostic")
        if secret in output or "fixture-user" in output:
            errors.append("unsafe URL value reflected")
        if Registry.requests:
            errors.append("registry request occurred")
        if snapshot(storage) != previous:
            errors.append("existing storage changed")
        results.append(dict(case=label, passed=not errors, errors=errors))
        print(("PASS " if not errors else "FAIL ") + label + (": " + "; ".join(errors) if errors else ""), flush=True)
        wait_for_ports_closed((args.port,))

    def positive(label: str, upstream: str, *, request_index: bool = False) -> None:
        output_path = logs / (label + ".log")
        variables = dict(env, CJREPO_STORAGE=str(root / label), CJREPO_UPSTREAM=upstream)
        Registry.requests.clear()
        errors = []
        try:
            with ManagedProcesses() as processes:
                process = processes.start((executable,), cwd=root, env=variables, output_path=output_path)
                wait_for_health(args.port)
                if request_index:
                    response = http_request("GET", f"http://127.0.0.1:{args.port}/index/me/sh/meshdep")
                    if response.status != 404 or Registry.requests != [
                            ("/registry/index/me/sh/meshdep", "header-token-fixture")]:
                        raise TestFailure("valid base path or token header changed")
                processes.stop(process)
        except TestFailure as error:
            errors.append(str(error))
        wait_for_ports_closed((args.port,))
        results.append(dict(case=label, passed=not errors, errors=errors))
        print(("PASS " if not errors else "FAIL ") + label, flush=True)

    try:
        for label, address in unsafe.items():
            negative(label + "-startup", address, [], startup=True)
            for command, arguments in command_cases(address):
                negative(label + "-" + command, address, arguments)
        for command, arguments in command_cases(""):
            negative("empty-" + command, "", arguments)
        negative("cached-mirror-query", unsafe["query"],
                 ["mirror", unsafe["query"], "meshdep", "1.0.0"], cached=True)
        negative("single-slash-startup", "/", [], startup=True)
        positive("hosted-no-upstream", "")
        positive("http-path-and-header", origin + "/registry/", request_index=True)
        positive("https-ipv6", "https://[::1]:443/registry")
        positive("uppercase-scheme", "HTTP://127.0.0.1:9/registry")
        positive("encoded-path", origin + "/registry%20name")
    finally:
        registry.shutdown()
        registry.server_close()
        worker.join(timeout=5)
    passed = sum(result["passed"] for result in results)
    report = dict(passed=passed, total=len(results), server_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                  cases=results)
    (logs / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Server URL validation: {passed}/{len(results)} passed", flush=True)
    success = passed == len(results)
    if success:
        remove_within(root, (TESTS / ".tmp",))
    else:
        print(f"Failure fixtures retained: {root}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
