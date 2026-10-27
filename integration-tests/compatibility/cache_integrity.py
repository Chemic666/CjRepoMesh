#!/usr/bin/env python3
"""Exercise extracted-cache admission with real cjpm archives and offline builds.

The receipt detects accidental/local cache changes; it is not protection against
an attacker who can change both the cache and its receipt with the same account.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (TestFailure, assert_contains, assert_equal,  # noqa: E402
                        assert_ports_available, run_command, sha256, wait_for_ports_closed)
from showcase.run import AuditedHTTP  # noqa: E402

CASES = ("intact", "modified", "truncated", "deleted", "added", "directory-added",
         "directory-deleted", "file-link", "directory-link", "root-link",
         "receipt-missing", "receipt-truncated", "receipt-index-mismatch", "receipt-link",
         "source-file", "occupied-temp", "large-file-tail-modified", "receipt-oversized", "dangling-link")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--port", type=int, default=39765)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=CASES)
    args = parser.parse_args()
    client = args.cjpm.resolve()
    if not client.is_file():
        parser.error("--cjpm must be an existing real cjpm binary")
    assert_ports_available((args.port,))
    suffix = uuid.uuid4().hex
    root = TESTS / ".tmp" / ("cache-integrity-" + suffix)
    root.mkdir(parents=True)
    report = (args.evidence_dir or TESTS / ".tmp" / ("cache-integrity-report-" + suffix)).resolve()
    report.mkdir(parents=True, exist_ok=False)
    home = root / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    env.update(HOME=str(home), USERPROFILE=str(home), CJREPOMESH_INTEGRITY_TOKEN="upstream-read-fixture")
    url = f"http://127.0.0.1:{args.port}"
    stages, actor = [], None

    def fixture(relative: str, label: str, cache: Path) -> Path:
        destination = root / label
        destination.mkdir()
        original = TESTS / relative
        for name in ("cjpm.toml", "README.md", "src"):
            source = original / name
            if source.is_dir():
                shutil.copytree(source, destination / name)
            elif source.is_file():
                shutil.copyfile(source, destination / name)
        destination.joinpath("cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "{cache.as_posix()}"\n'
            f'[repository.home]\nregistry = "{url}"\ntoken-env = "CJREPOMESH_INTEGRITY_TOKEN"\n',
            encoding="utf-8")
        return destination

    def command(label: str, app: Path, *arguments: str, success=True):
        try:
            result = run_command((client, *arguments), cwd=app, env=env,
                                 expect_success=success, timeout=90)
        except TestFailure as error:
            report.joinpath(label + ".log").write_text(str(error), encoding="utf-8")
            raise
        report.joinpath(label + ".log").write_text(result.output, encoding="utf-8")
        return result

    def snapshot(path: Path):
        # Preserve link identity without following its target.
        return {item.relative_to(path).as_posix():
                ("link", os.readlink(item)) if item.is_symlink() else
                ("directory", "") if item.is_dir() else ("file", sha256(item))
                for item in path.rglob("*")}

    try:
        warmed = root / "warmed-cache"
        package = fixture("multirepo/packages/meshdep-v1-high", "package", warmed)
        # An empty directory lets the test detect directory deletions independently
        # of source-file hashing. A real CJP is still produced by cjpm itself.
        package.joinpath("src/empty-integrity-fixture").mkdir()
        package.joinpath("large-integrity-fixture.txt").write_bytes(b"x" * (3 * 65536 + 17))
        command("bundle", package, "bundle")
        metadata = json.loads(package.joinpath("target/meta-data.json").read_text(encoding="utf-8"))
        archives = list(package.joinpath("target").glob("*.cjp"))
        assert_equal(len(archives), 1, label="one real bundled CJP")
        artifact = archives[0].read_bytes()
        assert_equal(sha256(archives[0]), metadata["index"]["sha256sum"], label="archive SHA")
        actor = AuditedHTTP(args.port, packages=(dict(name=metadata["name"], version=metadata["version"],
            organization=metadata["organization"], index=metadata["index"], artifact=artifact),))
        app = fixture("multirepo/app-pinned", "warm-consumer", warmed)
        command("warm", app, "run")
        actor.close()
        wait_for_ports_closed((args.port,))
        for case in args.cases:
            try:
                cache = root / ("cache-" + case)
                shutil.copytree(warmed, cache, symlinks=True)
                consumer = fixture("multirepo/app-pinned", "consumer-" + case, cache)
                source = cache / "repository/source/default/meshdep-1.0.0"
                original = source / "src/meshdep.cj"
                receipt = source.parent / (source.name + ".cjpm-integrity")
                if case == "modified":
                    original.write_text(original.read_text().replace("high-1.0.0", "changed-cache"))
                elif case == "truncated":
                    original.write_bytes(b"")
                elif case == "large-file-tail-modified":
                    large = source / "large-integrity-fixture.txt"
                    with large.open("r+b") as stream:
                        stream.seek(-1, os.SEEK_END)
                        stream.write(b"y")
                elif case == "deleted":
                    original.unlink()
                elif case == "added":
                    source.joinpath("untracked.txt").write_text("unknown user file")
                elif case == "directory-added":
                    source.joinpath("unknown-empty-directory").mkdir()
                elif case == "directory-deleted":
                    # CJP bundling may omit empty source directories. Select an
                    # actual archived directory, preserving every file elsewhere.
                    directories = sorted((item for item in source.rglob("*") if item.is_dir()),
                                         key=lambda item: len(item.parts), reverse=True)
                    assert directories, "real package must contain a directory"
                    shutil.rmtree(directories[0])
                elif case in ("file-link", "directory-link", "root-link", "receipt-link"):
                    outside = root / ("outside-" + case)
                    if case == "file-link":
                        outside.write_bytes(original.read_bytes())
                        original.unlink()
                        original.symlink_to(outside)
                    elif case == "directory-link":
                        shutil.copytree(source / "src", outside)
                        shutil.rmtree(source / "src")
                        source.joinpath("src").symlink_to(outside, target_is_directory=True)
                    elif case == "root-link":
                        shutil.copytree(source, outside)
                        shutil.rmtree(source)
                        source.symlink_to(outside, target_is_directory=True)
                    else:
                        outside.write_bytes(receipt.read_bytes())
                        receipt.unlink()
                        receipt.symlink_to(outside)
                elif case == "receipt-missing":
                    receipt.unlink(missing_ok=True)
                elif case == "receipt-truncated":
                    receipt.write_bytes(b"")
                elif case == "receipt-oversized":
                    receipt.write_bytes(b"x" * (1024 * 1024))
                elif case == "dangling-link":
                    original.unlink()
                    original.symlink_to(root / "missing-link-target")
                elif case == "receipt-index-mismatch":
                    index = cache / "repository/index/default/me/sh/meshdep"
                    row = json.loads(index.read_text())
                    row["sha256sum"] = "0" * 64
                    index.write_text(json.dumps(row) + "\n")
                elif case == "source-file":
                    shutil.rmtree(source)
                    source.write_text("unknown user file")
                elif case == "occupied-temp":
                    shutil.rmtree(source)
                    receipt.unlink(missing_ok=True)
                    temporary = source.parent / ("temp-" + source.name)
                    temporary.mkdir()
                    temporary.joinpath("unknown.txt").write_text("unknown user file")
                before = snapshot(cache)
                result = command(case, consumer, "run" if case == "intact" else "build",
                                 success=case == "intact")
                if case == "intact":
                    assert_contains(result.output, "high-1.0.0")
                else:
                    assert_contains(result.output, "repository cache integrity")
                assert_equal(snapshot(cache), before, label="unknown or damaged cache preserved")
                stages.append(dict(name=case, status="PASS"))
            except (TestFailure, OSError, ValueError, AssertionError) as error:
                stages.append(dict(name=case, status="FAIL", error=str(error)))
            print(f"{stages[-1]['status']} {case}", flush=True)
    except (TestFailure, OSError, ValueError, AssertionError) as error:
        stages.append(dict(name="setup", status="FAIL", error=str(error)))
    finally:
        if actor is not None:
            actor.close()
        success = len(stages) == len(args.cases) and all(item["status"] == "PASS" for item in stages)
        report.joinpath("summary.json").write_text(json.dumps(dict(success=success, stages=stages,
            inputs=dict(client_sha256=sha256(client), runner_sha256=sha256(Path(__file__))),
            fixture_root=str(root), limits=["Local integrity receipt is writable by the same account.",
            "Fixtures and evidence retained for inspection; no real user cache is changed."]), indent=2), encoding="utf-8")
        print(f"Cache integrity: success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
