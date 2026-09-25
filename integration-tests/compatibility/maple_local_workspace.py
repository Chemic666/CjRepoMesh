#!/usr/bin/env python3
"""Compare the official local cjpm workspace LLT cases on both binaries."""

from __future__ import annotations

import argparse
import tempfile
import time
import uuid
from pathlib import Path

from maple_smoke import require_file, run_case


EXPECTED_CASES = 52
FORBIDDEN = ("curl", "wget", "publish", "http://", "https://", "git@", "ssh ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--workspace-suite", type=Path, required=True)
    parser.add_argument("--test-config", type=Path, required=True)
    parser.add_argument("--official-cjpm", type=Path, required=True)
    parser.add_argument("--enhanced-cjpm", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    framework_main = require_file(args.framework / "main.py", "Maple main.py")
    config = require_file(args.test_config, "official test configuration")
    official = require_file(args.official_cjpm, "official cjpm")
    enhanced = require_file(args.enhanced_cjpm, "enhanced cjpm")
    if official == enhanced:
        raise ValueError("Official and enhanced cjpm paths must differ")

    suite = args.workspace_suite.expanduser().resolve()
    cases = sorted(suite.rglob("*.info"))
    if len(cases) != EXPECTED_CASES:
        raise ValueError(f"Expected {EXPECTED_CASES} workspace cases, found {len(cases)}")
    for case in cases:
        commands = [line.split(":", 1)[1].strip() for line in case.read_text().splitlines()
                    if line.startswith("// EXEC")]
        if not commands or any(not command.startswith("cd %n") for command in commands):
            raise ValueError(f"Review changed workspace commands before running: {case}")
        if any(word in command.lower() for command in commands for word in FORBIDDEN):
            raise ValueError(f"External operation found in workspace case: {case}")
        if not any("%cjpm " in command for command in commands):
            raise ValueError(f"Workspace case has no cjpm command: {case}")
    for config_file in suite.rglob("*.toml"):
        lines = (line.strip().lower() for line in config_file.read_text().splitlines())
        if any(any(word in line for word in FORBIDDEN) or "git =" in line
               for line in lines if line and not line.startswith("#")):
            raise ValueError(f"External dependency found in workspace case: {config_file}")

    results = args.results_dir.expanduser().resolve() / f"workspace-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    results.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="maple-local-workspace-") as raw:
        staging = Path(raw)
        for label, executable in (("official", official), ("enhanced", enhanced)):
            for case in cases:
                run_case(label, case.parent.name, executable, framework_main, config,
                         case, 1, staging, results, isolate_home=True)
    print(f"PASS: official local workspace LLT {EXPECTED_CASES}/{EXPECTED_CASES} on both binaries; logs: {results}")


if __name__ == "__main__":
    main()
