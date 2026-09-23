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
FIXTURE_PORTS = (39137, 39138, 39139)


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


def occupied_ports() -> list[int]:
    occupied = []
    for port in FIXTURE_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                occupied.append(port)
    return occupied


def wait_for_port_release() -> None:
    for _ in range(50):
        if not occupied_ports():
            return
        time.sleep(0.1)
    raise RuntimeError(f"Official fixture ports still listening: {occupied_ports()}")


def normalized_fixture(source: Path, destination: Path, name: str) -> Path:
    target = destination / name
    shutil.copytree(source, target)
    # The official fixture's end-anchored sed expressions and shell shebangs
    # require LF. Modify only the per-run copy, never the upstream checkout.
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".toml", ".cj"}:
            contents = path.read_bytes()
            path.write_bytes(contents.replace(b"\r\n", b"\n"))
    return target / f"{name}.info"


def stabilized_archive_fixture(source: Path, destination: Path) -> tuple[Path, Path]:
    target = destination / "repository_archive_matrix"
    shutil.copytree(source, target)
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".toml", ".cj"}:
            contents = path.read_bytes()
            path.write_bytes(contents.replace(b"\r\n", b"\n"))
    server = target / "server.py"
    original = server.read_text(encoding="utf-8")
    if (original.count('tarfile.open(fileobj=output, mode="w:gz")') != 1 or
            original.count("LICENSE_CJ = ") != 1):
        raise ValueError("Official archive fixture changed; review stabilization before running")
    # The upstream server regenerates an archive for index and package GETs.
    # gzip's current-time header makes those bytes differ across a second.
    # Pin only the per-run fixture's gzip mtime; package contents are unchanged.
    patch = (
        "import gzip as _fixture_gzip\n"
        "from functools import partial as _fixture_partial\n"
        "_fixture_gzip.GzipFile = _fixture_partial(_fixture_gzip.GzipFile, mtime=0)\n\n"
    )
    stabilized = original.replace("LICENSE_CJ = ", patch + "LICENSE_CJ = ", 1)
    compile(stabilized, str(server), "exec")
    server.write_text(stabilized, encoding="utf-8")
    return target / "repository_archive_matrix.info", server


