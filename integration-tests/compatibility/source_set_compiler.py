#!/usr/bin/env python3
"""Regression for capability-based legacy/named CHIR compiler arguments.

The supported-compiler fixture records actual cjpm arguments, then translates
only the new named CHIR argument for the existing SDK. It is not a newer SDK
acceptance claim. All projects, compiler wrappers and profiles are synthetic.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

CASE_TIMEOUT_SECONDS = 120


def run_owned(command, *, cwd, env):
    """Capture one isolated process tree, including failure output."""
    process = subprocess.Popen(command, cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=CASE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
    finally:
        # This fresh group belongs only to this case. Also remove descendants
        # after a normally exiting parent, before deleting the owned stage.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), timed_out


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--cjc", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--stage-parent", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=("legacy-zero-error", "named-supported",
                        "probe-failed", "probe-ambiguous", "named-concurrent", "ordinary-no-probe"))
    args = parser.parse_args()
    if sys.platform != "linux":
        raise ValueError("Linux-only compiler regression")
    client, compiler = args.cjpm.resolve(), args.cjc.resolve()
    fixture_files = {p.relative_to(args.fixture).as_posix(): sha(p)
                     for p in args.fixture.rglob("*") if p.is_file()}
    if not fixture_files or not (args.fixture / "always_enabled_check.info").is_file():
        raise ValueError("Require the separately reviewed official always_enabled_check fixture")
    args.results.mkdir(parents=True, exist_ok=False)
    records = []
    with tempfile.TemporaryDirectory(prefix="chir-capability-", dir=args.stage_parent) as raw:
        stage = Path(raw)
        for mode in args.case or ("legacy-zero-error", "named-supported", "probe-failed", "probe-ambiguous", "named-concurrent", "ordinary-no-probe"):
            owned = stage / mode
            owned.mkdir()
            project = owned / "project"
            if mode == "ordinary-no-probe":
                (project / "src").mkdir(parents=True)
                (project / "cjpm.toml").write_text('[package]\ncjc-version="1.0.0"\nname="ordinary"\nversion="1.0.0"\noutput-type="executable"\n')
                (project / "src/main.cj").write_text('package ordinary\nmain(): Int64 { println("ordinary-ok"); return 0 }\n')
            else:
                shutil.copytree(args.fixture, project)
                for path in project.rglob("*"):
                    if path.is_file() and path.suffix in (".toml", ".cj"):
                        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
                if mode == "named-concurrent":
                    # Two independent source-set libraries reach the lazy
                    # capability getter from parallel ReadCompilerOptions tasks.
                    other = project / "other"
                    shutil.copytree(project / "cmp", other)
                    for path in other.rglob("*"):
                        if path.is_file() and path.suffix in (".toml", ".cj"):
                            path.write_text(path.read_text().replace("cmp", "other"))
                    config = project / "cjpm.toml"
                    text = config.read_text()
                    assert text.count('  cmp = { path = "./cmp" }') == 1
                    assert text.count('[ "user.cmp.arch.little" ]') == 1
                    text = text.replace('  cmp = { path = "./cmp" }',
                                        '  cmp = { path = "./cmp" }\n  other = { path = "./other" }')
                    text = text.replace('[ "user.cmp.arch.little" ]',
                                        '[ "user.cmp.arch.little", "user.other.arch.little" ]')
                    text += '\n[profile.build]\nincremental = false\n'
                    config.write_text(text)
            wrapper = owned / "bin/cjc"
            wrapper.parent.mkdir()
            calls = owned / "calls.jsonl"
            wrapper.write_text('#!/usr/bin/python3\nimport json, os, sys, time\n'
                f'mode={mode!r}\ncompiler={str(compiler)!r}\ncalls={str(calls)!r}\n'
                'args=sys.argv[1:]\n'
                'with open(calls, "a") as stream: stream.write(json.dumps(args)+"\\n")\n'
                'if "--help" in args and any(a.startswith("--common-part-chir=") for a in args):\n'
                '    if mode == "legacy-zero-error":\n'
                '        print("error: invalid option: \'--common-part-chir\'.", file=sys.stderr); sys.exit(0)\n'
                '    if mode in ("named-supported", "named-concurrent"):\n'
                '        if mode == "named-concurrent": time.sleep(1)\n'
                '        print("Usage:\\n      cjc [option] file..."); sys.exit(0)\n'
                '    if mode == "probe-failed":\n'
                '        print("synthetic probe failed", file=sys.stderr); sys.exit(7)\n'
                '    print("synthetic unrelated output"); sys.exit(0)\n'
                'if mode in ("named-supported", "named-concurrent"):\n'
                '    args=[a.split("=",1)[1] if a.startswith("--common-part-chir=") else a for a in args]\n'
                'os.execv(compiler, [compiler]+args)\n')
            wrapper.chmod(0o755)
            home = owned / "home"
            home.mkdir()
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("CJREPO_", "CJREPOMESH_")) and k != "CJPM_CONFIG"}
            env.update(HOME=str(home), USERPROFILE=str(home),
                       PATH=f"{wrapper.parent}:{client.parent}:{env.get('PATH', '')}")
            errors = []
            timed_out = False
            try:
                result, timed_out = run_owned([str(client), "run"], cwd=project, env=env)
            except OSError as error:
                result = subprocess.CompletedProcess([str(client), "run"], -1, "", str(error))
                errors.append(f"Failed to execute client: {error}")
            if timed_out:
                errors.append(f"Client process tree exceeded {CASE_TIMEOUT_SECONDS}s timeout")
            output = result.stdout + result.stderr
            (args.results / (mode + ".log")).write_text(output)
            try:
                invocations = [json.loads(line) for line in calls.read_text().splitlines()]
                if not all(isinstance(call, list) and all(isinstance(a, str) for a in call)
                           for call in invocations):
                    raise ValueError("Expected argument arrays")
            except (OSError, ValueError) as error:
                invocations = []
                errors.append(f"Failed to read compiler calls: {error}")
            probes = [call for call in invocations if "--help" in call and any(a.startswith("--common-part-chir=") for a in call)]
            compiles = [call for call in invocations if "--help" not in call]
            named = any(a.startswith("--common-part-chir=") for call in compiles for a in call)
            bare = any(a.endswith(".chir") and not a.startswith("--") for call in compiles for a in call)
            libraries = sorted({name for name in ("cmp", "other")
                                if any('/' + name + '/' in a for call in compiles for a in call)})
            if mode in ("legacy-zero-error", "named-supported", "named-concurrent"):
                passed = (result.returncode == 0 and "Platform B 'foo'" in output and len(probes) == 1
                          and (named if mode.startswith("named-") else bare and not named)
                          and (libraries == ["cmp", "other"] if mode == "named-concurrent" else True))
            elif mode == "ordinary-no-probe":
                passed = result.returncode == 0 and "ordinary-ok" in output and not probes
            else:
                passed = result.returncode != 0 and len(probes) == 1 and "failed to probe cjc --common-part-chir support" in output
            passed = passed and not errors
            records.append(dict(name=mode, passed=passed, returncode=result.returncode,
                                timedOut=timed_out, error="; ".join(errors),
                                probes=len(probes), namedChirArgument=named, bareChirArgument=bare,
                                compiledLibraries=libraries,
                                logSha256=sha(args.results / (mode + ".log"))))
            (args.results / (mode + "-calls.json")).write_text(json.dumps(invocations, indent=2))
            print(("PASS " if passed else "FAIL ") + mode, flush=True)
    assert fixture_files == {p.relative_to(args.fixture).as_posix(): sha(p)
                             for p in args.fixture.rglob("*") if p.is_file()}
    summary = dict(clientSha256=sha(client), compilerSha256=sha(compiler),
                   runnerSha256=sha(Path(__file__)), fixtureFiles=fixture_files,
                   total=len(records), passed=sum(r["passed"] for r in records), cases=records,
                   fixtureUnchanged=True, ownedStageRemoved=not stage.exists())
    (args.results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return int(summary["passed"] != summary["total"])


if __name__ == "__main__":
    raise SystemExit(main())
