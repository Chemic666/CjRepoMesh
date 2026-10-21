#!/usr/bin/env python3
"""Verify stored provenance inspection without a compiler or registry access."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--library-path", help="runtime libraries for an unpackaged Linux binary")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("this no-SDK acceptance currently supports Linux only")
    client = args.cjpm.resolve(strict=True)
    evidence = args.evidence_dir.absolute()
    evidence.mkdir(parents=True, exist_ok=False)
    parent = Path(__file__).resolve().parents[1] / ".tmp"
    parent.mkdir(exist_ok=True)
    work = parent / ("recorded-no-sdk-" + uuid.uuid4().hex)
    work.mkdir()
    requests: list[str] = []

    class Registry(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Registry)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    env = dict(PATH="/usr/bin:/bin", LANG="C.UTF-8")
    if args.library_path:
        env["LD_LIBRARY_PATH"] = args.library_path
    assert shutil.which("cjc", path=env["PATH"]) is None, "acceptance requires a PATH without cjc"
    record_data = dict(formatVersion=1, packages=[
        dict(package=name, version="1.0.0", repository="internal", registry=origin + "/private", sha256="a" * 64)
        for name in ("meshdep", "company::auth")])
    cases = []
    started = time.monotonic()

    def check(name: str, command: list[str], expected: int, marker: str, *, record: object = record_data,
              readonly: bool = False, bad_config: bool = False, forbidden: tuple[str, ...] = ()) -> None:
        root = work / name
        root.mkdir()
        home = root / "home"
        home.mkdir()
        path = root / "cjpm-provenance.json"
        if record is not None:
            path.write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")
        if readonly:
            path.chmod(0o444)
        case_env = dict(env, HOME=str(home), USERPROFILE=str(home))
        if bad_config:
            config = root / "unrelated-config"
            config.mkdir()
            (config / "config.toml").write_text("invalid = [", encoding="utf-8")
            (root / "cangjie-repo.toml").write_text("invalid = [", encoding="utf-8")
            (root / "cjpm.toml").write_text("invalid = [", encoding="utf-8")
            (root / "build.cj").write_text("invalid build script", encoding="utf-8")
            case_env["CJPM_CONFIG"] = str(config)
        before = snapshot(root)
        result = subprocess.run([str(client), *command], cwd=root, env=case_env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                check=False, timeout=30)
        log = evidence / (name + ".log")
        log.write_text(result.stdout, encoding="utf-8")
        passed = (result.returncode == expected and marker in result.stdout and
                  all(text not in result.stdout for text in forbidden) and snapshot(root) == before)
        cases.append(dict(name=name, passed=passed, exitCode=result.returncode, expectedExit=expected,
                          filesUnchanged=snapshot(root) == before, logSha256=sha(log)))
        print(f"{'PASS' if passed else 'FAIL'} {name}: exit {result.returncode}", flush=True)

    error = ""
    try:
        def recorded(package="meshdep"):
            return ["repo", "explain", package, "--recorded"]
        check("valid-default", recorded(), 0, "checksum: sha256:" + "a" * 64)
        check("valid-organization", recorded("company::auth"), 0, "package: company::auth")
        check("readonly-record", recorded(), 0, "Recorded resolution:", readonly=True)
        check("invalid-config-still-rejected", recorded(), 1, "load file './cangjie-repo.toml' failed", bad_config=True)
        check("missing-record", recorded(), 1, "does not exist or is invalid", record=None)
        check("package-not-recorded", recorded("absent"), 1, "is not recorded")
        check("unsupported-version", recorded(), 1, "unsupported repository provenance format version",
              record=dict(record_data, formatVersion=99))
        check("malformed-record", recorded(), 1, "failed to read repository provenance", record="invalid json")
        unsafe = dict(record_data, packages=[dict(record_data["packages"][0], registry=origin.replace("http://", "http://private-user:private-secret@"))])
        check("unsafe-record-address", recorded(), 1, "recorded registry URL is unsafe", record=unsafe,
              forbidden=("private-user", "private-secret"))
        check("invalid-package-name", recorded("bad/name"), 1, "name of dependency")
        for name, command in (("online-still-needs-sdk", ["repo", "explain", "meshdep"]),
                              ("build-still-needs-sdk", ["build"]),
                              ("run-still-needs-sdk", ["run"])):
            check(name, command, 1, "failed to run 'cjc -v'")
    except (OSError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    passed = sum(case["passed"] for case in cases)
    success = not error and passed == len(cases) == 13 and not requests
    result = dict(success=success, passed=passed, total=13, error=error, cases=cases,
                  registryRequests=len(requests), compilerOnPath=False, sdkEnvironment=False,
                  clientSha256=sha(client), runnerSha256=sha(Path(__file__)),
                  seconds=round(time.monotonic() - started, 2))
    (evidence / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if success:
        assert work.resolve().parent == parent.resolve()
        shutil.rmtree(work)
    print(f"Recorded without SDK: {passed}/13; requests={len(requests)}; success={success}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
