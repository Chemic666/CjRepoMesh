#!/usr/bin/env python3
"""Compare legacy repository.home behavior against the unmodified cjpm base."""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
import uuid
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TESTS_ROOT))

from lib.harness import (  # noqa: E402
    ManagedProcesses,
    TestFailure,
    assert_contains,
    assert_equal,
    assert_ports_available,
    remove_within,
    run_command,
    wait_for_port,
    wait_for_ports_closed,
)

PORT = 39142
OFFICIAL_FIXTURE_PORT = 39137
MARKER = "low-2.0.0"


def normalized_output(output: str) -> str:
    return "\n".join(line.rstrip() for line in output.splitlines() if line.strip())


def assert_same_text(label: str, original: str, enhanced: str) -> None:
    if original == enhanced:
        return
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            enhanced.splitlines(),
            fromfile="official",
            tofile="enhanced",
            lineterm="",
        )
    )
    raise TestFailure(f"{label} differs between official and enhanced cjpm:\n{diff}")


def prepare_app(
    source: Path, destination: Path, *, requirement: str, include_company_auth: bool
) -> None:
    destination.mkdir(parents=True)
    (destination / "src").mkdir()
    shutil.copy2(source / "cangjie-repo.toml", destination / "cangjie-repo.toml")
    source_text = (source / "src" / "main.cj").read_text(encoding="utf-8")
    if include_company_auth:
        source_text = source_text.replace(
            "import meshdep.*", "import meshdep.*\nimport company::auth.*"
        ).replace(
            "println(registryMarker())",
            "println(registryMarker())\n    println(authRegistryMarker())",
        )
    (destination / "src" / "main.cj").write_text(source_text, encoding="utf-8")
    manifest = (source / "cjpm.toml").read_text(encoding="utf-8")
    if 'meshdep = "2.0.0"' not in manifest:
        raise TestFailure("Legacy fixture no longer contains the expected dependency")
    manifest = manifest.replace('meshdep = "2.0.0"', f'meshdep = "{requirement}"')
    if include_company_auth:
        manifest += '\n"company::auth" = "1.0.0"\n'
    (destination / "cjpm.toml").write_text(manifest, encoding="utf-8")


def compare_case(
    official: Path,
    enhanced: Path,
    source: Path,
    work_root: Path,
    *,
    name: str,
    requirement: str,
    include_company_auth: bool = False,
    env: dict[str, str],
) -> None:
    official_app = work_root / name / "official"
    enhanced_app = work_root / name / "enhanced"
    for app in (official_app, enhanced_app):
        prepare_app(
            source, app,
            requirement=requirement,
            include_company_auth=include_company_auth,
        )

    official_run = run_command((official, "run"), cwd=official_app, env=env)
    enhanced_run = run_command((enhanced, "run"), cwd=enhanced_app, env=env)
    assert_contains(official_run.output, MARKER, label="official run output")
    assert_contains(enhanced_run.output, MARKER, label="enhanced run output")
    if include_company_auth:
        assert_contains(official_run.output, "private-1.0.0", label="official run output")
        assert_contains(enhanced_run.output, "private-1.0.0", label="enhanced run output")

    official_lock = (official_app / "cjpm.lock").read_text(encoding="utf-8")
    enhanced_lock = (enhanced_app / "cjpm.lock").read_text(encoding="utf-8")
    assert_same_text(f"{name} cjpm.lock", official_lock, enhanced_lock)
    if 'version = "2.0.0"' not in official_lock:
        raise TestFailure(f"{name} lockfile did not select meshdep 2.0.0")

    official_tree = run_command((official, "tree", "--no-tests"), cwd=official_app, env=env)
    enhanced_tree = run_command((enhanced, "tree", "--no-tests"), cwd=enhanced_app, env=env)
    assert_same_text(
        f"{name} dependency tree",
        normalized_output(official_tree.output),
        normalized_output(enhanced_tree.output),
    )
    assert_contains(official_tree.output, "meshdep", label="official dependency tree")
    if include_company_auth:
        assert_contains(official_tree.output, "auth", label="official dependency tree")

    for app in (official_app, enhanced_app):
        cache = app / "cache" / "repository"
        if not (cache / "index" / "default" / "me" / "sh" / "meshdep").is_file():
            raise TestFailure(f"Legacy index cache layout is missing: {app}")
        if (cache / "registries").exists():
            raise TestFailure(f"Legacy app unexpectedly used a multi-registry cache: {app}")
    print(f"PASS {name}: selected version, lockfile, dependency tree, legacy cache", flush=True)


