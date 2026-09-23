#!/usr/bin/env python3
"""Run selected upstream Maple cjpm LLT suites against two cjpm binaries."""

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
    label: str, suite_name: str, executable: Path, framework_main: Path,
    test_config: Path, target: Path, expected_count: int,
    staging: Path, results: Path,
) -> None:
    if not port_available():
        raise RuntimeError(f"Port {FIXTURE_PORT} is in use before {label} run")
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("CJREPO_") or key.startswith("CJREPOMESH_"):
            env.pop(key)
    env["PATH"] = f"{executable.parent}{os.pathsep}{env.get('PATH', '')}"
    output_dir = results / f"{label}-{suite_name}"
    output_dir.mkdir()
    command = (
        sys.executable, str(framework_main),
        f"--test_cfg={test_config}",
        f"--temp_dir={staging / (label + '-' + suite_name + '-temp')}",
        f"--log_dir={output_dir / 'maple-log'}",
        "--fail_exit", "-p", "FAIL", str(target),
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
    pass_summary = f"Total: {expected_count}, PASS: {expected_count}, FAIL: 0"
    if completed.returncode != 0 or pass_summary not in output:
        raise RuntimeError(
            f"{label} {suite_name} Maple LLT failed (exit {completed.returncode}); "
            f"inspect {output_dir / 'runner.log'}"
        )
    print(
        f"PASS {label}: Maple {suite_name} {expected_count}/{expected_count}, "
        f"{time.monotonic() - started:.2f}s; cjpm SHA-256 {file_sha256(executable)}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--config-suite", type=Path, required=True)
    parser.add_argument("--missing-repository-case", type=Path, required=True)
    parser.add_argument("--test-config", type=Path, required=True)
    parser.add_argument("--official-cjpm", type=Path, required=True)
    parser.add_argument("--enhanced-cjpm", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    framework_main = require_file(args.framework / "main.py", "Maple main.py")
    fixture = args.fixture.expanduser().resolve()
    require_file(fixture / f"{FIXTURE_NAME}.info", "official LLT case")
    require_file(fixture / "run_matrix.sh", "official LLT script")
    config_suite = args.config_suite.expanduser().resolve()
    if not config_suite.is_dir() or len(tuple(config_suite.rglob("*.info"))) != 3:
        raise ValueError(f"Expected the three official cjpm config LLT cases: {config_suite}")
    missing_repository_case = require_file(
        args.missing_repository_case, "official missing-repository LLT case",
    )
    if missing_repository_case.name != "central_repository_missing.info":
        raise ValueError(f"Unexpected missing-repository case: {missing_repository_case}")
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
                    label, FIXTURE_NAME, executable, framework_main,
                    copied_config, fixture_info, 1, staging, results,
                )
                # Directory-mode Maple resolves testlist beside test.cfg.
                run_case(
                    label, "config", executable, framework_main,
                    config, config_suite, 3, staging, results,
                )
                run_case(
                    label, "central_repository_missing", executable, framework_main,
                    config, missing_repository_case, 1, staging, results,
                )
    finally:
        try:
            temp_parent.rmdir()
        except OSError:
            pass
    print(f"All selected Maple LLT cases passed for both binaries. Logs: {results}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
