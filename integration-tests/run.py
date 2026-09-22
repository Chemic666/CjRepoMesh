#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from lib.harness import TestFailure, platform_executable
from lib.suites import SUITES, TestContext


def default_cjpm(project_root: Path) -> Path:
    candidates = (
        platform_executable(project_root / "cjpm" / "dist" / "cjpm"),
        platform_executable(project_root / "cjpm" / "target" / "release" / "bin" / "cjpm"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def parse_args(project_root: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cross-platform CjRepoMesh core integration suites."
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=tuple(SUITES),
        help="Run one suite; repeat to select multiple suites. Defaults to all core suites.",
    )
    parser.add_argument(
        "--cjpm",
        type=Path,
        default=default_cjpm(project_root),
        help="Path to the enhanced cjpm executable.",
    )
    parser.add_argument(
        "--server",
        type=Path,
        default=platform_executable(project_root / "server" / "target" / "release" / "bin" / "main"),
        help="Path to the CjRepo Server executable.",
    )
    parser.add_argument(
        "--skip-server-build",
        action="store_true",
        help="Reuse an existing CjRepo Server binary instead of building it once.",
    )
    return parser.parse_args()


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    args = parse_args(project_root)
    cjpm = args.cjpm.expanduser().resolve()
    server = args.server.expanduser().resolve()
    if not cjpm.is_file():
        raise TestFailure(f"Enhanced cjpm executable not found: {cjpm}")

    selected = args.suite or list(SUITES)
    context = TestContext(
        project_root,
        cjpm,
        server,
        build=not args.skip_server_build,
    )
    results: list[tuple[str, float]] = []
    total_started = time.monotonic()
    try:
        context.cleanup_generated()
        for key in selected:
            name, suite = SUITES[key]
            print(f"\n=== {name} ===", flush=True)
            started = time.monotonic()
            suite(context)
            elapsed = time.monotonic() - started
            results.append((name, elapsed))
            print(f"=== {name}: PASS ({elapsed:.2f}s) ===", flush=True)
    finally:
        context.close()

    print("\n=== CjRepoMesh core integration summary ===")
    width = max(len(name) for name, _elapsed in results)
    for name, elapsed in results:
        print(f"{name:<{width}}  PASS  {elapsed:8.2f}s")
    print(f"All {len(results)} core suites passed in {time.monotonic() - total_started:.2f} seconds.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
