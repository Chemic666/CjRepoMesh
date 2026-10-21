#!/usr/bin/env python3
"""Verify cjpm run reports real application/build failures to CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    client = args.cjpm.resolve(strict=True)
    evidence = args.evidence_dir.absolute()
    evidence.mkdir(parents=True, exist_ok=False)
    temporary = Path(__file__).resolve().parent.parent / ".tmp"
    temporary.mkdir(exist_ok=True)
    work = temporary / ("run-status-" + uuid.uuid4().hex)
    app = work / "application with spaces"
    (app / "src").mkdir(parents=True)
    home = work / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    env.update(HOME=str(home), USERPROFILE=str(home))
    (app / "cjpm.toml").write_text(
        '[package]\nname = "runstatus"\nversion = "1.0.0"\n'
        'cjc-version = "1.0.0"\noutput-type = "executable"\n', encoding="utf-8")
    source = app / "src/main.cj"
    source.write_text('''package runstatus
import std.env.getCommandLine
main(): Int64 {
    let args = getCommandLine()[1..]
    println("RUN_STATUS_EXECUTED")
    for (arg in args) { println("ARG[${arg}]") }
    if (!args.isEmpty() && args[0] == "fail") {
        eprintln("RUN_STATUS_APPLICATION_FAILURE")
        return 7
    }
    return 0
}
''', encoding="utf-8")
    cases = []
    started = time.monotonic()

    def check(name: str, arguments: list[str], exit_code: int, *, markers: tuple[str, ...] = (),
              absent: tuple[str, ...] = ()) -> None:
        result = subprocess.run([str(client), *arguments], cwd=app, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=120, check=False)
        log = evidence / (name + ".log")
        log.write_text(result.stdout, encoding="utf-8")
        passed = (result.returncode == exit_code and
                  all(marker in result.stdout for marker in markers) and
                  all(marker not in result.stdout for marker in absent))
        cases.append(dict(name=name, passed=passed, exitCode=result.returncode,
                          expectedExit=exit_code, logSha256=sha256(log)))
        print(f"{'PASS' if passed else 'FAIL'} {name}: exit {result.returncode}, expected {exit_code}", flush=True)

    error = ""
    try:
        check("successful-build-and-run", ["run"], 0,
              markers=("RUN_STATUS_EXECUTED", "cjpm run finished"))
        # Verify the fixture's actual exit independently of cjpm's status.
        binary = app / "target/release/bin/main"
        result = subprocess.run([str(binary), "fail"], cwd=app, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 7 and "RUN_STATUS_APPLICATION_FAILURE" in result.stderr
        (evidence / "application-exit.json").write_text(json.dumps(dict(exitCode=result.returncode, binarySha256=sha256(binary))) + "\n")
        failure = ("RUN_STATUS_EXECUTED", "RUN_STATUS_APPLICATION_FAILURE", "Error: cjpm run failed")
        check("skip-build-runtime-failure", ["run", "--skip-build", "--", "fail"], 1,
              markers=failure, absent=("cjpm run finished",))
        check("normal-runtime-failure", ["run", "--", "fail"], 1,
              markers=failure, absent=("cjpm run finished",))
        check("legacy-run-args-failure", ["run", "--skip-build", "--run-args", "fail"], 1,
              markers=failure, absent=("cjpm run finished",))
        check("separator-overrides-legacy", ["run", "--skip-build", "--run-args", "ok", "--", "fail"], 1,
              markers=failure, absent=("ARG[ok]", "cjpm run finished"))
        check("success-argument-boundaries", ["run", "--skip-build", "--", "two words", "--help"], 0,
              markers=("ARG[two words]", "ARG[--help]", "cjpm run finished"))
        check("missing-product", ["run", "--skip-build", "--name", "not-present"], 1,
              markers=("Error: cjpm run failed",), absent=("RUN_STATUS_EXECUTED", "cjpm run finished"))
        source.write_text('package runstatus\nmain(): Int64 { let invalid: Int64 = "type error"; return invalid }\n', encoding="utf-8")
        check("compile-failure-does-not-run-old-app", ["run", "--", "fail"], 1,
              markers=("Error:",), absent=("RUN_STATUS_EXECUTED", "cjpm run finished"))
    except (OSError, AssertionError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
    passed = sum(case["passed"] for case in cases)
    success = not error and passed == len(cases) == 8
    summary = dict(success=success, passed=passed, total=8, cases=cases, error=error,
                   clientSha256=sha256(client), runnerSha256=sha256(Path(__file__)),
                   seconds=round(time.monotonic() - started, 2),
                   contract="Application nonzero status maps to cjpm CLI failure 1; success remains 0. Not exact child status propagation.")
    (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if success:
        assert work.resolve().parent == temporary.resolve()
        shutil.rmtree(work)
    print(f"Run exit status: {passed}/8; success={success}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
