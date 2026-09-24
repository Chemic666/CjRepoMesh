#!/usr/bin/env python3
"""Compare the official local cjpm bundle LLT cases on both binaries."""

from __future__ import annotations

import argparse
import tempfile
import time
import uuid
from pathlib import Path

from maple_smoke import require_file, run_case


EXPECTED_CASES = 23


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--bundle-suite", type=Path, required=True)
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
    bundle_suite = args.bundle_suite.expanduser().resolve()
    cases = sorted(bundle_suite.glob("*/*.info"))
    if len(cases) != EXPECTED_CASES:
        raise ValueError(f"Expected {EXPECTED_CASES} local bundle cases, found {len(cases)}")
    for case in cases:
        # Explicitly reject unexpected commands before executing this official test snapshot.
        commands = [line.removeprefix("// EXEC:").strip()
                    for line in case.read_text().splitlines() if line.startswith("// EXEC:")]
        if len(commands) != 1 or not commands[0].startswith("cd %n && %cjpm bundle "):
            raise ValueError(f"Review changed bundle command before running: {case}")
        if any(word in commands[0] for word in ("curl", "wget", "publish", "http://", "https://")):
            raise ValueError(f"External operation found in bundle case: {case}")
    results = args.results_dir.expanduser().resolve() / f"bundle-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    results.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="maple-local-bundle-") as raw:
        staging = Path(raw)
        for label, executable in (("official", official), ("enhanced", enhanced)):
            for case in cases:
                run_case(label, case.parent.name, executable, framework_main, config,
                         case, 1, staging, results, isolate_home=True)
    print(f"PASS: official local bundle LLT {EXPECTED_CASES}/{EXPECTED_CASES} on both binaries; logs: {results}")


if __name__ == "__main__":
    main()
