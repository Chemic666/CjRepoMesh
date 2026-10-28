#!/usr/bin/env python3
"""Check executable results after incremental macro and CHIR body changes.

macro-transitive reproduces a stale macro expansion when a linked function body
changes while the macro package's cjo stays identical. macro-body and chir-body
are controls, not claims of additional pre-fix failures. All fixture mutations
are confined to owned copies; original official assertions remain untouched.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from incremental_cutoff import change_source, run_owned, sha, snapshot


CASES = ("macro-body", "macro-transitive", "chir-body")
FIXTURES = {
    "macro": Path("testsuites/LLT/Tools/cjpm/CJNATIVE/build/incremental/incremental_39"),
    "chir": Path("testsuites/LLT/Tools/cjpm/CJNATIVE/common_platform/basic"),
}


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    check(text.count(old) == 1, f"Expected one mutation anchor in {path.name}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def checked_run(command: list[str], *, project: Path, env: dict, log: Path,
                timeout: int, record: dict, label: str) -> dict:
    result = run_owned(command, project=project, env=env, log=log, timeout=timeout)
    record["commands"].append(dict(label=label, **result))
    check(not result["timedOut"], f"{label} timed out")
    check(result["returncode"] == 0, f"{label} failed with exit {result['returncode']}")
    return result


def check_output(log: Path, expected: str, forbidden: str | None = None, *, exact_line: bool = False) -> None:
    output = log.read_text(encoding="utf-8", errors="replace")
    observed = output.splitlines() if exact_line else output
    check(expected in observed, f"Expected actual executable output {expected!r}")
    if forbidden is not None:
        check(forbidden not in observed, f"Executable retained stale output {forbidden!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--stage-parent", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux-only owned process-group regression; use the existing Linux SDK")
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds per command")
    client = args.cjpm.resolve()
    compiler = shutil.which("cjc")
    if not client.is_file() or compiler is None:
        parser.error("Require an existing product cjpm and the installed cjc in PATH")
    if not args.stage_parent.is_dir():
        parser.error("--stage-parent must be an existing owned scratch parent")
    upstream = args.upstream.resolve()
    selected = list(dict.fromkeys(args.case or CASES))
    originals = {}
    for name in selected:
        fixture = upstream / FIXTURES["chir" if name == "chir-body" else "macro"]
        if not (fixture / "cjpm.toml").is_file():
            parser.error(f"Missing original fixture: {fixture}")
        originals[name] = dict(path=str(fixture), files=snapshot(fixture))
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    stage = Path(tempfile.mkdtemp(prefix="incremental-implementation-inputs-",
                                 dir=args.stage_parent.resolve()))
    summary = dict(clientSha256=sha(client), compilerSha256=sha(Path(compiler)),
                   runnerSha256=sha(Path(__file__)), helperSha256=sha(Path(__file__).with_name("incremental_cutoff.py")),
                   selectedCases=selected, requested=len(selected), total=0, passed=0,
                   ownedStage=str(stage), ownedStageRetained=True,
                   originalAssertionsUnchanged=True, fixtureInputs=originals, cases=[])
    write_json(results / "summary.json", summary)
    for name in selected:
        owned = stage / name
        project = owned / "project"
        evidence = results / name
        evidence.mkdir()
        record = dict(name=name, passed=False, outputCorrect=False, commands=[], errors=[], ownedProject=str(project),
                      role="stale-expansion-regression" if name == "macro-transitive" else "control")
        try:
            fixture = Path(originals[name]["path"])
            shutil.copytree(fixture, project)
            for path in project.rglob("*"):
                if path.is_file() and path.suffix in (".cj", ".toml"):
                    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            if name == "macro-transitive":
                replace_once(project / "src/a/a.cj",
                             'public func aaa(): Unit {\n    println("aaa")\n}',
                             'public func aaa(): Int64 {\n    return 3\n}')
                replace_once(project / "src/b/b.cj", "return input",
                             "if (aaa() == 3) { return input }\n    return input[0..1]")
                record["syntheticPreparation"] = "a returns 3; b macro branches on aaa(), before warm"
            elif name == "chir-body":
                replace_once(project / "cmp/cjpm.toml", 'output-type = "dynamic"',
                             'output-type = "static"')
                record["syntheticPreparation"] = "cmp output-type dynamic -> static before warm"
            home = owned / "home"
            home.mkdir()
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
            env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                       GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
            command = [str(client), "build", "-i", "-V"]
            if name == "chir-body":
                command += ["--no-feature-deduce", "--enable-features=user.cmp.arch.little"]
            write_json(evidence / "sources-before.json", snapshot(project))
            checked_run(command, project=project, env=env, log=evidence / "warm.log",
                        timeout=args.timeout, record=record, label="warm-build")
            app = project / "target/release/bin/main"
            check(app.is_file(), "Warm build did not produce the expected executable")
            checked_run([str(app)], project=project, env=env, log=evidence / "run-before.log",
                        timeout=min(args.timeout, 30), record=record, label="warm-executable")
            check_output(evidence / "run-before.log", "call from boo:" if name == "chir-body" else "a = 3",
                         exact_line=name != "chir-body")
            before = snapshot(project / "target")
            write_json(evidence / "artifacts-before.json", before)
            shutil.copytree(project / "target", evidence / "target-before")
            if name == "macro-transitive":
                body = project / "src/a/a.cj"
                replace_once(body, "return 3", "return 1")
            elif name == "macro-body":
                body = project / "src/b/b.cj"
                replace_once(body, "return input", "return input[0..1]")
            else:
                body = project / "cmp/common/c.cj"
                replace_once(body, "call from boo:", "call from NEW:")
            change_source(body)
            # Save only source/config inputs, not the warmed target twice.
            write_json(evidence / "sources-after.json",
                       {key: value for key, value in snapshot(project).items()
                        if not key.startswith("target/")})
            checked_run(command, project=project, env=env, log=evidence / "second.log",
                        timeout=args.timeout, record=record, label="second-build")
            after = snapshot(project / "target")
            write_json(evidence / "artifacts-after.json", after)
            # Execute the actual produced program before checking artifact
            # invariants, so even invariant failures retain its real output.
            checked_run([str(app)], project=project, env=env, log=evidence / "run-after.log",
                        timeout=min(args.timeout, 30), record=record, label="second-executable")
            if name.startswith("macro-"):
                cjo = "release/default/default.b.cjo"
                macro = "release/default/lib-macro_default.b.so"
                check(cjo in before and cjo in after and macro in before and macro in after,
                      "Expected real macro cjo and shared library artifacts")
                record["macroCjoUnchanged"] = before[cjo] == after[cjo]
                record["macroCjoBytesUnchanged"] = before[cjo]["sha256"] == after[cjo]["sha256"]
                record["macroLibraryBytesChanged"] = before[macro]["sha256"] != after[macro]["sha256"]
                check(record["macroLibraryBytesChanged"], "Macro implementation library did not change")
                if name == "macro-transitive":
                    check(record["macroCjoUnchanged"],
                          "Transitive regression requires macro cjo bytes, size and mtime to stay unchanged")
                check_output(evidence / "run-after.log", "a = 1", "a = 3", exact_line=True)
            else:
                cjo = "release/cmp/common/nonproduct/cmp.cjo"
                chir = "release/cmp/common/nonproduct/cmp.chir"
                check(cjo in before and cjo in after and chir in before and chir in after,
                      "Expected common cjo and CHIR artifacts")
                record["commonCjoBytesChanged"] = before[cjo]["sha256"] != after[cjo]["sha256"]
                record["commonChirBytesChanged"] = before[chir]["sha256"] != after[chir]["sha256"]
                check(record["commonChirBytesChanged"], "CHIR implementation bytes did not change")
                check_output(evidence / "run-after.log", "call from NEW:", "call from boo:")
            record["outputCorrect"] = True
            record["passed"] = True
        except Exception as error:
            record["errors"].append(f"{type(error).__name__}: {error}")
        record["fixtureUnchanged"] = originals[name]["files"] == snapshot(Path(originals[name]["path"]))
        if not record["fixtureUnchanged"]:
            record["passed"] = False
            record["errors"].append("Original upstream fixture changed")
        summary["cases"].append(record)
        summary["total"] = len(summary["cases"])
        summary["passed"] = sum(item["passed"] for item in summary["cases"])
        summary["fixtureUnchanged"] = all(item["fixtureUnchanged"] for item in summary["cases"])
        write_json(results / "summary.json", summary)
        print(("PASS " if record["passed"] else "FAIL ") + name, flush=True)
    return int(summary["passed"] != summary["total"] or not summary["fixtureUnchanged"])


if __name__ == "__main__":
    raise SystemExit(main())