def run_official_fixture(
    executable: Path, fixture: Path, work_root: Path, *, label: str, env: dict[str, str]
) -> int:
    destination = work_root / f"official-llt-{label}"
    shutil.copytree(fixture, destination)
    # The upstream sed expressions anchor to end of line. A Windows checkout's
    # CRLF would prevent fixture renames as well as break the shell script.
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".toml", ".cj"}:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    expected = [
        line.split("// ASSERT: scan ", 1)[1].strip()
        for line in (destination / "http_status_matrix.info").read_text(encoding="utf-8").splitlines()
        if "// ASSERT: scan " in line
    ]
    if not expected:
        raise TestFailure("Official LLT fixture has no status assertions")
    fixture_env = dict(env)
    fixture_env["PATH"] = f"{executable.parent}{os.pathsep}{fixture_env['PATH']}"
    assert_ports_available((OFFICIAL_FIXTURE_PORT,))
    try:
        result = run_command(("bash", "run_matrix.sh"), cwd=destination, env=fixture_env)
    finally:
        wait_for_ports_closed((OFFICIAL_FIXTURE_PORT,))
    missing = [message for message in expected if message not in result.output]
    if missing:
        raise TestFailure(
            f"{label} missed {len(missing)} official LLT assertions:\n"
            + "\n".join(missing)
            + "\nObserved publish output:\n"
            + "\n".join(
                line for line in result.output.splitlines()
                if "publish" in line.lower() or "error" in line.lower()
            )[-3000:]
        )
    print(f"PASS {label}: {len(expected)} official repository HTTP status assertions", flush=True)
    return len(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-cjpm", type=Path, required=True)
    parser.add_argument("--enhanced-cjpm", type=Path, required=True)
    parser.add_argument(
        "--official-fixture",
        type=Path,
        help="Path to the upstream cangjie_test http_status_matrix directory.",
    )
    parser.add_argument(
        "--only-official-fixture",
        action="store_true",
        help="Run only upstream LLT status assertions; requires --official-fixture.",
    )
    args = parser.parse_args()
    if args.only_official_fixture and not args.official_fixture:
        parser.error("--only-official-fixture requires --official-fixture")
    official = args.official_cjpm.resolve()
    enhanced = args.enhanced_cjpm.resolve()
    for executable in (official, enhanced):
        if not executable.is_file():
            raise TestFailure(f"cjpm executable not found: {executable}")

    fixture_root = TESTS_ROOT / "multirepo"
    temp_parent = TESTS_ROOT / ".tmp"
    temp_parent.mkdir(exist_ok=True)
    work_root = (temp_parent / f"compat-{os.getpid()}-{uuid.uuid4().hex[:8]}").resolve()
    work_root.mkdir()
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("CJREPO_") or key.startswith("CJREPOMESH_"):
            env.pop(key)

    packages = ("meshdep-v1-low", "meshdep-v2-low", "company-auth-v1-private")
    generated = [fixture_root / "packages" / package / "target" for package in packages]
    request_logs = (
        fixture_root / "low.requests.log",
        fixture_root / "legacy-mixed.requests.log",
    )
    owns_generated = False
    try:
        if not args.only_official_fixture:
            existing = [path for path in (*generated, *request_logs) if path.exists()]
            if existing:
                raise TestFailure(
                    "Refusing to replace pre-existing fixture output: "
                    + ", ".join(str(path) for path in existing)
                )
            owns_generated = True
            assert_ports_available((PORT,))
            for package in packages:
                run_command((enhanced, "bundle"), cwd=fixture_root / "packages" / package, env=env)
            with ManagedProcesses() as processes:
                low_server = processes.start(
                    (sys.executable, fixture_root / "server.py", str(PORT), "low"),
                    cwd=fixture_root,
                )
                wait_for_port(PORT)
                source = fixture_root / "app-legacy"
                compare_case(
                    official, enhanced, source, work_root,
                    name="pinned", requirement="2.0.0", env=env,
                )
                compare_case(
                    official, enhanced, source, work_root,
                    name="range", requirement="[1.0.0, 3.0.0)", env=env,
                )
                processes.stop(low_server)
                wait_for_ports_closed((PORT,))
                processes.start(
                    (sys.executable, fixture_root / "server.py", str(PORT), "legacy-mixed"),
                    cwd=fixture_root,
                )
                wait_for_port(PORT)
                compare_case(
                    official, enhanced, source, work_root,
                    name="mixed", requirement="[1.0.0, 3.0.0)",
                    include_company_auth=True, env=env,
                )
            wait_for_ports_closed((PORT,))
            print("All 3 official-versus-enhanced legacy cases passed.", flush=True)
        if args.official_fixture:
            fixture = args.official_fixture.resolve()
            if not (fixture / "http_status_matrix.info").is_file():
                raise TestFailure(f"Official LLT fixture not found: {fixture}")
            official_count = run_official_fixture(
                official, fixture, work_root, label="official cjpm", env=env
            )
            enhanced_count = run_official_fixture(
                enhanced, fixture, work_root, label="enhanced cjpm", env=env
            )
            assert_equal(enhanced_count, official_count, label="official LLT assertion count")
        return 0
    finally:
        if owns_generated:
            for path in generated:
                remove_within(path, (TESTS_ROOT,))
            for path in request_logs:
                remove_within(path, (TESTS_ROOT,))
        remove_within(work_root, (TESTS_ROOT,))
        try:
            temp_parent.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
