#!/usr/bin/env python3
"""Compare the official local cjpm bundle LLT or selected HLT cases on both binaries."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import uuid
from pathlib import Path

from maple_smoke import file_sha256, require_file, run_case


EXPECTED_CASES = 23
HLT_EXCLUDED = {
    "bundle_build_03", "bundle_build_04", "bundle_build_06",  # no Linux EXEC directive
    "bundle_include_23", "bundle_include_28",  # separate Python-generated fixture setup
    "bundle_verify_03",  # dependency lookup outside this offline subset
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--bundle-suite", type=Path, required=True)
    parser.add_argument("--test-config", type=Path, required=True)
    parser.add_argument("--official-cjpm", type=Path, required=True)
    parser.add_argument("--enhanced-cjpm", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--level", choices=("LLT", "HLT"), default="LLT")
    args = parser.parse_args()
    framework_main = require_file(args.framework / "main.py", "Maple main.py")
    config = require_file(args.test_config, "official test configuration")
    official = require_file(args.official_cjpm, "official cjpm")
    enhanced = require_file(args.enhanced_cjpm, "enhanced cjpm")
    if official == enhanced:
        raise ValueError("Official and enhanced cjpm paths must differ")
    bundle_suite = args.bundle_suite.expanduser().resolve()
    cases = sorted(bundle_suite.glob("*/*.info"))
    expected = EXPECTED_CASES if args.level == "LLT" else 101
    if len(cases) != expected:
        raise ValueError(f"Expected {expected} bundle {args.level} cases, found {len(cases)}")
    if args.level == "HLT":
        if not HLT_EXCLUDED.issubset({case.parent.name for case in cases}):
            raise ValueError("Official HLT layout changed; review the offline selection")
        cases = [case for case in cases if case.parent.name not in HLT_EXCLUDED]
    for case in cases:
        # Explicitly reject unexpected commands before executing this official test snapshot.
        commands = [line.removeprefix("// EXEC:").strip()
                    for line in case.read_text().splitlines() if line.startswith("// EXEC:")]
        if len(commands) != 1 or not commands[0].startswith("cd %n && %cjpm bundle "):
            raise ValueError(f"Review changed bundle command before running: {case}")
        if any(word in commands[0] for word in ("curl", "wget", "publish", "http://", "https://")):
            raise ValueError(f"External operation found in bundle case: {case}")
        if args.level == "HLT":
            for config_file in case.parent.rglob("*.toml"):
                section = ""
                for line in config_file.read_text().splitlines():
                    line = line.strip().lower()
                    if not line or line.startswith("#"):
                        continue
                    if any(word in line for word in ("http://", "https://", "git =", "repository =")):
                        raise ValueError(f"External configuration found in HLT case: {config_file}")
                    if line.startswith("["):
                        section = line
                    elif "dependencies" in section:
                        raise ValueError(f"Dependency lookup found in HLT case: {config_file}")
    results = args.results_dir.expanduser().resolve() / f"bundle-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    results.mkdir(parents=True)
    (results / "selection.json").write_text(json.dumps(dict(level=args.level,
        official_sha256=file_sha256(official), enhanced_sha256=file_sha256(enhanced),
        config_sha256=file_sha256(config),
        excluded=sorted(HLT_EXCLUDED) if args.level == "HLT" else [],
        cases={case.parent.name: file_sha256(case) for case in cases}), indent=2), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="maple-local-bundle-") as raw:
        staging = Path(raw)
        for label, executable in (("official", official), ("enhanced", enhanced)):
            for case in cases:
                run_case(label, case.parent.name, executable, framework_main, config,
                         case, 1, staging, results, isolate_home=True)
    print(f"PASS: official local bundle {args.level} {len(cases)}/{len(cases)} on both binaries; logs: {results}")


if __name__ == "__main__":
    main()
