#!/usr/bin/env python3
"""Cold-backup an isolated Docker volume and restore real cjpm packages to a new volume."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import sys
import tarfile
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    CommandResult, TestFailure, assert_contains, assert_equal, assert_ports_available, http_request,
    publish_frame, remove_within, run_command, wait_for_health, wait_for_ports_closed,
)


def archive_manifest(path: Path) -> dict[str, str]:
    """Validate the owned archive before extraction and hash its full file set."""
    files = {}
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isdir() or member.isfile()):
                raise TestFailure("Unexpected path or file type in test backup")
            if member.isfile():
                key = name.as_posix()
                if key in files or not key.startswith(("index/", "artifacts/")):
                    raise TestFailure("Unexpected or duplicate file in test backup")
                with archive.extractfile(member) as stream:
                    files[key] = hashlib.sha256(stream.read()).hexdigest()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="existing local CjRepo image; never pulled")
    clients = parser.add_mutually_exclusive_group(required=True)
    clients.add_argument("--cjpm", type=Path, help="existing native host client")
    clients.add_argument("--client-bundle", type=Path, help="complete Linux client delivery directory")
    parser.add_argument("--client-sdk", type=Path, help="existing Linux SDK for container jobs, read-only")
    parser.add_argument("--client-native", type=Path, help="existing ar/ld, Python and libraries, read-only")
    parser.add_argument("--port", type=int, default=39640)
    parser.add_argument("--evidence-dir", type=Path, help="new directory retaining logs and backup archive")
    args = parser.parse_args()
    if not args.client_bundle and (args.client_sdk or args.client_native):
        parser.error("client-sdk/client-native require client-bundle")
    cjpm = args.cjpm.resolve() if args.cjpm else None
    if cjpm and not cjpm.is_file():
        parser.error("build the enhanced cjpm first")
    client_manifest = None
    client_verifier = None
    if args.client_bundle:
        if not args.client_sdk or not (args.client_sdk / "envsetup.sh").is_file():
            parser.error("client-bundle requires an existing client-sdk")
        if args.client_native and not (args.client_native / "bin/ar").is_file():
            parser.error("client-native requires existing ar/ld and matching runtime tools")
        client_verifier = runpy.run_path(str(TESTS.parent / "deployment/client/verify.py"))["verify_bundle"]
        try:
            client_manifest = client_verifier(args.client_bundle)
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error("invalid client bundle: " + str(error))
    assert_ports_available((args.port,))
    parent = TESTS / ".tmp"
    root = parent / ("docker-backup-" + uuid.uuid4().hex)
    logs = root if args.evidence_dir is None else args.evidence_dir.resolve()
    if logs != root:
        logs.mkdir(parents=True, exist_ok=False)
    root.mkdir(parents=True)
    scope = "cjrepomesh-backup-" + uuid.uuid4().hex
    label = "cjrepomesh.backup-drill=" + scope
    containers: list[str] = []
    volumes: list[str] = []
    docker_env = {key: value for key, value in os.environ.items()
                  if not key.startswith(("CJREPO_", "CJREPOMESH_"))}
    client_env = dict(docker_env)
    client_env.pop("CJPM_CONFIG", None)
    isolated_home = root / "home"
    isolated_home.mkdir()
    client_env.update(HOME=str(isolated_home), USERPROFILE=str(isolated_home),
                      CJREPOMESH_BACKUP_READ_TOKEN="backup-read-fixture")
    base = f"http://127.0.0.1:{args.port}"
    client_registry = "http://127.0.0.1:8080" if args.client_bundle else base
    client_manifest_sha = (hashlib.sha256((args.client_bundle / "manifest.json").read_bytes()).hexdigest()
                           if args.client_bundle else None)
    recovered = None
    completed = 0
    success = False

    def docker(*arguments: str, stdin=None, stdout=subprocess.PIPE) -> bytes:
        result = subprocess.run(["docker", *arguments], env=docker_env, stdin=stdin, stdout=stdout,
                                stderr=subprocess.PIPE, timeout=60, check=False)
        if result.returncode:
            raise TestFailure(f"Docker {arguments[0]} failed: {result.stderr.decode(errors='replace')}")
        return result.stdout or b""

    def passed(message: str) -> None:
        nonlocal completed
        completed += 1
        print("PASS " + message, flush=True)

    def volume(suffix: str) -> str:
        name = scope + "-" + suffix
        docker("volume", "create", "--label", label, name)
        volumes.append(name)
        return name

    def create(image: str, mount: str, *options: str, command: tuple[str, ...] = ()) -> str:
        identifier = docker("create", "--pull=never", "--label", label, "--read-only",
                            "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
                            "--mount", mount, *options, image, *command).decode().strip()
        containers.append(identifier)
        return identifier

    def export(image: str, storage: str, target: Path) -> dict[str, str]:
        identifier = create(image, f"type=volume,source={storage},target=/var/lib/cjrepo,readonly",
                            "--network=none", "--entrypoint", "/bin/tar",
                            command=("-C", "/var/lib/cjrepo", "-cf", "-", "."))
        with target.open("wb") as output:
            docker("start", "--attach", identifier, stdout=output)
        return archive_manifest(target)

    def restore(image: str, storage: str, archive: Path) -> None:
        archive_manifest(archive)
        identifier = create(image, f"type=volume,source={storage},target=/var/lib/cjrepo",
                            "--network=none", "--interactive", "--entrypoint", "/bin/tar",
                            command=("-C", "/var/lib/cjrepo", "-xf", "-"))
        with archive.open("rb") as source:
            docker("start", "--attach", "--interactive", identifier, stdin=source)

    def server(image: str, storage: str) -> str:
        identifier = create(image, f"type=volume,source={storage},target=/var/lib/cjrepo",
                            "--publish", f"127.0.0.1:{args.port}:8080", "--init",
                            "--tmpfs", "/tmp:size=16m,mode=1777",
                            "--env", "CJREPO_ADDRESS=0.0.0.0", "--env", "CJREPO_PORT=8080",
                            "--env", "CJREPO_STORAGE=/var/lib/cjrepo",
                            "--env", "CJREPO_PUBLISH_TOKEN=backup-publish-fixture",
                            "--env", "CJREPO_READ_TOKEN=backup-read-fixture",
                            "--env", "CJREPO_UPSTREAM=", "--env", "CJREPO_UPSTREAM_TOKEN=")
        docker("start", identifier)
        wait_for_health(args.port)
        mount = json.loads(docker("inspect", identifier))[0]["Mounts"]
        assert_equal([item["Name"] for item in mount if item["Destination"] == "/var/lib/cjrepo"],
                     [storage], label="server uses the intended named volume")
        return identifier

    def stop(identifier: str, suffix: str) -> None:
        docker("stop", "--time", "5", identifier)
        (logs / f"server-{suffix}.log").write_bytes(docker("logs", identifier))
        state = json.loads(docker("inspect", identifier))[0]["State"]
        assert_equal(state["Running"], False, label="source is stopped before backup")
        wait_for_ports_closed((args.port,))

    def client_command(command: str, target: Path, suffix: str) -> CommandResult:
        if cjpm:
            return run_command((cjpm, command), cwd=target, env=client_env, timeout=90)
        native_mounts = []
        if args.client_native:
            native_mounts += ["--mount", f"type=bind,source={args.client_native.resolve()},target=/opt/native,readonly"]
            for path in sorted((args.client_native / "system").rglob("*")):
                if path.is_file():
                    destination = "/" + path.relative_to(args.client_native / "system").as_posix()
                    native_mounts += ["--mount", f"type=bind,source={path.resolve()},target={destination},readonly"]
        if command == "run" and recovered is None:
            raise TestFailure("A restored server is required for consumer jobs")
        # Share only this owned restored server's network namespace. The client
        # reaches its internal port without exposing the host beyond loopback.
        identifier = create(image, f"type=bind,source={target.resolve()},target=/job",
            "--network", "container:" + recovered if command == "run" else "none",
            "--tmpfs", "/tmp:size=128m,mode=1777", "--workdir", "/job",
            "--mount", f"type=bind,source={args.client_sdk.resolve()},target=/opt/cangjie,readonly",
            "--mount", f"type=bind,source={args.client_bundle.resolve()},target=/opt/client,readonly",
            *native_mounts, "--env", "HOME=/job/.home", "--env", "USERPROFILE=/job/.home",
            "--env", "CJREPOMESH_BACKUP_READ_TOKEN=backup-read-fixture", "--entrypoint", "/bin/bash",
            command=("-ec", 'source /opt/cangjie/envsetup.sh; '
                     'export PATH="/opt/native/bin:$PATH" LD_LIBRARY_PATH="/opt/native/lib:$LD_LIBRARY_PATH"; '
                     'exec /opt/client/run.sh "$@"', "cjpm-job", command))
        # The launcher reports integrity on stderr; preserve both streams.
        output = run_command(("docker", "start", "--attach", identifier), cwd=root,
                             env=docker_env, timeout=180).output
        state = json.loads(docker("inspect", identifier))[0]["State"]
        (logs / f"client-{suffix}.log").write_text(output, encoding="utf-8")
        assert_equal(state["ExitCode"], 0, label="real container client exit")
        assert_contains(output, "PASS: client bundle integrity; cjpm SHA-256 " +
                        client_manifest["files"]["cjpm"]["sha256"])
        return CommandResult(0, output)

    def fixture(relative: str, suffix: str) -> Path:
        target = root / suffix
        target.mkdir()
        for name in ("cjpm.toml", "README.md", "src"):
            original = TESTS / relative / name
            if original.is_dir():
                shutil.copytree(original, target / name)
            elif original.is_file():
                shutil.copyfile(original, target / name)
        (target / "cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "{client_registry}"\n'
            'token-env = "CJREPOMESH_BACKUP_READ_TOKEN"\n', encoding="utf-8")
        return target

    def bundle(relative: str, suffix: str, version: str | None = None) -> dict:
        target = fixture(relative, suffix)
        if version is not None:
            config = target / "cjpm.toml"
            text = config.read_text(encoding="utf-8")
            assert_equal(text.count('version = "2.0.0"'), 1, label="fixture version replacement")
            config.write_text(text.replace('version = "2.0.0"', f'version = "{version}"'), encoding="utf-8")
        result = client_command("bundle", target, suffix)
        (logs / f"bundle-{suffix}.log").write_text(result.output, encoding="utf-8")
        metadata = (target / "target/meta-data.json").read_bytes()
        value = json.loads(metadata)
        candidates = list((target / "target").glob("*.cjp"))
        assert_equal(len(candidates), 1, label="one real bundled archive")
        artifact = candidates[0].read_bytes()
        assert_equal(hashlib.sha256(artifact).hexdigest(), value["index"]["sha256sum"], label="bundle SHA-256")
        return dict(name=value["name"], version=value["version"], organization=value["organization"],
                    artifact=artifact, frame=publish_frame(metadata, artifact))

    def query(package: dict) -> str:
        return "?organization=" + package["organization"] if package["organization"] else ""

    def publish(package: dict, expected: int = 200) -> None:
        result = http_request("POST", base + "/pkg/" + package["name"] + query(package),
                              headers={"Authorization": "backup-publish-fixture"}, body=package["frame"])
        assert_equal(result.status, expected, label="publication status")

    def read_all(packages: list[dict]) -> None:
        for package in packages:
            name = package["name"]
            index_path = f"/index/{name[:2]}/{name[2:4]}/{name}{query(package)}"
            artifact_path = f"/pkg/{name}/{package['version']}{query(package)}"
            for path in (index_path, artifact_path):
                assert_equal(http_request("GET", base + path).status, 401, label="private read")
            index = http_request("GET", base + index_path, headers={"Authorization": "backup-read-fixture"})
            assert_equal(index.status, 200, label="index read")
            rows = [json.loads(line) for line in index.body.splitlines() if line]
            selected = [row for row in rows if row["version"] == package["version"]]
            assert_equal(len(selected), 1, label="one selected version")
            assert_equal(selected[0]["organization"], package["organization"], label="organization retained")
            result = http_request("GET", base + artifact_path, headers={"Authorization": "backup-read-fixture"})
            assert_equal(result.status, 200, label="artifact read")
            assert_equal(result.body, package["artifact"], label="archive bytes retained")
            assert_equal(hashlib.sha256(result.body).hexdigest(), selected[0]["sha256sum"], label="index SHA-256")

    try:
        image = json.loads(docker("image", "inspect", args.image))[0]["Id"]
        packages = [bundle("multirepo/packages/meshdep-v1-low", "default-v1"),
                    bundle("multirepo/packages/meshdep-v2-low", "default-v2"),
                    bundle("hosted-server/org-package", "organization-v1")]
        fourth = bundle("multirepo/packages/meshdep-v2-low", "default-v3", "3.0.0")
        source_volume, restored_volume = volume("source"), volume("restored")
        original = server(image, source_volume)
        binary_sha = docker("exec", original, "sha256sum", "/usr/local/bin/cjrepo").decode().split()[0]
        (logs / "runtime.json").write_text(json.dumps(dict(image=image, server_sha256=binary_sha,
            client_sha256=client_manifest["files"]["cjpm"]["sha256"] if client_manifest else None,
            client_manifest_sha256=client_manifest_sha,
            source_volume=source_volume, restored_volume=restored_volume), indent=2), encoding="utf-8")
        for package in packages:
            publish(package)
        read_all(packages)
        passed("real default and named-organization archives published with private reads")
        stop(original, "source")
        backup = logs / "backup.tar"
        expected = export(image, source_volume, backup)
        assert_equal(len(expected), 5, label="complete two indexes and three artifacts")
        (logs / "backup-manifest.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
        backup_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
        passed("stopped source volume exported to a complete validated tar archive")
        assert_equal(source_volume == restored_volume, False, label="distinct restore volume")
        restore(image, restored_volume, backup)
        assert_equal(export(image, restored_volume, root / "restored-before-start.tar"), expected,
                     label="new volume has identical file set and SHA-256")
        passed("archive restored into a different volume with matching file hashes")
        recovered = server(image, restored_volume)
        assert_equal(json.loads(docker("inspect", original))[0]["State"]["Running"], False,
                     label="original source remains offline")
        read_all(packages)
        passed("restored container serves private archives while original remains stopped")
        for suffix, relative, marker in (("default", "hosted-server/app", "low-2.0.0"),
                                         ("organization", "hosted-server/org-app", "meshcorp-1.0.0")):
            consumer = fixture(relative, "consumer-" + suffix)
            result = client_command("run", consumer, "consumer-" + suffix)
            (logs / f"consumer-{suffix}.log").write_text(result.output, encoding="utf-8")
            assert_contains(result.output, marker)
            passed(f"fresh-cache {suffix} client builds and runs from restored volume")
        for package in packages:
            publish(package, 409)
        publish(fourth)
        read_all(packages + [fourth])
        passed("restored volume rejects duplicates and accepts another real version")
        stop(recovered, "restored")
        docker("start", recovered)
        wait_for_health(args.port)
        read_all(packages + [fourth])
        passed("restored and newly published archives remain readable after restart")
        stop(recovered, "restored-restart")
        assert_equal(export(image, source_volume, root / "source-after.tar"), expected,
                     label="source volume remains unchanged")
        assert_equal(hashlib.sha256(backup.read_bytes()).hexdigest(), backup_sha, label="backup archive unchanged")
        if args.client_bundle:
            assert_equal(client_verifier(args.client_bundle), client_manifest, label="client delivery unchanged")
            assert_equal(hashlib.sha256((args.client_bundle / "manifest.json").read_bytes()).hexdigest(),
                         client_manifest_sha, label="client manifest unchanged")
        passed("source volume and backup archive remain unchanged by restored writes")
        success = True
    except (TestFailure, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f"FAIL Docker cold backup: {error}", flush=True)
    finally:
        cleanup_failed = False
        for identifier in reversed(containers):
            if not success:
                try:
                    (logs / f"failure-{identifier}-inspect.json").write_bytes(docker("inspect", identifier))
                    with (logs / f"failure-{identifier}.log").open("wb") as output:
                        result = subprocess.run(["docker", "logs", identifier], env=docker_env,
                            stdout=output, stderr=subprocess.STDOUT, timeout=30, check=False)
                        if result.returncode:
                            raise TestFailure("Failed to save owned-container logs")
                except (TestFailure, OSError, subprocess.TimeoutExpired) as error:
                    cleanup_failed = True
                    print(f"FAIL diagnostic capture; container retained: {identifier}: {error}", flush=True)
                    try:
                        docker("stop", "--time", "5", identifier)
                    except (TestFailure, OSError, subprocess.TimeoutExpired):
                        pass
                    continue
            try:
                docker("rm", "--force", identifier)
            except (TestFailure, OSError, subprocess.TimeoutExpired) as error:
                cleanup_failed = True
                print(f"FAIL owned-container cleanup: {error}", flush=True)
        if success and not cleanup_failed:
            for name in reversed(volumes):
                try:
                    info = json.loads(docker("volume", "inspect", name))[0]
                    assert_equal(info["Labels"].get("cjrepomesh.backup-drill"), scope, label="owned volume label")
                    docker("volume", "rm", name)
                except (TestFailure, OSError, subprocess.TimeoutExpired) as error:
                    cleanup_failed = True
                    print(f"FAIL owned-volume cleanup: {error}", flush=True)
        success = success and not cleanup_failed
        (logs / "summary.json").write_text(json.dumps(dict(success=success, passed=completed, total=9,
            client_mode="container-bundle" if args.client_bundle else "native-host",
            client_sha256=client_manifest["files"]["cjpm"]["sha256"] if client_manifest else None,
            cleanup_failed=cleanup_failed), indent=2) + "\n", encoding="utf-8")
        if success:
            remove_within(root, (parent,))
        else:
            print(f"Failure storage retained: {root}; named volumes: {volumes}", flush=True)
    print(f"Docker cold backup: {completed}/9 checkpoints passed; success={success}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
