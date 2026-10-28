#!/usr/bin/env python3
"""Exercise cjo projection cutoff and necessary invalidation with real cjpm/cjc.

Copies the original incremental_37 fixture into a fresh owned directory for each
case. This checks product behavior, not the official fixture's stronger only-a
assertion: unchanged cjo may skip static consumers while changed archive bytes
still require the final link. Logs and owned stages are retained for audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


CASES = ("touch-only", "changed-api", "missing-static", "changed-source", "syntax-error",
         "missing-output", "changed-options")
PACKAGES = {"default", "default.a", "default.b", "default.c", "default.d"}
COMPILE = re.compile(r"^Compiling package `([^`]+)`: .+$", re.MULTILINE)
FIXTURE = Path("testsuites/LLT/Tools/cjpm/CJNATIVE/build/incremental/incremental_37")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot(root: Path) -> dict:
    return {path.relative_to(root).as_posix():
            {"sha256": sha(path), "bytes": path.stat().st_size,
             "mtimeNs": path.stat().st_mtime_ns}
            for path in sorted(root.rglob("*")) if path.is_file()}


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_owned(command, *, project: Path, env: dict, log: Path, timeout: int) -> dict:
    """Bound a fresh Linux process group and retain original combined output."""
    started = time.monotonic()
    timed_out = False
    # A file avoids a completed parent leaving inherited output pipes open.
    with log.open("wb") as stream:
        process = subprocess.Popen(command, cwd=project, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # This group was created solely for this command. Clean descendants
            # on both timeout and ordinary parent exit, before the next case.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
    output = log.read_text(encoding="utf-8", errors="replace")
    return {"command": command, "returncode": process.returncode,
            "timedOut": timed_out, "seconds": round(time.monotonic() - started, 2),
            "compiledPackages": COMPILE.findall(output), "log": str(log),
            "logSha256": sha(log)}


def change_source(path: Path, addition: str | None = None) -> None:
    previous = path.stat().st_mtime_ns
    if addition is not None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(addition)
    # Guarantee a distinct timestamp without a timing-dependent sleep.
    os.utime(path, ns=(path.stat().st_atime_ns, max(time.time_ns(), previous + 1_000_000_000)))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def install_missing_output_wrapper(owned: Path, project: Path, compiler: Path) -> tuple[Path, Path, Path]:
    """Forward the real compiler unchanged until the owned marker is enabled."""
    wrapper = owned / "bin/cjc"
    wrapper.parent.mkdir()
    marker = owned / "suppress-a-output"
    calls = owned / "wrapper-calls.jsonl"
    wrapper.write_text(
        "#!/usr/bin/python3\nimport json, os, sys\nfrom pathlib import Path\n"
        f"real={str(compiler)!r}\nmarker=Path({str(marker)!r})\n"
        f"calls=Path({str(calls)!r})\na_source=Path({str(project / 'src/a')!r}).resolve()\n"
        "args=sys.argv[1:]\npackage=None\n"
        "for index, arg in enumerate(args):\n"
        "    if arg == '-p' and index + 1 < len(args): package=args[index+1]\n"
        "    elif arg.startswith('-p='): package=arg[3:]\n"
        "suppressed=(marker.is_file() and package is not None\n"
        "            and Path(package).resolve() == a_source\n"
        "            and '--scan-dependency' not in args\n"
        "            and not any(a in ('--help', '-h', '-v', '--version') for a in args))\n"
        "entry={'args':args,'suppressed':suppressed}\n"
        "with calls.open('a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(entry)+'\\n')\n"
        "if suppressed: sys.exit(0)\n"
        "os.execv(real, [real]+args)\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper, marker, calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--stage-parent", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux-only process-group regression; use the existing Linux SDK")
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds per command")
    client = args.cjpm.resolve()
    fixture = args.upstream.resolve() / FIXTURE
    compiler_path = shutil.which("cjc")
    if not client.is_file() or compiler_path is None:
        parser.error("Require an existing product cjpm and the installed cjc in PATH")
    if not (fixture / "incremental_37.info").is_file():
        parser.error("--upstream must contain the original incremental_37 fixture")
    if not args.stage_parent.is_dir():
        parser.error("--stage-parent must be an existing owned scratch parent")
    original = snapshot(fixture)
    args.results = args.results.resolve()
    args.results.mkdir(parents=True, exist_ok=False)
    stage = Path(tempfile.mkdtemp(prefix="incremental-cutoff-", dir=args.stage_parent.resolve()))
    summary = {"clientSha256": sha(client), "compilerSha256": sha(Path(compiler_path)),
               "runnerSha256": sha(Path(__file__)), "fixture": str(fixture),
               "fixtureFiles": original, "ownedStage": str(stage), "ownedStageRetained": True,
               "officialAssertionsUnchanged": True, "cases": []}
    write_json(args.results / "summary.json", summary)
    selected = list(dict.fromkeys(args.case or CASES))
    for name in selected:
        record = {"name": name, "passed": False, "attempts": [], "errors": []}
        owned = stage / name
        project = owned / "project"
        case_results = args.results / name
        case_results.mkdir()
        try:
            shutil.copytree(fixture, project)
            for path in project.rglob("*"):
                if path.is_file() and path.suffix in (".cj", ".toml"):
                    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            home = owned / "home"
            home.mkdir()
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
            env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                       GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
            wrapper = marker = calls = None
            if name == "missing-output":
                # Install before warming and retain exactly the same wrapper
                # bytes/PATH for both builds. Keep CANGJIE_HOME on the real SDK.
                wrapper, marker, calls = install_missing_output_wrapper(
                    owned, project, Path(compiler_path).resolve())
                env["PATH"] = str(wrapper.parent) + os.pathsep + env.get("PATH", "")
                record["compilerWrapperSha256"] = sha(wrapper)
                record["cangjieHome"] = env.get("CANGJIE_HOME")
            if name == "changed-options":
                config = project / "cjpm.toml"
                text = config.read_text(encoding="utf-8")
                old = 'compile-option = "--incremental-compile --experimental"'
                check(text.count(old) == 1, "Expected one original fixture compile-option")
                config.write_text(text.replace(old, old[:-1] + ' -O0"'), encoding="utf-8")
                record["warmConfigSha256"] = sha(config)
            command = [str(client), "build", "-i", "-V"]
            warm = run_owned(command, project=project, env=env,
                             log=case_results / "warm.log", timeout=args.timeout)
            record["attempts"].append(warm)
            check(not warm["timedOut"] and warm["returncode"] == 0, "Warm build failed or timed out")
            check(set(warm["compiledPackages"]) == PACKAGES and len(warm["compiledPackages"]) == 5,
                  "Warm build did not invoke all five expected package compiles")
            if name == "missing-output":
                warm_calls = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
                check(warm_calls and not any(call["suppressed"] for call in warm_calls),
                      "Warm compiler wrapper failed to forward every call")
                record["warmWrapperCallCount"] = len(warm_calls)
            before = snapshot(project / "target")
            write_json(case_results / "artifacts-before.json", before)
            # The second real compiler call can overwrite an archive. Preserve
            # warm bytes as well as hashes so a failure can be investigated.
            shutil.copytree(project / "target", case_results / "target-before")
            a_source = project / "src/a/a.cj"
            b_source = project / "src/b/b.cj"
            a_archive = project / "target/release/default/libdefault.a.a"
            b_archive = project / "target/release/default/libdefault.b.a"
            if name == "touch-only":
                change_source(a_source)
            elif name == "changed-api":
                change_source(a_source, "\npublic func cutoffAddedApi(): Int64 { return 314159 }\n")
            elif name == "missing-static":
                check(b_archive.is_file(), "Warm build did not produce b's static archive")
                b_archive.unlink()
            elif name == "changed-source":
                change_source(b_source, "\npublic func cutoffBAddedApi(): Int64 { return 271828 }\n")
            elif name == "syntax-error":
                change_source(a_source, "\npublic func cutoffBroken(\n")
            elif name == "missing-output":
                check(a_archive.is_file(), "Warm build did not produce a's static archive")
                a_archive.unlink()
                marker.write_text("owned synthetic missing-output case\n", encoding="utf-8")
                change_source(a_source)
            else:
                text = config.read_text(encoding="utf-8")
                check(text.count(' -O0"') == 1, "Expected the warmed -O0 compile-option")
                config.write_text(text.replace(' -O0"', ' -O1"'), encoding="utf-8")
                record["secondConfigSha256"] = sha(config)
            write_json(case_results / "sources-after-mutation.json", snapshot(project / "src"))
            second = run_owned(command, project=project, env=env,
                               log=case_results / "second.log", timeout=args.timeout)
            record["attempts"].append(second)
            after = snapshot(project / "target")
            write_json(case_results / "artifacts-after.json", after)
            compiles = second["compiledPackages"]
            check(not second["timedOut"], "Second build timed out")
            check(set(compiles) <= PACKAGES, "Unexpected package invocation in second build")
            if name == "missing-output":
                invocations = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
                write_json(case_results / "compiler-wrapper-calls.json", invocations)
                record["wrapperCallsSha256"] = sha(case_results / "compiler-wrapper-calls.json")
                record["suppressedCompileCalls"] = sum(call["suppressed"] for call in invocations)
                check(sha(wrapper) == record["compilerWrapperSha256"], "Compiler wrapper changed between builds")
                check(record["suppressedCompileCalls"] >= 1, "Missing-output injection did not intercept a compile")
                check(not a_archive.exists(), "Missing-output injection unexpectedly produced a's archive")
                cjo = "release/default/default.a.cjo"
                check(cjo in before and cjo in after and before[cjo] == after[cjo],
                      "Missing-output injection did not preserve the valid warmed cjo")
                check(second["returncode"] != 0,
                      "Compiler produced no required archive but cjpm returned cached success")
            elif name == "syntax-error":
                check(second["returncode"] != 0, "Invalid source unexpectedly built successfully")
                check(not (set(compiles) & (PACKAGES - {"default.a"})),
                      "A failed dependency triggered downstream compilation")
            else:
                check(second["returncode"] == 0, "Second build failed")
                if name == "touch-only":
                    check(compiles.count("default.a") == 1, "Touched a was not compiled exactly once")
                    check(set(compiles) <= {"default.a", "default"} and compiles.count("default") <= 1,
                          "Unchanged cjo caused redundant static-consumer compilation: " + repr(compiles))
                else:
                    check("default.b" in compiles, "Required invalidation did not rebuild b: " + repr(compiles))
                    check(b_archive.is_file(), "Rebuilt b archive is missing")
                    if name == "changed-api":
                        cjo = "release/default/default.a.cjo"
                        check(cjo in before and cjo in after and before[cjo]["sha256"] != after[cjo]["sha256"],
                              "API mutation did not change a's real cjo bytes")
            record["passed"] = True
        except Exception as error:
            record["errors"].append(f"{type(error).__name__}: {error}")
        record["ownedProject"] = str(project)
        summary["cases"].append(record)
        summary["total"] = len(summary["cases"])
        summary["passed"] = sum(item["passed"] for item in summary["cases"])
        summary["fixtureUnchanged"] = original == snapshot(fixture)
        write_json(args.results / "summary.json", summary)
        print(("PASS " if record["passed"] else "FAIL ") + name, flush=True)
    return int(not summary["fixtureUnchanged"] or summary["passed"] != summary["total"])


if __name__ == "__main__":
    raise SystemExit(main())
