#!/usr/bin/env python3
"""Exercise an exported bundle as a receiver, with an existing real CJP fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid


def client_bundle_identity(root: Path) -> dict:
    # Use the repository's verifier, never execute a candidate's Python code.
    verifier = Path(__file__).resolve().parents[2] / "deployment/client/verify.py"
    manifest = runpy.run_path(str(verifier))["verify_bundle"](root)
    return dict(mode="client-bundle", binarySha256=manifest["files"]["cjpm"]["sha256"],
                manifestSha256=hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path, help="existing cjpm bundle output")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="new local evidence directory")
    parser.add_argument("--check-running", action="store_true", help="exercise verify.py --running in a supporting bundle")
    parser.add_argument("--team-sdk", type=Path, help="optional existing Linux SDK, mounted read-only")
    client = parser.add_mutually_exclusive_group()
    client.add_argument("--team-client", type=Path, help="optional existing Linux enhanced cjpm")
    client.add_argument("--team-client-bundle", type=Path, help="optional complete Linux client delivery directory")
    parser.add_argument("--team-native", type=Path, help="optional existing ar/ld and libraries for a minimal runtime container")
    args = parser.parse_args()
    team_client = args.team_client_bundle or args.team_client
    if bool(args.team_sdk) != bool(team_client):
        parser.error("team-sdk and a team client must be supplied together")
    if args.team_sdk and (not (args.team_sdk / "envsetup.sh").is_file() or
                          (args.team_client and not args.team_client.is_file())):
        parser.error("an existing Linux SDK and client are required")
    client_identity = None
    if args.team_client_bundle:
        try:
            client_identity = client_bundle_identity(args.team_client_bundle)
        except (OSError, ValueError, KeyError, TypeError) as failure:
            parser.error("invalid team client bundle: " + str(failure))
    if args.team_native and (not args.team_sdk or not (args.team_native / "bin/ar").is_file()):
        parser.error("team-native requires team SDK/client and an existing ar")
    total = ((21 if args.team_client_bundle else 20) if args.team_sdk else 12) + (4 if args.check_running else 0)
    bundle, fixture, report = args.bundle.resolve(), args.package_dir.resolve(), args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    installation = report / "installation"
    shutil.copytree(bundle, installation)
    guard = report / "missing-credentials"
    guard.mkdir()
    shutil.copyfile(installation / "compose.yaml", guard / "compose.yaml")
    (guard / ".env").write_text("")
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("CJREPO_", "CJREPOMESH_", "COMPOSE_"))}
    project, projects, secret_values = "", [], []
    manifest = json.loads((installation / "manifest.json").read_text())
    image_tag = manifest["image"]["tag"]
    stages, error, cleanup_errors = [], "", []
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def run(label, arguments, *, cwd=installation, success=True, log=True, variables=None, timeout=120):
        result = subprocess.run([str(value) for value in arguments], cwd=cwd,
                                env=variables or environment, text=True, capture_output=True, timeout=timeout)
        output = result.stdout + result.stderr
        safe = output
        for value in secret_values:
            safe = safe.replace(value, "[REDACTED]")
        if log:
            (report / (label + ".log")).write_text(safe, encoding="utf-8")
        if (result.returncode == 0) != success:
            raise AssertionError(f"{label}: unexpected command exit {result.returncode}; inspect retained log")
        return result

    def compose(label, *arguments, cwd=installation, name=None, **options):
        return run(label, ("docker", "compose", "-p", name or project,
                          "-f", "compose.yaml", "--env-file", ".env", *arguments), cwd=cwd, **options)

    def passed(name, **facts):
        stages.append(dict(name=name, facts=facts))
        print(f"PASS {len(stages)}/{total} {name}", flush=True)

    def request(path, token="", body=None):
        headers = {"Authorization": token} if token else {}
        req = urllib.request.Request(base + path, data=body, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with opener.open(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as failure:
            return failure.code, failure.read()

    def expect(status, expected):
        if status != expected:
            raise AssertionError(f"unexpected HTTP status {status}, expected {expected}")

    def healthy():
        for _ in range(60):
            try:
                status, body = request("/health")
                if status == 200 and json.loads(body).get("service") == "cjrepo":
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        raise AssertionError("receiver service did not become healthy")

    def running_diagnostic(label):
        # HTTP can be ready before Docker's periodic healthcheck has run.
        identifier = compose(label + "-container", "ps", "-q", "cjrepo", log=False).stdout.strip()
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise AssertionError("expected one running receiver container")
        for _ in range(30):
            status = run(label + "-health", ("docker", "inspect", "--format",
                "{{.State.Health.Status}}", identifier), log=False).stdout.strip()
            if status == "healthy":
                run(label, (sys.executable, "verify.py", "--running"))
                return
            if status == "unhealthy":
                raise AssertionError("receiver Docker healthcheck failed")
            time.sleep(0.5)
        raise AssertionError("receiver Docker healthcheck did not become ready")

    try:
        run("verify-files", (sys.executable, "verify.py"))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        run("configure", (sys.executable, "configure.py", "--port", str(port)))
        credentials = dict(line.split("=", 1) for line in (installation / ".env").read_text().splitlines())
        secret_values.extend((credentials["CJREPO_PUBLISH_TOKEN"], credentials["CJREPO_READ_TOKEN"]))
        project = credentials["COMPOSE_PROJECT_NAME"]
        assert re.fullmatch(r"cjrepomesh-[a-f0-9]{16}", project)
        projects.append((project, installation))
        credential_sha = hashlib.sha256((installation / ".env").read_bytes()).hexdigest()
        passed("bundle-verified-and-private-configuration-created")
        if args.check_running:
            run("runtime-before-start", (sys.executable, "verify.py", "--running"), success=False)
            passed("runtime-diagnostic-rejects-not-started-deployment")

        run("image-load", ("docker", "load", "--input", "image.tar"), timeout=300)
        run("verify-runtime", (sys.executable, "verify.py", "--docker"))
        passed("offline-archive-loaded-and-server-identity-verified", image=manifest["image"]["id"],
               server_sha256=manifest["image"]["serverSha256"])

        override = installation / "compose.override.yaml"
        override.write_text('services:\n  cjrepo:\n    image: unsafe-override-fixture\n    ports:\n      - "0.0.0.0:1:8080"\n')
        poisoned = dict(environment, COMPOSE_FILE=str(override))
        config = json.loads(compose("explicit-config", "config", "--format", "json", log=False,
                                    variables=poisoned).stdout)
        service = config["services"]["cjrepo"]
        assert service["image"] == image_tag
        assert len(service["ports"]) == 1 and service["ports"][0]["host_ip"] == "127.0.0.1"
        passed("explicit-compose-file-ignores-untrusted-overrides")

        guard_project = "cjrepomesh-guard-" + uuid.uuid4().hex[:16]
        projects.append((guard_project, guard))
        compose("missing-publish", "run", "--rm", "--no-deps", "cjrepo", cwd=guard,
                name=guard_project, success=False, timeout=30)
        assert "publish token must be configured" in (report / "missing-publish.log").read_text()
        passed("missing-publish-token-refuses-startup")
        (guard / ".env").write_text("CJREPO_PUBLISH_TOKEN=" + credentials["CJREPO_PUBLISH_TOKEN"] + "\n")
        compose("missing-read", "run", "--rm", "--no-deps", "cjrepo", cwd=guard,
                name=guard_project, success=False, timeout=30)
        assert "read token must be configured" in (report / "missing-read.log").read_text()
        passed("missing-read-token-refuses-startup")

        compose("up", "up", "-d", "--no-build", "--pull", "never")
        healthy()
        container = compose("container-id", "ps", "-q", "cjrepo").stdout.strip()
        info = json.loads(run("inspect-container", ("docker", "inspect", container), log=False).stdout)[0]
        assert info["Image"] == manifest["image"]["id"]
        assert info["Config"]["User"] == "10001:10001"
        assert info["HostConfig"]["ReadonlyRootfs"] and "ALL" in info["HostConfig"]["CapDrop"]
        assert any(value.startswith("no-new-privileges") for value in info["HostConfig"]["SecurityOpt"])
        assert info["NetworkSettings"]["Ports"]["8080/tcp"] == [dict(HostIp="127.0.0.1", HostPort=str(port))]
        passed("healthy-server-with-fixed-image-and-runtime-constraints")
        if args.check_running:
            running_diagnostic("runtime-healthy")
            passed("runtime-diagnostic-verifies-running-deployment")

        metadata = json.loads((fixture / "meta-data.json").read_text())
        package, version = metadata["name"], metadata["version"]
        assert metadata["organization"] == "" and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", package)
        artifact = (fixture / f"{package}-{version}.cjp").read_bytes()
        checksum = hashlib.sha256(artifact).hexdigest()
        assert checksum == metadata["index"]["sha256sum"]
        raw_metadata = json.dumps(metadata, separators=(",", ":")).encode()
        frame = b"\x01" + struct.pack("<I", len(raw_metadata)) + raw_metadata
        frame += b"\x01" + struct.pack("<I", len(artifact)) + artifact
        index_path = f"/index/{package[:2]}/{package[2:4]}/{package}"
        archive_path, publish_path = f"/pkg/{package}/{version}", f"/pkg/{package}"
        for path in (index_path, archive_path):
            expect(request(path)[0], 401)
        expect(request(publish_path, body=frame)[0], 401)
        passed("anonymous-read-and-publish-denied")
        expect(request(publish_path, credentials["CJREPO_READ_TOKEN"], frame)[0], 401)
        expect(request(index_path, credentials["CJREPO_PUBLISH_TOKEN"])[0], 401)
        passed("read-and-publish-token-scopes-separated")

        expect(request(publish_path, credentials["CJREPO_PUBLISH_TOKEN"], frame)[0], 200)
        status, content = request(archive_path, credentials["CJREPO_READ_TOKEN"])
        expect(status, 200)
        assert content == artifact
        status, content = request(index_path, credentials["CJREPO_READ_TOKEN"])
        expect(status, 200)
        assert json.loads(content.decode().strip())["sha256sum"] == checksum
        passed("real-cjp-published-and-read-with-exact-checksum", archive_sha256=checksum)
        expect(request(archive_path + "?organization=company", credentials["CJREPO_READ_TOKEN"])[0], 404)
        passed("organization-query-does-not-alias-default-storage")

        compose("down-retain-data", "down")
        if args.check_running:
            run("runtime-stopped", (sys.executable, "verify.py", "--running"), success=False)
            passed("runtime-diagnostic-rejects-stopped-deployment")
        compose("recreate", "up", "-d", "--no-build", "--pull", "never")
        healthy()
        status, content = request(archive_path, credentials["CJREPO_READ_TOKEN"])
        expect(status, 200)
        assert content == artifact
        passed("real-archive-survives-container-recreation")
        if args.check_running:
            running_diagnostic("runtime-recreated")
            passed("runtime-diagnostic-verifies-recreated-deployment")
        expect(request(publish_path, credentials["CJREPO_PUBLISH_TOKEN"], frame)[0], 409)
        assert hashlib.sha256((installation / ".env").read_bytes()).hexdigest() == credential_sha
        passed("duplicate-rejected-and-original-credentials-preserved")

        if args.team_sdk:
            if args.team_client_bundle:
                passed("delivered-client-verified-before-team-jobs", **client_identity)
            example = Path(__file__).resolve().parents[2] / "examples" / "team"
            registry = "http://cjrepo:8080"
            network = project + "_default"
            team_root = report / "team"
            team_root.mkdir()

            def workspace(label, role):
                job = team_root / label
                run("prepare-" + label, (sys.executable, example / "prepare.py", "--role", role,
                                         "--registry", registry, "--output", job))
                assert not (job / "cache").exists() and not (job / "cjpm.lock").exists()
                assert not (job / "cjpm-provenance.json").exists()
                return job

            def job_run(label, job, role, token, success=True):
                key = "CJREPO_PUBLISH_TOKEN" if role == "publisher" else "CJREPO_READ_TOKEN"
                other = "CJREPO_READ_TOKEN" if role == "publisher" else "CJREPO_PUBLISH_TOKEN"
                variables = dict(environment)
                variables[key] = token
                native_mount = (("--mount", f"type=bind,source={args.team_native.resolve()},target=/opt/native,readonly")
                                if args.team_native else ())
                if args.team_native and (args.team_native / "system").is_dir():
                    for path in sorted((args.team_native / "system").rglob("*")):
                        if path.is_file():
                            destination = "/" + path.relative_to(args.team_native / "system").as_posix()
                            native_mount += ("--mount", f"type=bind,source={path.resolve()},target={destination},readonly")
                command = ("docker", "run", "--rm", "--pull=never", "--name", "cjrepomesh-job-" + uuid.uuid4().hex[:16],
                           "--network", network, "--read-only", "--cap-drop", "ALL",
                           "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,mode=1777",
                           "--label", "com.docker.compose.project=" + project,
                           "--label", "io.cjrepomesh.distribution=" + image_tag,
                           "--mount", f"type=bind,source={args.team_sdk.resolve()},target=/opt/cangjie,readonly",
                           "--mount", f"type=bind,source={team_client.resolve()},target=/opt/client,readonly",
                           *native_mount,
                           "--mount", f"type=bind,source={job},target=/job", "--workdir", "/job",
                           "--env", "CJREPOMESH_CJPM=" + ("/opt/client/run.sh" if args.team_client_bundle else "/opt/client"),
                           "--env", key,
                           "--entrypoint", "/bin/bash", image_tag, "-ec",
                           'source /opt/cangjie/envsetup.sh; '
                           'export PATH="/opt/native/bin:$PATH" LD_LIBRARY_PATH="/opt/native/lib:$LD_LIBRARY_PATH"; '
                           'test -z "${' + other + ':-}"; bash run.sh')
                return run(label, command, success=success, variables=variables, timeout=180)

            publisher = workspace("publisher", "publisher")
            consumer = workspace("consumer", "consumer")
            passed("team-role-workspaces-created-without-secrets")
            job_run("team-publish", publisher, "publisher", credentials["CJREPO_PUBLISH_TOKEN"])
            index = json.loads((publisher / "target/meta-data.json").read_text())["index"]
            expected_sha = index["sha256sum"]
            assert index["organization"] == "company" and index["name"] == "teamhello"
            with tarfile.open(publisher / "target/teamhello-1.0.0.cjp") as archive:
                assert not any(Path(item.name).name in {"run.sh", "workspace.json", "cangjie-repo.toml", ".env"}
                               for item in archive.getmembers())
            passed("developer-container-publishes-real-private-package", archive_sha256=expected_sha)

            def check_consumer(job, result):
                assert "CjRepoMesh team 1.0.0: CI" in result.stdout
                entries = json.loads((job / "cjpm-provenance.json").read_text())["packages"]
                entry = next(item for item in entries if item["package"] == "company::teamhello")
                assert entry["version"] == "1.0.0" and entry["repository"] == "internal"
                assert entry["registry"] == registry and entry["sha256"] == expected_sha
                assert (job / "cjpm.lock").is_file()
                assert (job / "cache").is_dir() and (job / ".home").is_dir()

            result = job_run("team-consume", consumer, "consumer", credentials["CJREPO_READ_TOKEN"])
            check_consumer(consumer, result)
            passed("read-only-ci-compiles-and-runs-private-dependency", archive_sha256=expected_sha)
            repeated = workspace("independent-ci", "consumer")
            result = job_run("team-independent", repeated, "consumer", credentials["CJREPO_READ_TOKEN"])
            check_consumer(repeated, result)
            passed("independent-cold-ci-reproduces-source-and-checksum")
            failed_application = workspace("application-exit-seven", "consumer")
            source = failed_application / "src/main.cj"
            original = source.read_text(encoding="utf-8")
            assert original.count("return 0") == 1
            source.write_text(original.replace("return 0", "return 7"), encoding="utf-8")
            result = job_run("team-application-failed", failed_application, "consumer",
                             credentials["CJREPO_READ_TOKEN"], success=False)
            assert result.returncode == 7
            assert "CjRepoMesh team 1.0.0: CI" in result.stdout
            assert "Recorded resolution:" not in result.stdout
            assert (failed_application / "cjpm-provenance.json").is_file()
            passed("application-runtime-failure-preserves-nonzero-ci-exit")
            denied = workspace("wrong-read-token", "consumer")
            result = job_run("team-denied", denied, "consumer", "synthetic-wrong-read-token", success=False)
            assert "401" in result.stdout + result.stderr
            assert not (denied / "cjpm-provenance.json").exists()
            assert "CjRepoMesh team 1.0.0: CI" not in result.stdout
            passed("cold-ci-invalid-token-cannot-use-another-jobs-cache")
            unauthorized_publisher = workspace("read-only-publish-attempt", "publisher")
            result = job_run("team-publish-denied", unauthorized_publisher, "publisher",
                             credentials["CJREPO_READ_TOKEN"], success=False)
            assert "401" in result.stdout + result.stderr
            passed("read-token-cannot-publish-through-real-client")
            status, stored = request("/index/te/am/teamhello?organization=company", credentials["CJREPO_READ_TOKEN"])
            expect(status, 200)
            assert json.loads(stored.decode().strip())["sha256sum"] == expected_sha
            assert hashlib.sha256((installation / ".env").read_bytes()).hexdigest() == credential_sha
            if args.team_client_bundle:
                assert client_bundle_identity(args.team_client_bundle) == client_identity
            passed("failed-team-jobs-preserve-package-and-server-credentials")
    except (OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as failure:
        error = str(failure) or type(failure).__name__
        print("FAIL portable delivery: " + error, flush=True)
    finally:
        # Every project is freshly generated by this run; inspect ownership before
        # removing any container or volume, including failure remnants.
        for name, cwd in reversed(projects):
            try:
                containers = run("cleanup-list-" + name,
                    ("docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + name)).stdout.split()
                for identifier in containers:
                    item = json.loads(run("cleanup-inspect", ("docker", "inspect", identifier), log=False).stdout)[0]
                    labels = item["Config"]["Labels"]
                    assert labels.get("com.docker.compose.project") == name
                    assert labels.get("io.cjrepomesh.distribution") == image_tag
                    run("cleanup-container", ("docker", "rm", "-f", identifier))
                compose("cleanup-down-" + name, "down", cwd=cwd, name=name)
                volumes = run("cleanup-volumes-" + name, ("docker", "volume", "ls", "-q", "--filter",
                              "label=com.docker.compose.project=" + name)).stdout.split()
                for volume in volumes:
                    labels = json.loads(run("cleanup-volume-inspect", ("docker", "volume", "inspect", volume), log=False).stdout)[0]["Labels"]
                    assert labels.get("com.docker.compose.project") == name
                    assert labels.get("io.cjrepomesh.distribution") == image_tag
                    run("cleanup-volume", ("docker", "volume", "rm", volume))
            except (OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as failure:
                cleanup_errors.append(name + ": " + (str(failure) or type(failure).__name__))
        success = not error and not cleanup_errors and len(stages) == total
        summary = dict(success=success, passed=len(stages), total=total,
                       seconds=round(time.monotonic() - started, 2), stages=stages,
                       image=manifest["image"], error=error, cleanup_errors=cleanup_errors,
                       team_jobs=bool(args.team_sdk),
                       runtime_diagnostics=args.check_running,
                       team_client=client_identity,
                       limits=["Local receiver-directory simulation on the existing Docker engine, not a fresh host.",
                               ("Real Linux publisher and independent read-only consumer builds; no Windows Cangjie execution."
                                if args.team_sdk else "Real prebuilt CJP publish/read; no consumer build or Windows Cangjie execution."),
                               "No LAN/HTTPS, upgrade, disaster recovery or capacity acceptance."])
        (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Portable receiver: {len(stages)}/{total}; success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
