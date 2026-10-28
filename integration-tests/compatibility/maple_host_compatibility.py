#!/usr/bin/env python3
"""Prepare seven reviewed, owned-copy Maple fixture corrections.

The official snapshot and historical failures remain unchanged. Adapted results
are compatibility evidence, never an official-suite score. Without --execute,
this only freezes inputs and prepares an inspectable pack; it runs no commands.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from maple_reviewed import file_sha256, preflight, snapshot_tree


PREFIX = "testsuites/LLT/Tools/cjpm/CJNATIVE/"
CASES = {
    "run21": "run/run_21/run_21.info",
    "git08": "build/git_local/multiple_module_git_08/multiple_module_git_08.info",
    "sameTarget": "cross_compile/case_04/case_04.info",
    "combined": "cross_compile/combined_01/combined_01.info",
    "macro": "cross_compile/macro_cross_01/macro_cross_01.info",
    "quoting": "target/cross_compile/linux2windows_cross_compile_02/linux2windows_cross_compile_02.info",
    "unixCondition": "test/test_configuration/testConfiguration_07/testConfiguration_07.info",
}
REASONS = {
    "run21": "Keep the intentional exception; assert failure diagnostics and direct cjpm exit 1.",
    "git08": "Correct the arithmetic oracle: imported constants 24 + 25 equal 49.",
    "sameTarget": "Use the existing same-platform diagnostic; retain ignore-target and compile-count assertions.",
    "combined": "Declare missing binary dependencies, following native build/combined/combined_09; retain all original assertions.",
    "macro": "The command builds; assert build success and actual host macro execution.",
    "quoting": "Match quoted compound linker argument while retaining option order and exact occurrence count.",
    "unixCondition": "Enable the fixture's existing Unix command in the owned Linux configuration.",
}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_once(root: Path, relative: str, old: str, new: str,
                 case_id: str, changes: list[dict]) -> None:
    path = root / relative
    before = path.read_bytes()
    newline = "\r\n" if b"\r\n" in before else "\n"
    expected = old.replace("\n", newline).encode()
    replacement = new.replace("\n", newline).encode()
    if before.count(expected) != 1:
        raise ValueError(f"Expected exactly one reviewed patch anchor: {relative}")
    after = before.replace(expected, replacement, 1)
    old_sha = file_sha256(path)
    path.write_bytes(after)
    changes.append(dict(case=case_id, path=relative, reason=REASONS[case_id],
                        originalSha256=old_sha, adaptedSha256=file_sha256(path),
                        diff="".join(difflib.unified_diff(
                            before.decode().splitlines(keepends=True),
                            after.decode().splitlines(keepends=True),
                            fromfile="original/" + relative, tofile="adapted/" + relative))))


def apply_corrections(root: Path, config: str) -> list[dict]:
    changes: list[dict] = []
    patch = lambda case, relative, old, new: replace_once(root, relative, old, new, case, changes)
    info = lambda case: PREFIX + CASES[case]
    patch("run21", info("run21"), "// ASSERT: scan cjpm run finished",
          "// EXEC-1: cd %n && %cjpm run --skip-build\n"
          "// ASSERT: scan NegativeArraySizeException: I am an Exception!\n"
          "// ASSERT: scan Error: cjpm run failed\n"
          "// ASSERT: scan-not cjpm run finished")
    git_source = str(Path(info("git08")).parent / "src/main.cj").replace("\\", "/")
    patch("git08", git_source, "res2 != 75", "res2 != 49")
    patch("sameTarget", info("sameTarget"), "the current specific is", "the current platform is")
    combined_dir = Path(info("combined")).parent.as_posix()
    binary_paths = {
        "binDep/cjpm.toml": ["../staticDep"],
        "dep/cjpm.toml": ["../binDep", "../staticDep"],
        "cjpm.toml": ["./dep", "./binDep", "./staticDep"],
    }
    for toml, dependencies in binary_paths.items():
        relative = combined_dir + "/" + toml
        # The corresponding native fixture explicitly declares these same
        # directories. Cross compilation adds the target directory segment.
        paths = [f"{dep}/target/x86_64-w64-mingw32/release/{dep.split('/')[-1]}"
                 for dep in dependencies]
        addition = ("\n[target.x86_64-w64-mingw32.bin-dependencies]\n"
                    "  path-option = " + json.dumps(paths) + "\n")
        content = (root / relative).read_text(encoding="utf-8")
        if "bin-dependencies" in content:
            raise ValueError(f"Binary dependency fixture was already changed: {relative}")
        # Match the entire reviewed file so a repeated final line cannot select
        # an earlier TOML setting; every existing byte is retained.
        patch("combined", relative, content, content + addition)
    patch("macro", info("macro"), "// ASSERT: scan cjpm test success",
          "// ASSERT: scan cjpm build success\n"
          "// ASSERT: scan I'm in macro body\n"
          "// ASSERT: scan dep.aoo")
    patch("quoting", info("quoting"),
          "// ASSERT: scan-1 -O1 -O2 -Woff all --link-options -s -s -s",
          '// ASSERT: scan-1 -O1 -O2 -Woff all --link-options "-s -s -s"')
    patch("unixCondition", config, "    VOO\n", "    VOO\n    Unix\n")
    return changes


def original_observations(paths: list[Path], selected: set[str]) -> list[dict]:
    observations = []
    for path in paths:
        summary = json.loads(path.read_text(encoding="utf-8"))
        for row in summary.get("cases", []):
            if row.get("path") in selected:
                observations.append(dict(summary=str(path.resolve()), summarySha256=file_sha256(path),
                                         clientSha256=summary.get("clientSha256"), record=row))
    return observations


def run_reviewed(manifest: Path, upstream: Path, framework: Path, client: Path,
                 results: Path, stage_parent: Path, timeout: int) -> dict:
    runner = Path(__file__).with_name("maple_reviewed.py")
    command = [sys.executable, str(runner), "--manifest", str(manifest),
               "--upstream", str(upstream), "--framework", str(framework),
               "--client", str(client), "--results", str(results),
               "--stage-parent", str(stage_parent), "--timeout", str(timeout), "--execute"]
    completed = subprocess.run(command, capture_output=True, text=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    log = results.with_suffix(".runner.log")
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    summary_path = results / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
    return dict(command=command, returncode=completed.returncode, log=str(log),
                logSha256=file_sha256(log), summary=summary,
                summarySha256=file_sha256(summary_path) if summary_path.is_file() else None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "upstream", "framework", "client", "pack"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--client-sha256", required=True,
                        help="Explicitly approved current client hash; may differ from historical manifest")
    parser.add_argument("--original-summary", type=Path, action="append", default=[])
    parser.add_argument("--stage-parent", type=Path,
                        default=Path(__file__).resolve().parent.parent / ".tmp")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--original", action="store_true", help="Also re-execute all seven original fixtures")
    args = parser.parse_args()
    if args.original and not args.execute:
        raise ValueError("--original requires --execute")
    if args.execute and (sys.platform != "linux" or args.timeout < 1):
        raise ValueError("Execution requires Linux and a positive timeout")
    pack, upstream, framework, client = (value.resolve() for value in
                                         (args.pack, args.upstream, args.framework, args.client))
    if pack.exists() or any(pack.is_relative_to(root) for root in
                            (upstream, framework, Path(__file__).resolve().parents[2])):
        raise ValueError("Require a new private pack outside the official and product source trees")
    source_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    by_path = {row["path"]: row for row in source_manifest["cases"]}
    selected = {PREFIX + path for path in CASES.values()}
    original = deepcopy(source_manifest)
    original["cases"] = [deepcopy(by_path[PREFIX + path]) for path in CASES.values()]
    original["clientSha256"] = args.client_sha256
    preflight(original, upstream, framework, client)
    history = original_observations(args.original_summary, selected)
    runner_hashes = {name: file_sha256(Path(__file__).with_name(name)) for name in
                     ("maple_host_compatibility.py", "maple_reviewed.py", "maple_smoke.py")}
    pack.mkdir(parents=True, exist_ok=False)
    owned = pack / "adapted-inputs"
    for row in original["cases"]:
        if row.get("dependencies"):
            raise ValueError("These seven corrections admit no additional external fixture dependencies")
        relative = Path(row["path"]).parent
        shutil.copytree(upstream / relative, owned / relative)
    config = original["config"]
    (owned / config).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(upstream / config, owned / config)
    changes = apply_corrections(owned, config)
    adapted = deepcopy(original)
    adapted["configSha256"] = file_sha256(owned / config)
    for case_id, row in zip(CASES, adapted["cases"]):
        row["files"] = snapshot_tree((owned / row["path"]).parent)
        row["reason"] = "OWNED-COPY COMPATIBILITY CORRECTION: " + REASONS[case_id]
    preflight(adapted, owned, framework, client)
    write_json(pack / "original-manifest.json", original)
    write_json(pack / "adapted-manifest.json", adapted)
    write_json(pack / "changes.json", dict(changes=changes))
    (pack / "changes.diff").write_text("\n".join(row["diff"] for row in changes), encoding="utf-8")
    report = dict(schema=1, scope="reviewed-host-compatibility", notOfficialSuiteScore=True,
                  sourceManifestSha256=file_sha256(args.manifest),
                  historicalManifestClientSha256=source_manifest.get("clientSha256"),
                  clientSha256=file_sha256(client), runnerHashes=runner_hashes,
                  originalObservations=history, changes=changes,
                  requested=7, executed=0, counts={}, status="PREPARED_NOT_EXECUTED")
    write_json(pack / "comparison.json", report)
    if not args.execute:
        print(f"PREPARED: {pack}; seven adapted fixtures; zero commands executed")
        return 0
    # Use the existing runner's owned, per-case staging and strict Maple status
    # extraction; this adapter does not synthesize a PASS from process success.
    if not args.stage_parent.is_dir() or args.stage_parent.is_symlink():
        raise ValueError("Require the existing owned integration-tests/.tmp staging directory")
    if args.original:
        report["originalExecution"] = run_reviewed(pack / "original-manifest.json", upstream,
                                                   framework, client, pack / "original-results",
                                                   args.stage_parent, args.timeout)
        write_json(pack / "comparison.json", report)
    execution = run_reviewed(pack / "adapted-manifest.json", owned, framework, client,
                             pack / "adapted-results", args.stage_parent, args.timeout)
    report["adaptedExecution"] = execution
    summary = execution["summary"]
    records = summary.get("cases", [])
    original_records = report.get("originalExecution", {}).get("summary", {}).get("cases", [])
    report.update(executed=len(records), counts=dict(Counter(row["status"] for row in records)),
                  status="EXECUTED", comparisons=[dict(
                      path=path, original=[item for item in history if item["record"]["path"] == path],
                      originalRerun=[row for row in original_records if row["path"] == path],
                      adapted=[row for row in records if row["path"] == path])
                      for path in (PREFIX + value for value in CASES.values())])
    report["executionStatistics"] = dict(
        adapted=dict(requested=7, executed=len(records), counts=report["counts"]),
        originalRerun=dict(requested=7 if args.original else 0, executed=len(original_records),
                           counts=dict(Counter(row["status"] for row in original_records))),
        totalCasesExecuted=len(records) + len(original_records))
    preflight(original, upstream, framework, client)
    preflight(adapted, owned, framework, client)
    if runner_hashes != {name: file_sha256(Path(__file__).with_name(name)) for name in runner_hashes}:
        raise ValueError("Compatibility runner sources changed during execution")
    report["originalInputsUnchanged"] = True
    report["adaptedInputsUnchanged"] = True
    report["complete"] = (len(records) == 7 and summary.get("requested") == 7
                          and summary.get("inputsUnchanged") is True
                          and summary.get("ownedTemporaryDirectoryRemoved") is True)
    write_json(pack / "comparison.json", report)
    return int(not report["complete"] or execution["returncode"] != 0
               or any(row["status"] != "PASS" for row in records))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
