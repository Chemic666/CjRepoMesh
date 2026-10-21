#!/usr/bin/env python3
"""Exercise a cold filesystem backup and restore using real cjpm archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    ManagedProcesses, TestFailure, assert_contains, assert_equal, assert_ports_available,
    http_request, platform_executable, publish_frame, remove_within, run_command,
    wait_for_health, wait_for_ports_closed,
)


def manifest(directory: Path) -> dict[str, str]:
    """Hash the complete file set, including indexes and organization directories."""
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise TestFailure("Backup drill fixtures must not contain symbolic links")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path,
                        default=platform_executable(TESTS.parent / "server/target/release/bin/main"))
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--port", type=int, default=39630)
    parser.add_argument("--evidence-dir", type=Path, help="new directory for logs and hash manifests")
    args = parser.parse_args()
    server, cjpm = args.server.resolve(), args.cjpm.resolve()
    if not server.is_file() or not cjpm.is_file():
        parser.error("build the server and enhanced cjpm first")
    assert_ports_available((args.port,))
    parent = TESTS / ".tmp"
    root = parent / f"cold-backup-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    logs = root if args.evidence_dir is None else args.evidence_dir.resolve()
    if logs != root:
        logs.mkdir(parents=True, exist_ok=False)
    source, backup, restored = (root / name for name in ("source", "backup", "restored"))
    offline = root / "source-offline"
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    isolated_home = root / "home"
    isolated_home.mkdir()
    environment.update(HOME=str(isolated_home), USERPROFILE=str(isolated_home))
    environment["CJREPOMESH_BACKUP_READ_TOKEN"] = "backup-read-fixture"
    base = f"http://127.0.0.1:{args.port}"
    payloads: list[dict] = []
    completed = 0
    success = False

    def passed(message: str) -> None:
        nonlocal completed
        completed += 1
        print("PASS " + message, flush=True)

    def copy_fixture(relative: str, destination: str) -> Path:
        target = root / destination
        target.mkdir()
        for name in ("cjpm.toml", "README.md", "src"):
            original = TESTS / relative / name
            if original.is_dir():
                shutil.copytree(original, target / name)
            elif original.is_file():
                shutil.copyfile(original, target / name)
        (target / "cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "{base}"\n'
            'token-env = "CJREPOMESH_BACKUP_READ_TOKEN"\n', encoding="utf-8")
        return target

    def bundle(relative: str, label: str, version: str | None = None) -> dict:
        package = copy_fixture(relative, label)
        if version is not None:
            config = package / "cjpm.toml"
            text = config.read_text(encoding="utf-8")
            assert_equal(text.count('version = "2.0.0"'), 1, label="fixture version replacement")
            config.write_text(text.replace('version = "2.0.0"', f'version = "{version}"'), encoding="utf-8")
        result = run_command((cjpm, "bundle"), cwd=package, env=environment, timeout=60)
        (logs / f"bundle-{label}.log").write_text(result.output, encoding="utf-8")
        metadata = (package / "target/meta-data.json").read_bytes()
        value = json.loads(metadata)
        candidates = list((package / "target").glob("*.cjp"))
        assert_equal(len(candidates), 1, label="one real bundled archive")
        artifact = candidates[0].read_bytes()
        assert_equal(hashlib.sha256(artifact).hexdigest(), value["index"]["sha256sum"],
                     label="bundle archive SHA-256")
        return dict(name=value["name"], version=value["version"], organization=value["organization"],
                    artifact=artifact, frame=publish_frame(metadata, artifact))

    def query(package: dict) -> str:
        return "" if not package["organization"] else "?organization=" + package["organization"]

    def publish(package: dict, expected: int = 200) -> None:
        response = http_request("POST", base + "/pkg/" + package["name"] + query(package),
                                headers={"Authorization": "backup-publish-fixture"}, body=package["frame"])
        assert_equal(response.status, expected, label="restored publish status")

    def read_all(packages: list[dict]) -> None:
        for package in packages:
            name = package["name"]
            suffix = query(package)
            index_path = f"/index/{name[:2]}/{name[2:4]}/{name}{suffix}"
            artifact_path = f"/pkg/{name}/{package['version']}{suffix}"
            for path in (index_path, artifact_path):
                assert_equal(http_request("GET", base + path).status, 401, label="private read remains protected")
            index = http_request("GET", base + index_path, headers={"Authorization": "backup-read-fixture"})
            assert_equal(index.status, 200, label="restored index status")
            rows = [json.loads(line) for line in index.body.splitlines() if line]
            selected = [row for row in rows if row["version"] == package["version"]]
            assert_equal(len(selected), 1, label="restored index has one selected version")
            assert_equal(selected[0]["organization"], package["organization"], label="restored organization")
            result = http_request("GET", base + artifact_path, headers={"Authorization": "backup-read-fixture"})
            assert_equal(result.status, 200, label="restored artifact status")
            assert_equal(result.body, package["artifact"], label="restored archive bytes")
            assert_equal(hashlib.sha256(result.body).hexdigest(), selected[0]["sha256sum"],
                         label="restored archive matches index")

    try:
        payloads = [bundle("multirepo/packages/meshdep-v1-low", "default-v1"),
                    bundle("multirepo/packages/meshdep-v2-low", "default-v2"),
                    bundle("hosted-server/org-package", "organization-v1")]
        new_version = bundle("multirepo/packages/meshdep-v2-low", "default-v3", "3.0.0")
        with ManagedProcesses() as processes:
            def start(storage: Path, label: str):
                env = dict(environment, CJREPO_ADDRESS="127.0.0.1", CJREPO_PORT=str(args.port),
                           CJREPO_STORAGE=str(storage), CJREPO_PUBLISH_TOKEN="backup-publish-fixture",
                           CJREPO_READ_TOKEN="backup-read-fixture")
                process = processes.start((server,), cwd=server.parent, env=env,
                                          output_path=logs / f"server-{label}.log")
                wait_for_health(args.port)
                return process

            original = start(source, "source")
            for package in payloads:
                publish(package)
            read_all(payloads)
            passed("real archives published with multiple versions, organization-scoped and private reads")
            processes.stop(original)
            wait_for_ports_closed((args.port,))
            original_manifest = manifest(source)
            assert_equal(len(original_manifest), 5, label="two complete indexes and three real artifacts")
            shutil.copytree(source, backup)
            assert_equal(manifest(backup), original_manifest, label="cold backup exact file set and hashes")
            (logs / "backup-manifest.json").write_text(json.dumps(original_manifest, indent=2), encoding="utf-8")
            passed("stopped source copied with byte-identical complete storage")

            for label, change in (("corrupt", "artifact"), ("incomplete", "index")):
                damaged = root / label
                shutil.copytree(backup, damaged)
                key = next(name for name in original_manifest if name.startswith(change + ("s/" if change == "artifact" else "/")))
                target = damaged / key
                if change == "artifact":
                    target.write_bytes(target.read_bytes() + b"tamper")
                else:
                    target.unlink()
                assert_equal(manifest(damaged) == original_manifest, False, label="damaged backup rejected by manifest check")
                passed(f"manifest verification detects {label} backup before starting a restored instance")

            # The source is test-owned and stopped. Keep it as evidence while
            # making its old path unavailable to the restored process.
            assert root.resolve() in source.resolve().parents
            assert root.resolve() in offline.resolve().parents
            source.rename(offline)
            assert_equal(source.exists(), False, label="original storage path is unavailable")
            shutil.copytree(backup, restored)
            assert_equal(manifest(restored), original_manifest, label="restored file set and hashes")
            instance = start(restored, "restored")
            read_all(payloads)
            passed("fresh-directory restore serves verified default and named organization archives")

            for label, relative, marker in (("default", "hosted-server/app", "low-2.0.0"),
                                             ("organization", "hosted-server/org-app", "meshcorp-1.0.0")):
                consumer = copy_fixture(relative, "consumer-" + label)
                result = run_command((cjpm, "run"), cwd=consumer, env=environment, timeout=90)
                (logs / f"consumer-{label}.log").write_text(result.output, encoding="utf-8")
                assert_contains(result.output, marker)
                passed(f"fresh-cache {label} consumer builds and runs from restored real archive")

            for package in payloads:
                publish(package, 409)
            publish(new_version)
            read_all(payloads + [new_version])
            passed("restored instance rejects duplicate versions and accepts a new real version")
            processes.stop(instance)
            wait_for_ports_closed((args.port,))
            instance = start(restored, "restored-restart")
            read_all(payloads + [new_version])
            passed("restored data and subsequent publication survive another restart")
            assert_equal(manifest(backup), original_manifest, label="backup remains immutable")
            assert_equal(manifest(offline), original_manifest, label="original source remains preserved")
            passed("backup and offline original remain unchanged by restored writes")
        wait_for_ports_closed((args.port,))
        success = True
    except (TestFailure, OSError, ValueError) as error:
        print(f"FAIL cold backup drill: {error}", flush=True)
    finally:
        if success:
            remove_within(root, (parent,))
            try:
                parent.rmdir()
            except OSError:
                pass
        else:
            print(f"Failure storage retained: {root}", flush=True)
    print(f"Cold backup drill: {completed}/10 checkpoints passed; success={success}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