def run_case(
    label: str, suite_name: str, executable: Path, framework_main: Path,
    test_config: Path, target: Path, expected_count: int,
    staging: Path, results: Path, isolate_home: bool = False,
) -> None:
    if occupied_ports():
        raise RuntimeError(f"Fixture ports in use before {label} run: {occupied_ports()}")
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("CJREPO_") or key.startswith("CJREPOMESH_"):
            env.pop(key)
    env.pop("CJPM_CONFIG", None)
    path_prefix = str(executable.parent)
    if isolate_home:
        isolated_home = staging / f"{label}-{suite_name}-home"
        isolated_home.mkdir()
        env["HOME"] = str(isolated_home)
        path_prefix = f"{isolated_home / '.cjpm' / 'bin'}{os.pathsep}{path_prefix}"
    env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
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
    parser.add_argument("--install-coverage", type=Path, required=True)
    parser.add_argument("--install-local-suite", type=Path, required=True)
    parser.add_argument("--uninstall-suite", type=Path, required=True)
    parser.add_argument("--update-wrong-config", type=Path, required=True)
    parser.add_argument("--update-coverage", type=Path, required=True)
    parser.add_argument("--archive-fixture", type=Path, required=True)
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
    install_coverage = args.install_coverage.expanduser().resolve()
    if not install_coverage.is_dir():
        raise ValueError(f"Official install coverage directory not found: {install_coverage}")
    install_cases = (
        "central_repository_missing",
        "repository_cached",
        "git_install_invalid_config",
        "git_install_options",
        "git_install_workspace",
    )
    install_infos = {
        name: require_file(install_coverage / name / f"{name}.info", f"official {name} LLT case")
        for name in install_cases
    }
    install_local_suite = args.install_local_suite.expanduser().resolve()
    if not install_local_suite.is_dir() or len(tuple(install_local_suite.rglob("*.info"))) != 17:
        raise ValueError(f"Expected 17 official local-install LLT cases: {install_local_suite}")
    uninstall_suite = args.uninstall_suite.expanduser().resolve()
    if not uninstall_suite.is_dir() or len(tuple(uninstall_suite.rglob("*.info"))) != 4:
        raise ValueError(f"Expected four official uninstall LLT cases: {uninstall_suite}")
    update_wrong_config = args.update_wrong_config.expanduser().resolve()
    if not update_wrong_config.is_dir() or len(tuple(update_wrong_config.rglob("*.info"))) != 2:
        raise ValueError(f"Expected two official cjpm update config LLT cases: {update_wrong_config}")
    update_coverage = args.update_coverage.expanduser().resolve()
    update_cases = (
        "central_dependency_cached_update",
        "central_dependency_empty_version",
        "git_invalid_remote",
        "update_skip_script",
        "update_unknown_option",
        "workspace_missing_member",
    )
    update_infos = {
        name: require_file(update_coverage / name / f"{name}.info", f"official {name} LLT case")
        for name in update_cases
    }
    refresh_fixture = update_coverage / "local_index_refresh"
    require_file(refresh_fixture / "local_index_refresh.info", "official local index refresh LLT case")
    require_file(refresh_fixture / "run_refresh.sh", "official local index refresh script")
    require_file(refresh_fixture / "server.py", "official local index refresh server")
    archive_fixture = args.archive_fixture.expanduser().resolve()
    require_file(archive_fixture / "repository_archive_matrix.info", "official archive LLT case")
    require_file(archive_fixture / "run_archive_matrix.sh", "official archive LLT script")
    require_file(archive_fixture / "server.py", "official archive LLT server")
    config = require_file(args.test_config, "official test configuration")
    official = require_file(args.official_cjpm, "official cjpm")
    enhanced = require_file(args.enhanced_cjpm, "enhanced cjpm")
    if official == enhanced:
        raise ValueError("Official and enhanced cjpm paths must differ")
    if occupied_ports():
        raise RuntimeError(f"Fixture ports already in use: {occupied_ports()}")

    results_parent = args.results_dir.expanduser().resolve()
    results_parent.mkdir(parents=True, exist_ok=True)
    results = results_parent / f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    results.mkdir()
    temp_parent = Path(__file__).resolve().parent.parent / ".tmp"
    temp_parent.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="maple-smoke-", dir=temp_parent) as raw:
            staging = Path(raw)
            fixture_info = normalized_fixture(fixture, staging, FIXTURE_NAME)
            refresh_info = normalized_fixture(refresh_fixture, staging, "local_index_refresh")
            archive_info, stabilized_server = stabilized_archive_fixture(archive_fixture, staging)
            (results / "archive-fixture-adjustment.txt").write_text(
                "repository_archive_matrix/server.py: test-copy only, gzip mtime pinned to 0\n"
                f"official server SHA-256: {file_sha256(archive_fixture / 'server.py')}\n"
                f"stabilized server SHA-256: {file_sha256(stabilized_server)}\n",
                encoding="utf-8",
            )
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
                for case_name, case_info in install_infos.items():
                    run_case(
                        label, case_name, executable, framework_main,
                        config, case_info, 1, staging, results,
                    )
                run_case(
                    label, "install_local", executable, framework_main,
                    config, install_local_suite, 17, staging, results, isolate_home=True,
                )
                run_case(
                    label, "uninstall", executable, framework_main,
                    config, uninstall_suite, 4, staging, results, isolate_home=True,
                )
                run_case(
                    label, "update_wrong_config", executable, framework_main,
                    config, update_wrong_config, 2, staging, results,
                )
                for case_name, case_info in update_infos.items():
                    run_case(
                        label, case_name, executable, framework_main,
                        config, case_info, 1, staging, results, isolate_home=True,
                    )
                run_case(
                    label, "local_index_refresh", executable, framework_main,
                    copied_config, refresh_info, 1, staging, results, isolate_home=True,
                )
                run_case(
                    label, "repository_archive_matrix_stabilized", executable,
                    framework_main, config, archive_info, 1, staging, results,
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
