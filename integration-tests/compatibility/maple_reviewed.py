#!/usr/bin/env python3
"""Execute an explicit, reviewed, content-frozen Maple allowlist on Linux.

There is deliberately no suite discovery or automatic approval. Review every
selected command, dependency, helper and configuration before making a manifest.
Without --execute this only verifies inputs and runs no Maple commands.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from maple_smoke import file_sha256, wait_for_port_release


def snapshot_tree(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unreviewed symlink in fixture: {path}")
        if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts:
            files[path.relative_to(root).as_posix()] = file_sha256(path)
    return files


def relative_file(root: Path, relative: str, suffix: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or path.suffix != suffix:
        raise ValueError(f"Expected relative {suffix} path inside snapshot")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"Missing or escaping relative {suffix} path")
    return resolved


def preflight(manifest: dict, upstream: Path, framework: Path, client: Path) -> list[Path]:
    if manifest.get("schema") != 1 or not manifest.get("cases"):
        raise ValueError("Require schema 1 and a nonempty explicit reviewed allowlist")
    if file_sha256(client) != manifest.get("clientSha256"):
        raise ValueError("Client binary changed")
    if snapshot_tree(framework) != manifest.get("frameworkFiles"):
        raise ValueError("Maple framework changed")
    config = relative_file(upstream, manifest["config"], ".cfg")
    if file_sha256(config) != manifest.get("configSha256"):
        raise ValueError("Maple configuration changed")
    selected = []
    for row in manifest["cases"]:
        case = relative_file(upstream, row["path"], ".info")
        if not row.get("reason") or snapshot_tree(case.parent) != row.get("files"):
            raise ValueError(f"Unreviewed fixture changed: {row['path']}")
        expected_dependencies = {}
        for line in case.read_text(encoding="utf-8").splitlines():
            if "DEPENDENCE:" not in line:
                continue
            match = re.fullmatch(r"// DEPENDENCE: ([^\s,;]+)\s*", line)
            if not match:
                raise ValueError("Unsupported dependency directive requires review")
            dependency = (case.parent / match[1].replace("%n", case.stem)).resolve()
            if not dependency.is_relative_to(upstream.resolve()) or not dependency.is_dir():
                raise ValueError("Missing or escaping dependency directory")
            if dependency != case.parent:
                expected_dependencies[dependency.relative_to(upstream.resolve()).as_posix()] = snapshot_tree(dependency)
        if expected_dependencies != row.get("dependencies", {}):
            raise ValueError(f"Unreviewed dependency changed: {row['path']}")
        if case in selected:
            raise ValueError("Duplicate case in explicit allowlist")
        selected.append(case)
    return selected


def result_status(returncode: int, output: str) -> str:
    summaries = re.findall(r"Total: 1, ([^\r\n]*)", output)
    if not summaries:
        return "FAIL"
    counts = {name: int(count) for name, count in re.findall(r"([A-Z_]+): (\d+)", summaries[-1])}
    if returncode == 0 and counts.get("PASS") == 1 and not any(
            count for name, count in counts.items() if name != "PASS"):
        return "PASS"
    if returncode == 0 and counts.get("NOT_RUN") == 1:
        return "SKIP"
    return "FAIL"


def execute_one(case: Path, row: dict, client: Path, framework: Path, config: Path,
                stage: Path, results: Path, ordinal: int, timeout: int) -> dict:
    wait_for_port_release()
    owned = stage / f"case-{ordinal:04d}"
    owned.mkdir()
    upstream = case
    for _ in PurePosixPath(row["path"]).parts:
        upstream = upstream.parent
    inputs = owned / "inputs"
    fixture = inputs / PurePosixPath(row["path"]).parent
    fixture.parent.mkdir(parents=True)
    shutil.copytree(case.parent, fixture)
    for relative in row.get("dependencies", {}):
        shutil.copytree(upstream / relative, inputs / relative, dirs_exist_ok=True)
    normalizations = []
    for path in inputs.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".toml", ".cj", ".py"}:
            raw = path.read_bytes()
            if b"\r\n" in raw:
                path.write_bytes(raw.replace(b"\r\n", b"\n"))
                normalizations.append(path.relative_to(inputs).as_posix())
    home = owned / "home"
    home.mkdir()
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(("CJREPO_", "CJREPOMESH_")) or key in {
                "CJPM_CONFIG", "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT"}:
            env.pop(key)
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               PATH=f"{home / '.cjpm' / 'bin'}:{client.parent}:{env.get('PATH', '')}")
    output_dir = results / f"case-{ordinal:04d}"
    output_dir.mkdir()
    command = [sys.executable, str(framework / "main.py"), f"--test_cfg={config}",
               f"--temp_dir={owned / 'temp'}", f"--log_dir={output_dir / 'maple-log'}",
               "--fail_exit", "-p", "FAIL", str(fixture / case.name)]
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=owned, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
    finally:
        # Kill only descendants in the fresh process group owned by this run.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    log = output_dir / "runner.log"
    log.write_text(output, encoding="utf-8")
    wait_for_port_release()
    return dict(path=row["path"], status="FAIL" if timed_out else result_status(process.returncode, output),
                returncode=process.returncode, timedOut=timed_out,
                seconds=round(time.monotonic() - started, 2),
                log=str(log.relative_to(results)), logSha256=file_sha256(log),
                lineEndingNormalization=normalizations,
                reason=row["reason"], summary=output.strip().splitlines()[-8:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--stage-parent", type=Path,
                        help="Existing owned Linux scratch directory; defaults to integration-tests/.tmp")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = preflight(manifest, args.upstream, args.framework, args.client)
    if not args.execute:
        print(f"PRECHECK ONLY: {len(cases)} frozen reviewed cases; no commands executed")
        return 0
    if sys.platform != "linux" or args.results is None or args.timeout < 1:
        raise ValueError("Execution requires Linux, a new results directory, and positive timeout")
    args.results.mkdir(parents=True, exist_ok=False)
    temp_parent = args.stage_parent or Path(__file__).resolve().parent.parent / ".tmp"
    if args.stage_parent is None:
        temp_parent.mkdir(exist_ok=True)
    if not temp_parent.is_dir() or temp_parent.is_symlink():
        raise ValueError("Stage parent must be an existing owned directory without symlinks")
    records = []
    begin = time.monotonic()
    runner_sha = file_sha256(Path(__file__))
    shutil.copy2(Path(__file__), args.results / "runner-source.py")
    # Official scan counts also inspect verbose absolute paths. A hyphen before
    # a random leading 'g' would manufacture a spurious '-g' option match.
    with tempfile.TemporaryDirectory(prefix="maple_reviewed_", dir=temp_parent) as temporary:
        stage = Path(temporary)
        staged_framework = stage / "framework"
        shutil.copytree(args.framework, staged_framework,
                        ignore=shutil.ignore_patterns(".git", "__pycache__"))
        if snapshot_tree(staged_framework) != manifest["frameworkFiles"]:
            raise ValueError("Staged Maple framework changed")
        config = stage / "test.cfg"
        shutil.copy2(args.upstream / manifest["config"], config)
        for ordinal, (case, row) in enumerate(zip(cases, manifest["cases"]), 1):
            record = execute_one(case, row, args.client.resolve(), staged_framework,
                                 config, stage, args.results, ordinal, args.timeout)
            records.append(record)
            summary = dict(clientSha256=file_sha256(args.client), manifestSha256=file_sha256(args.manifest),
                           runnerSha256=runner_sha,
                           requested=len(cases), executed=len(records),
                           counts=dict(Counter(item["status"] for item in records)),
                           seconds=round(time.monotonic() - begin, 2), cases=records)
            (args.results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(f"{ordinal}/{len(cases)} {record['status']} {row['path']}", flush=True)
    preflight(manifest, args.upstream, args.framework, args.client)
    summary["inputsUnchanged"] = True
    summary["ownedTemporaryDirectoryRemoved"] = not stage.exists()
    (args.results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return int(any(item["status"] != "PASS" for item in records))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
