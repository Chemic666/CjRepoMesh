#!/usr/bin/env python3
"""Run the same upstream Maple cjpm LLT case against two cjpm binaries."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


FIXTURE_NAME = "http_status_matrix"
FIXTURE_PORT = 39137
PASS_SUMMARY = "Total: 1, PASS: 1, FAIL: 0"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} not found: {path}")
    return path


def port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", FIXTURE_PORT)) != 0


def wait_for_port_release() -> None:
    for _ in range(50):
        if port_available():
            return
        time.sleep(0.1)
    raise RuntimeError(f"Official fixture port {FIXTURE_PORT} is still listening")


def normalized_fixture(source: Path, destination: Path) -> Path:
    target = destination / FIXTURE_NAME
    shutil.copytree(source, target)
    # The official fixture's end-anchored sed expressions and shell shebangs
    # require LF. Modify only the per-run copy, never the upstream checkout.
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".toml", ".cj"}:
            contents = path.read_bytes()
            path.write_bytes(contents.replace(b"\r\n", b"\n"))
    return target / f"{FIXTURE_NAME}.info"


def run_case(
    label: str, executable: Path, framework_main: Path, test_config: Path,
    fixture_info: Path, staging: Path, results: Path,
) -> None:
    if not port_available():
        raise RuntimeError(f"Port {FIXTURE_PORT} is in use before {label} run")
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("CJREPO_") or key.startswith("CJREPOMESH_"):
            env.pop(key)
    env["PATH"] = f"{executable.parent}{os.pathsep}{env.get('PATH', '')}"
    output_dir = results / label
    output_dir.mkdir()
    command = (
        sys.executable, str(framework_main),
        f"--test_cfg={test_config}",
        f"--temp_dir={staging / (label + '-temp')}",
        f"--log_dir={output_dir / 'maple-log'}",
        "--fail_exit", "-p", "FAIL", str(fixture_info),
    )
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=staging, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=720, check=False,
        )
    finally:
        wait_for_port_release()
    output = completed.stdout
    (output_dir / "runner.log").write_text(output, encoding="utf-8")
    if completed.returncode != 0 or PASS_SUMMARY not in output:
        raise RuntimeError(
            f"{label} Maple LLT failed (exit {completed.returncode}); "
            f"inspect {output_dir / 'runner.log'}"
        )
    print(
        f"PASS {label}: Maple {FIXTURE_NAME} 1/1, "
        f"{time.monotonic() - started:.2f}s; cjpm SHA-256 {file_sha256(executable)}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--test-config", type=Path, required=True)
    parser.add_argument("--official-cjpm", type=Path, required=True)
    parser.add_argument("--enhanced-cjpm", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    framework_main = require_file(args.framework / "main.py", "Maple main.py")
    fixture = args.fixture.expanduser().resolve()
    require_file(fixture / f"{FIXTURE_NAME}.info", "official LLT case")
    require_file(fixture / "run_matrix.sh", "official LLT script")
    config = require_file(args.test_config, "official test configuration")
    official = require_file(args.official_cjpm, "official cjpm")
    enhanced = require_file(args.enhanced_cjpm, "enhanced cjpm")
    if official == enhanced:
        raise ValueError("Official and enhanced cjpm paths must differ")
    if not port_available():
        raise RuntimeError(f"Port {FIXTURE_PORT} is already in use")

    results_parent = args.results_dir.expanduser().resolve()
    results_parent.mkdir(parents=True, exist_ok=True)
    results = results_parent / f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    results.mkdir()
    temp_parent = Path(__file__).resolve().parent.parent / ".tmp"
    temp_parent.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="maple-smoke-", dir=temp_parent) as raw:
            staging = Path(raw)
            fixture_info = normalized_fixture(fixture, staging)
            copied_config = staging / "test.cfg"
            shutil.copy2(config, copied_config)
            for label, executable in (("official", official), ("enhanced", enhanced)):
                run_case(
                    label, executable, framework_main, copied_config,
                    fixture_info, staging, results,
                )
    finally:
        try:
            temp_parent.rmdir()
        except OSError:
            pass
    print(f"Both Maple LLT runs passed. Logs: {results}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
