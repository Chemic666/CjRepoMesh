#!/usr/bin/env python3
"""Check repository installation preserves and revalidates its immutable source cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (TestFailure, assert_contains, assert_equal,  # noqa: E402
                        assert_ports_available, run_command, sha256, wait_for_ports_closed)
from showcase.run import AuditedHTTP  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", required=True, type=Path)
    parser.add_argument("--port", type=int, default=39766)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    client = args.cjpm.resolve()
    if not client.is_file():
        parser.error("an existing real cjpm binary is required")
    assert_ports_available((args.port,))
    suffix = uuid.uuid4().hex
    root = TESTS / ".tmp" / ("cache-install-integrity-" + suffix)
    root.mkdir(parents=True)
    report = (args.evidence_dir or TESTS / ".tmp" / ("cache-install-report-" + suffix)).resolve()
    report.mkdir(parents=True, exist_ok=False)
    home, cache, package, consumer = (root / name for name in ("home", "cache", "package", "consumer"))
    for path in (home, package, consumer):
        path.mkdir()
    package.joinpath("src").mkdir()
    package.joinpath("cjpm.toml").write_text(
        '[package]\ncjc-version = "1.0.0"\nname = "meshinstaller"\nversion = "1.0.0"\n'
        'output-type = "executable"\ndescription = "isolated cache install fixture"\n', encoding="utf-8")
    package.joinpath("README.md").write_text("Isolated synthetic installer.\n", encoding="utf-8")
    package.joinpath("src/main.cj").write_text(
        'package meshinstaller\nmain(): Int64 {\n    println("installed-cache-fixture")\n    return 0\n}\n',
        encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    env.update(HOME=str(home), USERPROFILE=str(home), CJREPOMESH_INSTALL_TOKEN="upstream-read-fixture")
    url = f"http://127.0.0.1:{args.port}"
    configuration = f'[repository.cache]\npath = "{cache.as_posix()}"\n[repository.home]\nregistry = "{url}"\ntoken-env = "CJREPOMESH_INSTALL_TOKEN"\n'
    for path in (package, consumer):
        path.joinpath("cangjie-repo.toml").write_text(configuration, encoding="utf-8")
    stages, actor = [], None

    def command(label, cwd, arguments, *, success=True):
        try:
            result = run_command((client, *arguments), cwd=cwd, env=env,
                                 expect_success=success, timeout=90)
        except TestFailure as error:
            report.joinpath(label + ".log").write_text(str(error), encoding="utf-8")
            raise
        report.joinpath(label + ".log").write_text(result.output, encoding="utf-8")
        return result

    def source_snapshot(path):
        return {item.relative_to(path).as_posix(): sha256(item)
                for item in path.rglob("*") if item.is_file()}

    def passed(name):
        stages.append(dict(name=name, status="PASS"))
        print("PASS " + name, flush=True)

    try:
        expected = {name: sha256(package / name) for name in ("cjpm.toml", "README.md", "src/main.cj")}
        command("bundle", package, ("bundle",))
        metadata = json.loads(package.joinpath("target/meta-data.json").read_text(encoding="utf-8"))
        archive, = package.joinpath("target").glob("*.cjp")
        artifact = archive.read_bytes()
        assert_equal(hashlib.sha256(artifact).hexdigest(), metadata["index"]["sha256sum"], label="real CJP SHA")
        actor = AuditedHTTP(args.port, packages=(dict(name=metadata["name"], version=metadata["version"],
            organization=metadata["organization"], index=metadata["index"], artifact=artifact),))
        installed = root / "installed"
        install_args = ("install", "meshinstaller-1.0.0", "--root", str(installed))
        command("install-online", consumer, install_args)
        source = cache / "repository/source/default/meshinstaller-1.0.0"
        assert_equal(source_snapshot(source), expected, label="installation preserves original archive source")
        receipt = source.parent / (source.name + ".cjpm-integrity")
        assert receipt.is_file(), "new extraction must have an integrity receipt"
        preserved_receipt = sha256(receipt)
        passed("online-install-keeps-source-immutable")
        actor.close()
        wait_for_ports_closed((args.port,))
        command("install-offline-again", consumer, install_args)
        assert_equal(source_snapshot(source), expected, label="repeat offline install preserves source")
        assert_equal(sha256(receipt), preserved_receipt, label="receipt is not refreshed after install")
        executable = installed / "bin" / ("meshinstaller.exe" if os.name == "nt" else "meshinstaller")
        run = run_command((executable,), cwd=consumer, env=env, timeout=10)
        assert_contains(run.output, "installed-cache-fixture")
        work = cache / "repository/install-work"
        assert_equal(list(work.iterdir()), [], label="owned install work directories cleaned")
        passed("offline-repeat-install-runs-and-cleans-work-copy")
        source.joinpath("src/main.cj").write_text(
            source.joinpath("src/main.cj").read_text().replace("installed-cache-fixture", "tampered-cache-fixture"))
        changed = source_snapshot(source)
        result = command("install-tampered-offline", consumer, install_args, success=False)
        assert_contains(result.output, "repository cache integrity")
        assert_equal(source_snapshot(source), changed, label="modified source preserved on rejection")
        assert_equal(sha256(receipt), preserved_receipt, label="modified source does not get a new receipt")
        passed("offline-install-rejects-modified-source")
    except (TestFailure, OSError, ValueError, AssertionError) as error:
        stages.append(dict(name="install-integrity", status="FAIL", error=str(error)))
        print("FAIL " + str(error), flush=True)
    finally:
        if actor is not None:
            actor.close()
        success = len(stages) == 3 and all(stage["status"] == "PASS" for stage in stages)
        report.joinpath("summary.json").write_text(json.dumps(dict(success=success, stages=stages,
            inputs=dict(client_sha256=sha256(client), runner_sha256=sha256(Path(__file__))), fixture_root=str(root)),
            indent=2), encoding="utf-8")
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
