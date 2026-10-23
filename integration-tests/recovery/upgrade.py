#!/usr/bin/env python3
"""Rehearse a stopped-volume upgrade and snapshot rollback using existing local images."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import TestFailure, http_request, publish_frame, wait_for_health, wait_for_ports_closed
from docker_backup import archive_manifest
from upgrade_client import consume, verify_inputs


def docker_output(command, *, environment, stdin=None, stdout=subprocess.PIPE,
                  timeout=60, include_stderr=False):
    result = subprocess.run(command, env=environment, stdin=stdin, stdout=stdout,
                            stderr=subprocess.STDOUT if include_stderr else subprocess.PIPE,
                            timeout=timeout)
    if result.returncode:
        raise TestFailure('Docker command failed with exit ' + str(result.returncode))
    return result.stdout or b''


def fixture(directory: Path) -> dict:
    metadata = (directory / "meta-data.json").read_bytes()
    item = json.loads(metadata)
    for key in ("name", "organization", "version"):
        value = item[key]
        if not isinstance(value, str) or (not value and key != "organization"):
            raise ValueError("invalid fixture metadata")
        if value and not re.fullmatch(r"[A-Za-z0-9_+.-]+", value):
            raise ValueError("unsupported fixture identifier")
    artifact = (directory / f"{item['name']}-{item['version']}.cjp").read_bytes()
    if hashlib.sha256(artifact).hexdigest() != item["index"]["sha256sum"]:
        raise ValueError("fixture archive does not match its index")
    if any(item[key] != item["index"][key] for key in ("name", "organization", "version")):
        raise ValueError("fixture identity does not match its index")
    query = "?organization=" + item["organization"] if item["organization"] else ""
    name = item["name"]
    return dict(name=name, version=item["version"], organization=item["organization"],
                sha256=item["index"]["sha256sum"], artifact=artifact,
                frame=publish_frame(metadata, artifact), publish=f"/pkg/{name}{query}",
                index=f"/index/{name[:2]}/{name[2:4]}/{name}{query}",
                download=f"/pkg/{name}/{item['version']}{query}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-image", required=True, help="existing local Linux amd64 server image")
    parser.add_argument("--candidate-image", required=True, help="different existing local server image")
    parser.add_argument("--seed-package", type=Path, required=True, help="real default-organization bundle directory")
    parser.add_argument("--new-package", type=Path, required=True, help="real named-organization bundle directory")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="new directory; retains synthetic snapshots")
    parser.add_argument("--client-bundle", type=Path, help="optional complete Linux client for four protected cold consumers")
    parser.add_argument("--client-sdk", type=Path, help="existing Linux SDK, mounted read-only")
    parser.add_argument("--client-native", type=Path, help="existing Linux ar/ld and runtime files, mounted read-only")
    parser.add_argument("--expected-output", default="high-1.0.0", help="seed meshdep registryMarker output in client mode")
    args = parser.parse_args()
    client_manifest = verify_inputs(args, parser)
    seed, addition = fixture(args.seed_package), fixture(args.new_package)
    if seed["organization"] or not addition["organization"]:
        parser.error("use a default-organization seed and a named-organization new package")
    if client_manifest and (seed['name'] != 'meshdep' or addition['name'] != 'teamhello' or
                            addition['organization'] != 'company' or addition['version'] != '1.0.0'):
        parser.error('client mode requires meshdep and company::teamhello 1.0.0 API fixtures')
    total = 18 if client_manifest else 14
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    scope = "cjrepomesh-upgrade-" + uuid.uuid4().hex
    label_key = "io.cjrepomesh.upgrade-drill"
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("CJREPO_", "CJREPOMESH_", "COMPOSE_"))}
    environment.update(CJREPO_PUBLISH_TOKEN=secrets.token_hex(32), CJREPO_READ_TOKEN=secrets.token_hex(32))
    secret_values = [environment["CJREPO_PUBLISH_TOKEN"], environment["CJREPO_READ_TOKEN"]]
    containers, volumes, stages, identities, cleanup_errors = [], [], [], {}, []
    error, success = "", False
    started = time.monotonic()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    def docker(*arguments, stdin=None, stdout=subprocess.PIPE, timeout=60, include_stderr=False):
        return docker_output(["docker", *map(str, arguments)], environment=environment,
            stdin=stdin, stdout=stdout, timeout=timeout, include_stderr=include_stderr)

    def inspect(identifier):
        return json.loads(docker("inspect", identifier))[0]

    def save_log(identifier, name):
        # Do not persist inspect.Config.Env or unredacted credential-bearing logs.
        result = subprocess.run(["docker", "logs", identifier], env=environment,
                                capture_output=True, timeout=30)
        if result.returncode:
            raise TestFailure("could not retain owned server logs")
        output = (result.stdout + result.stderr).decode(errors="replace")
        for value in secret_values:
            output = output.replace(value, "[REDACTED]")
        (report / (name + ".log")).write_text(output, encoding="utf-8")

    def passed(name, **facts):
        stages.append(dict(name=name, facts=facts))
        print(f"PASS {len(stages)}/{total} {name}", flush=True)

    def cold_consumer(name, server, packages):
        if client_manifest:
            facts = consume(name=name, server=server, image=identities['candidate']['image'],
                packages=packages, args=args, manifest=client_manifest, report=report,
                docker=docker, inspect=inspect, register=containers.append,
                label_key=label_key, scope=scope, secret_values=secret_values)
            passed(name + '-protected-cold-client-build-run', **facts)

    def create(image, volume=None, *, writable=False, server=False, invalid=False, interactive=False, command=()):
        options = ["create", "--pull=never", "--label", label_key + "=" + scope,
                   "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges:true"]
        if volume:
            options += ["--mount", f"type=volume,source={volume},target=/var/lib/cjrepo" +
                        ("" if writable else ",readonly")]
        if interactive:
            options.append("--interactive")
        if server:
            options += ["--init", "--tmpfs", "/tmp:size=16m,mode=1777",
                        "--publish", f"127.0.0.1:{port}:8080", "--env", "CJREPO_ADDRESS=0.0.0.0",
                        "--env", "CJREPO_PORT=8080", "--env", "CJREPO_STORAGE=/var/lib/cjrepo",
                        "--env", "CJREPO_PUBLISH_TOKEN", "--env", "CJREPO_READ_TOKEN",
                        "--env", "CJREPO_UPSTREAM=" + ("invalid-upstream-fixture" if invalid else ""),
                        "--env", "CJREPO_UPSTREAM_TOKEN="]
        else:
            options += ["--network=none", "--entrypoint", command[0]]
            command = command[1:]
        identifier = docker(*options, image, *command).decode().strip()
        containers.append(identifier)
        return identifier

    def volume(suffix):
        name = scope + "-" + suffix
        docker("volume", "create", "--label", label_key + "=" + scope, name)
        volumes.append(name)
        return name

    def no_writer(storage):
        for identifier in docker("ps", "-q", "--filter", "volume=" + storage).decode().split():
            info = inspect(identifier)
            if any(m.get("Name") == storage and m.get("RW") for m in info["Mounts"]):
                raise TestFailure("storage still has a running writer")

    def export(image, storage, target):
        no_writer(storage)
        identifier = create(image, storage, command=("/bin/tar", "-C", "/var/lib/cjrepo", "-cf", "-", "."))
        with target.open("xb") as stream:
            docker("start", "--attach", identifier, stdout=stream)
        return archive_manifest(target)

    def restore(image, storage, archive):
        no_writer(storage)
        # Restore only into a newly created, empty volume owned by this drill.
        info = json.loads(docker("volume", "inspect", storage))[0]
        if storage not in volumes or info["Labels"].get(label_key) != scope:
            raise TestFailure("restore destination is not owned by this drill")
        identifier = create(image, storage, command=("/bin/tar", "-C", "/var/lib/cjrepo", "-cf", "-", "."))
        empty = report / (storage.rsplit("-", 1)[-1] + "-before-restore.tar")
        with empty.open("xb") as stream:
            docker("start", "--attach", identifier, stdout=stream)
        if archive_manifest(empty):
            raise TestFailure("restore destination is not empty")
        archive_manifest(archive)
        identifier = create(image, storage, writable=True, interactive=True,
                            command=("/bin/tar", "-C", "/var/lib/cjrepo", "-xf", "-"))
        with archive.open("rb") as stream:
            docker("start", "--attach", "--interactive", identifier, stdin=stream)

    def start_server(image, storage):
        no_writer(storage)
        identifier = create(image, storage, writable=True, server=True)
        docker("start", identifier)
        wait_for_health(port)
        info = inspect(identifier)
        if (info["Image"] != image or info["Config"]["User"] != "10001:10001" or
                not info["HostConfig"]["ReadonlyRootfs"] or "ALL" not in info["HostConfig"]["CapDrop"] or
                not any(v.startswith("no-new-privileges") for v in info["HostConfig"]["SecurityOpt"])):
            raise TestFailure("runtime identity or restrictions differ from the selected image")
        if info["NetworkSettings"]["Ports"]["8080/tcp"] != [dict(HostIp="127.0.0.1", HostPort=str(port))]:
            raise TestFailure("server binding differs from loopback-only test binding")
        expected_env = {k + "=" + environment[k] for k in ("CJREPO_PUBLISH_TOKEN", "CJREPO_READ_TOKEN")}
        if not expected_env.issubset(set(info["Config"]["Env"])):
            raise TestFailure("credentials changed across switch")
        if [m["Name"] for m in info["Mounts"] if m["Destination"] == "/var/lib/cjrepo"] != [storage]:
            raise TestFailure("server is using a different volume")
        return identifier

    def stop(identifier, name):
        docker("stop", "--time", "5", identifier)
        if inspect(identifier)["State"]["Running"]:
            raise TestFailure("server did not stop")
        save_log(identifier, name)
        wait_for_ports_closed((port,))

    def request(path, token="", body=None):
        return http_request("POST" if body is not None else "GET", base + path,
                            headers={"Authorization": token} if token else {}, body=body)

    def publish(package, expected=200):
        if request(package["publish"], environment["CJREPO_PUBLISH_TOKEN"], package["frame"]).status != expected:
            raise TestFailure("unexpected publication status")

    def read_all(packages):
        for item in packages:
            for path in (item["index"], item["download"]):
                if request(path).status != 401:
                    raise TestFailure("private data can be read without credentials")
            index = request(item["index"], environment["CJREPO_READ_TOKEN"])
            content = request(item["download"], environment["CJREPO_READ_TOKEN"])
            if index.status != 200 or content.status != 200 or content.body != item["artifact"]:
                raise TestFailure("package index or archive differs across switch")
            rows = [json.loads(row) for row in index.body.splitlines() if row]
            matches = [row for row in rows if row["version"] == item["version"]]
            if (len(matches) != 1 or matches[0]["sha256sum"] != item["sha256"] or
                    matches[0]["organization"] != item["organization"]):
                raise TestFailure("package identity or checksum differs across switch")
            if request(item["download"], environment["CJREPO_PUBLISH_TOKEN"]).status != 401:
                raise TestFailure("publish token unexpectedly permits private reads")

    try:
        for role, reference in (("previous", args.previous_image), ("candidate", args.candidate_image)):
            info = json.loads(docker("image", "inspect", reference))[0]
            if info["Os"] != "linux" or info["Architecture"] != "amd64":
                raise TestFailure("this drill requires existing Linux amd64 images")
            identifier = create(info["Id"], command=("sha256sum", "/usr/local/bin/cjrepo"))
            binary_sha = docker("start", "--attach", identifier).decode().split()[0]
            if not re.fullmatch(r"[a-f0-9]{64}", binary_sha):
                raise TestFailure("could not identify server binary")
            identities[role] = dict(image=info["Id"], server_sha256=binary_sha)
        previous, candidate = identities["previous"]["image"], identities["candidate"]["image"]
        if previous == candidate or identities["previous"]["server_sha256"] == identities["candidate"]["server_sha256"]:
            raise TestFailure("use two different existing server builds")
        passed("distinct-image-and-server-identities-pinned", **identities)
        original, upgraded, recovered = volume("original"), volume("candidate"), volume("recovered")
        server = start_server(previous, original)
        publish(seed)
        publish(seed, 409)
        read_all([seed])
        passed("previous-version-publishes-and-protects-real-seed-package")
        stop(server, "previous-before-backup")
        no_writer(original)
        passed("previous-writer-stopped-before-snapshot")
        backup = report / "before-upgrade.tar"
        baseline = export(previous, original, backup)
        if len(baseline) != 2:
            raise TestFailure("expected one index and one archive in initial snapshot")
        backup_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
        (report / "before-upgrade-manifest.json").write_text(json.dumps(baseline, indent=2) + "\n")
        passed("complete-pre-upgrade-snapshot-validated", archive_sha256=backup_sha)
        restore(candidate, upgraded, backup)
        if export(candidate, upgraded, report / "candidate-restored.tar") != baseline:
            raise TestFailure("candidate restore differs from snapshot")
        passed("candidate-starts-from-distinct-byte-identical-volume")
        server = start_server(candidate, upgraded)
        read_all([seed])
        publish(addition)
        publish(addition, 409)
        read_all([seed, addition])
        cold_consumer('candidate', server, [seed, addition])
        stop(server, "candidate-after-publication")
        post_upgrade = export(candidate, upgraded, report / "after-upgrade.tar")
        if len(post_upgrade) != 4:
            raise TestFailure("candidate snapshot must include both real packages")
        passed("candidate-reads-old-package-and-publishes-named-organization-package")
        server = start_server(previous, upgraded)
        read_all([seed, addition])
        publish(addition, 409)
        cold_consumer('compatible-downgrade', server, [seed, addition])
        stop(server, "previous-reading-candidate-data")
        passed("previous-version-reads-candidate-writes-with-same-credentials")
        if export(previous, upgraded, report / "after-compatible-downgrade.tar") != post_upgrade:
            raise TestFailure("compatible downgrade changed stored file hashes")
        passed("compatible-downgrade-preserves-all-package-bytes")
        failed = create(candidate, upgraded, writable=True, server=True, invalid=True)
        docker("start", failed)
        deadline = time.monotonic() + 15
        while inspect(failed)["State"]["Running"] and time.monotonic() < deadline:
            time.sleep(0.2)
        state = inspect(failed)["State"]
        save_log(failed, "candidate-rejected-configuration")
        if state["Running"] or state["ExitCode"] != 2:
            raise TestFailure("controlled invalid candidate configuration did not fail with exit 2")
        wait_for_ports_closed((port,))
        no_writer(upgraded)
        if export(candidate, upgraded, report / "after-rejected-start.tar") != post_upgrade:
            raise TestFailure("rejected candidate changed stored bytes")
        passed("controlled-candidate-startup-failure-leaves-no-writer-or-data-change", exit_code=2)
        restore(previous, recovered, backup)
        if export(previous, recovered, report / "recovered-before-start.tar") != baseline:
            raise TestFailure("rollback restore differs from pre-upgrade snapshot")
        passed("pre-upgrade-snapshot-restored-to-new-owned-volume")
        server = start_server(previous, recovered)
        read_all([seed])
        if request(addition["download"], environment["CJREPO_READ_TOKEN"]).status != 404:
            raise TestFailure("snapshot rollback unexpectedly contains a later publication")
        passed("rollback-serves-seed-and-explicitly-excludes-post-snapshot-write")
        cold_consumer('snapshot-rollback', server, [seed])
        publish(addition)
        publish(addition, 409)
        read_all([seed, addition])
        passed("rollback-service-accepts-new-publication-and-rejects-duplicates")
        cold_consumer('rollback-republished', server, [seed, addition])
        stop(server, "rollback-before-restart")
        server = start_server(previous, recovered)
        read_all([seed, addition])
        stop(server, "rollback-after-restart")
        passed("rollback-data-survives-server-recreation")
        if (export(previous, original, report / "original-after-drill.tar") != baseline or
                export(candidate, upgraded, report / "candidate-after-drill.tar") != post_upgrade or
                hashlib.sha256(backup.read_bytes()).hexdigest() != backup_sha):
            raise TestFailure("original, candidate storage or snapshot was changed by rollback")
        passed("original-candidate-and-snapshot-preserved-independently")
        if client_manifest:
            if verify_inputs(args, parser) != client_manifest:
                raise TestFailure('client bundle changed during drill')
        success = len(stages) == total
    except (TestFailure, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
        print("FAIL upgrade drill: " + error, flush=True)
    finally:
        for identifier in reversed(containers):
            try:
                info = inspect(identifier)
                if info["Config"]["Labels"].get(label_key) != scope:
                    raise TestFailure("container ownership label mismatch")
                if not success:
                    save_log(identifier, "failure-" + identifier[:12])
                docker("rm", "--force", identifier)
            except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as failure:
                cleanup_errors.append("container " + identifier[:12] + ": " + str(failure))
                # Preserve diagnostics on capture failures, but try to leave no writer running.
                try:
                    if inspect(identifier)["Config"]["Labels"].get(label_key) == scope:
                        docker("stop", "--time", "5", identifier)
                except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError):
                    pass
        if success and not cleanup_errors:
            for storage in reversed(volumes):
                try:
                    info = json.loads(docker("volume", "inspect", storage))[0]
                    if info["Labels"].get(label_key) != scope:
                        raise TestFailure("volume ownership label mismatch")
                    docker("volume", "rm", storage)
                except (TestFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as failure:
                    cleanup_errors.append("volume " + storage + ": " + str(failure))
        success = success and not cleanup_errors
        summary = dict(success=success, passed=len(stages), total=total,
                       seconds=round(time.monotonic() - started, 2), stages=stages,
                       identities=identities, error=error, cleanup_errors=cleanup_errors,
                       runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       packages=[{key: item[key] for key in ("name", "version", "organization", "sha256")}
                                 for item in (seed, addition)],
                       retained_volumes=volumes if not success else [],
                       limits=["Existing Docker engine and two specific existing Linux amd64 builds only.",
                               "Controlled startup configuration rejection, not a post-write crash or format migration.",
                               "Snapshot rollback excludes later writes; pause publishers for a real cutover.",
                               ("Four protected Linux cold consumers only; no Windows Cangjie, LAN/HTTPS, CA migration or automatic cutover."
                                if client_manifest else "No client compilation, Windows Cangjie, LAN/HTTPS, automatic upgrade or production cutover.")])
        (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Upgrade drill: {len(stages)}/{total}; success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
