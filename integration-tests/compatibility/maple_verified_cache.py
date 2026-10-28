#!/usr/bin/env python3
"""Replay four legacy-cache business assertions with separately prepared caches.

These are prepared compatibility checks, not original Maple results. Original
fixtures stay untouched. Only real bundle/download operations create receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (TestFailure, assert_contains, assert_equal,  # noqa: E402
                        assert_ports_available, run_command, sha256, wait_for_ports_closed)
from showcase.run import AuditedHTTP  # noqa: E402

SINGLE = "check/coverage/central_dependency_cached"
TRANSITIVE = "check/coverage/central_dependency_transitive"
INSTALL = "install/coverage/repository_cached"
UPDATE = "update/coverage/central_dependency_cached_update"
CASES = (SINGLE, TRANSITIVE, INSTALL, UPDATE)


def snapshot(root: Path) -> dict[str, str]:
    """Hash regular files without accepting links in either input or cache."""
    if root.is_symlink() or not root.is_dir():
        raise TestFailure(f"Require an existing regular directory: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise TestFailure(f"Unexpected link or special file: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def archive_files(archive: Path, package: str) -> dict[str, str]:
    """Inspect the owned CJP without extracting it or manufacturing a receipt."""
    result = {}
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or not name.parts
                    or name.parts[0] != package or not (member.isdir() or member.isfile())):
                raise TestFailure(f"Unexpected bundled archive member: {member.name}")
            if member.isfile():
                relative = PurePosixPath(*name.parts[1:]).as_posix()
                if relative in result or relative == ".":
                    raise TestFailure("Duplicate or invalid bundled archive file")
                digest = hashlib.sha256()
                with stream.extractfile(member) as source:
                    for block in iter(lambda: source.read(65536), b""):
                        digest.update(block)
                result[relative] = digest.hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--suite-root", required=True, type=Path,
                        help="original upstream testsuites/LLT/Tools/cjpm/CJNATIVE")
    parser.add_argument("--port", type=int, default=39769)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=CASES)
    args = parser.parse_args()
    client, suite = args.cjpm.resolve(), args.suite_root.resolve()
    if not client.is_file() or not 1 <= args.port <= 65535:
        parser.error("require an existing cjpm binary and a valid loopback port")
    input_paths = dict(client_sha256=client, runner_sha256=Path(__file__),
                       harness_sha256=TESTS / "lib/harness.py",
                       owned_registry_sha256=TESTS / "showcase/run.py")
    frozen_inputs = {name: sha256(path) for name, path in input_paths.items()}
    if len(args.cases) != len(set(args.cases)):
        parser.error("--cases must be unique")
    # The update case borrows the single-dependency fixture through DEPENDENCE.
    required = set(args.cases) | ({SINGLE} if UPDATE in args.cases else set())
    frozen = {}
    for relative in sorted(required):
        folder = suite / relative
        info = folder / (folder.name + ".info")
        if not info.is_file():
            parser.error(f"missing original fixture: {info}")
        frozen[relative] = snapshot(folder)
    assert_ports_available((args.port,))
    suffix = uuid.uuid4().hex
    root = TESTS / ".tmp" / ("maple-verified-cache-" + suffix)
    report = (args.evidence_dir or TESTS / ".tmp" / ("maple-verified-cache-report-" + suffix)).resolve()
    if report.is_relative_to(suite):
        parser.error("--evidence-dir must stay outside the original suite")
    report.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key not in
           {"CJPM_CONFIG", "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT"}}
    env.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               CJREPOMESH_PREPARED_TOKEN="upstream-read-fixture")
    url = f"http://127.0.0.1:{args.port}"
    stages, artifacts, bundles = [], [], {}

    def command(label: str, cwd: Path, *arguments: str):
        try:
            result = run_command((client, *arguments), cwd=cwd, env=env, timeout=120)
        except TestFailure as error:
            report.joinpath(label + ".log").write_text(str(error), encoding="utf-8")
            raise
        report.joinpath(label + ".log").write_text(result.output, encoding="utf-8")
        return result

    def configure(folder: Path, cache: Path) -> None:
        folder.joinpath("cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "{cache.as_posix()}"\n'
            f'[repository.home]\nregistry = "{url}"\ntoken-env = "CJREPOMESH_PREPARED_TOKEN"\n',
            encoding="utf-8")

    def consumer(original: Path, folder: Path, cache: Path) -> None:
        folder.mkdir()
        for name in ("cjpm.toml", "src"):
            source = original / name
            if source.is_dir():
                shutil.copytree(source, folder / name)
            elif source.is_file():
                shutil.copyfile(source, folder / name)
        configure(folder, cache)

    def bundle(original: Path, label: str) -> dict:
        if original in bundles:
            return bundles[original]
        folder = root / ("package-" + label)
        consumer(original, folder, folder / "cache")
        config = folder / "cjpm.toml"
        text = config.read_text(encoding="utf-8")
        text, count = re.subn(r"(?m)^\[package\][ \t]*$",
                             '[package]\ndescription = "Prepared legacy-cache compatibility fixture"', text, count=1)
        assert_equal(count, 1, label="original package table")
        config.write_text(text, encoding="utf-8")
        folder.joinpath("README.md").write_text(
            "Prepared compatibility fixture; not an original Maple cache.\n", encoding="utf-8")
        prepared_files = {"cjpm.toml": sha256(config), "README.md": sha256(folder / "README.md")}
        prepared_files.update({"src/" + name: checksum for name, checksum in snapshot(folder / "src").items()})
        command("bundle-" + label, folder, "bundle", "--skip-test", "--skip-lint")
        metadata_file = folder / "target/meta-data.json"
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        archives = list((folder / "target").glob("*.cjp"))
        assert_equal(len(archives), 1, label="one real bundled CJP")
        archive = archives[0]
        checksum = sha256(archive)
        assert_equal(checksum, metadata["index"]["sha256sum"], label="real archive SHA")
        files = archive_files(archive, metadata["name"] + "-" + metadata["version"])
        for name, expected in prepared_files.items():
            assert_equal(files.get(name), expected, label="bundled prepared source " + name)
        package = dict(name=metadata["name"], organization=metadata["organization"], version=metadata["version"],
                       index=metadata["index"], artifact=archive.read_bytes(), files=files)
        bundles[original] = package
        artifacts.append(dict(original=original.relative_to(suite).as_posix(), archive_sha256=checksum,
                              metadata_sha256=sha256(metadata_file), prepared_files=prepared_files,
                              archive_files=files, preparation=["add package.description", "add README.md",
                              "normalize package TOML newlines when inserting description",
                              "bundle --skip-test --skip-lint (real build still required)"]))
        return package

    def run_case(relative: str) -> dict:
        label = relative.rsplit("/", 1)[-1]
        original = suite / (SINGLE if relative == UPDATE else relative)
        case_root = root / label
        case_root.mkdir()
        cache, app = case_root / "cache", case_root / "consumer"
        consumer(original, app, cache)
        packages = []
        actor = AuditedHTTP(args.port, packages=packages)
        row = dict(name=relative, classification="prepared-compatibility", status="FAIL",
                   original_fixture=relative, borrowed_fixture=SINGLE if relative == UPDATE else None,
                   changes=["omit unverified preseeded cache", "use a new isolated cache.path",
                            "replace unreachable registry by an owned loopback fixture and test token",
                            "populate index/archive/receipt through verified product download"],
                   assertions=[], requests=[])
        try:
            names = ("leaf-1.0.0", "top-1.0.0") if relative == TRANSITIVE else ("cached-1.0.0",)
            for name in names:
                package = bundle(original / "cache/repository/source/default" / name, label + "-" + name)
                packages.append(package)
            if relative == TRANSITIVE:
                index = original / "cache/repository/index/default/to/p/top"
                yanked, = (json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()
                           if line.startswith("{") and json.loads(line)["version"] == "2.0.0")
                assert_equal(yanked["yanked"], True, label="original top 2.0.0 remains yanked")
                packages.append(dict(name="top", organization="", version="2.0.0", index=yanked, artifact=b""))
                row["changes"].append("retain original unused yanked top@2.0.0 index record")
            if relative == INSTALL:
                command(label + "-warm", app, "install", "cached-1.0.0", "--verbose",
                        "--root", str(case_root / "warm-install"))
            else:
                command(label + "-warm", app, "check")
            selected = packages[:len(names)]
            for package in selected:
                name = package["name"] + "-" + package["version"]
                source = cache / "repository/source/default" / name
                assert_equal(snapshot(source), package["files"], label="verified extraction " + name)
                assert (source.parent / (name + ".cjpm-integrity")).is_file(), "real download must create receipt"
                assert_equal(any(path.split("?")[0] == "/pkg/" + package["name"] + "/" + package["version"]
                                 for path in actor.requests), True, label="real artifact GET " + name)
            actor.close()
            wait_for_ports_closed((args.port,))
            before = snapshot(cache / "repository/source")
            if relative == INSTALL:
                installed = case_root / "offline-install"
                result = command(label + "-offline", app, "install", "cached-1.0.0", "--verbose", "--root", str(installed))
                executable = installed / "bin" / ("cached.exe" if os.name == "nt" else "cached")
                run = run_command((executable,), cwd=app, env=env, timeout=10)
                report.joinpath(label + "-installed-program.log").write_text(run.output, encoding="utf-8")
                assert_contains(run.output, "cached")
                row["changes"].append("isolate installation destinations with --root and run offline-installed binary")
            else:
                result = command(label + "-offline", app, "update" if relative == UPDATE else "check")
            info = suite / relative / (label + ".info")
            assertions = [line.split("// ASSERT: scan ", 1)[1].strip()
                          for line in info.read_text(encoding="utf-8").splitlines() if line.startswith("// ASSERT: scan ")]
            assert assertions, "original business assertions are required"
            for expected in assertions:
                assert_contains(result.output, expected, label="original business assertion")
            assert_equal(snapshot(cache / "repository/source"), before, label="offline source and receipt immutable")
            assert_equal(actor.errors, [], label="owned fixture server errors")
            row.update(status="PASS", assertions=assertions, offline_source_sha256=before)
        except (TestFailure, OSError, ValueError, AssertionError, tarfile.TarError) as error:
            row["error"] = str(error)
        finally:
            actor.close()
            wait_for_ports_closed((args.port,))
            row["requests"] = actor.requests
        return row

    try:
        for relative in args.cases:
            try:
                row = run_case(relative)
            except (TestFailure, OSError, ValueError, AssertionError) as error:
                row = dict(name=relative, classification="prepared-compatibility", status="FAIL", error=str(error))
            stages.append(row)
            print(f"{row['status']} prepared-compatibility {relative}", flush=True)
    finally:
        original_error = ""
        try:
            unchanged = all(snapshot(suite / relative) == files for relative, files in frozen.items())
        except (TestFailure, OSError) as error:
            unchanged, original_error = False, str(error)
        final_inputs = {name: sha256(path) for name, path in input_paths.items()}
        inputs_unchanged = frozen_inputs == final_inputs
        success = (unchanged and inputs_unchanged and len(stages) == len(args.cases)
                   and all(row["status"] == "PASS" for row in stages))
        summary = dict(classification="prepared-compatibility", success=success, original_maple_results_changed=False,
                       originals_unchanged=unchanged, original_verification_error=original_error,
                       original_files=frozen, stages=stages, artifacts=artifacts,
                       inputs=frozen_inputs, final_inputs=final_inputs, inputs_unchanged=inputs_unchanged,
                       fixture_root=str(root), limits=["Not original Maple results; never aggregate into raw suite totals.",
                       "Original fixtures lack verified archives/index hashes/receipts and are not rerun here.",
                       "Prepared package metadata adds description/README required by bundle.",
                       "No Python-generated receipt or production admission-policy change.",
                       "All synthetic fixtures and evidence retained; real user caches remain untouched."])
        report.joinpath("summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Prepared cache compatibility: success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
