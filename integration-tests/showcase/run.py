#!/usr/bin/env python3
"""Reproduce an isolated enterprise dependency workflow using real Cangjie packages."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import urllib.error
import urllib.request
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (  # noqa: E402
    HttpResult, ManagedProcesses, TestFailure, assert_contains, assert_equal, assert_ports_available,
    platform_executable, publish_frame, remove_within, run_command,
    sha256, wait_for_ports_closed,
)


def http_request(method: str, url: str, *, headers=None, body=None, timeout=10.0) -> HttpResult:
    # This scenario owns every HTTP endpoint; never consult host proxy settings.
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read())
    except urllib.error.HTTPError as error:
        return HttpResult(error.code, error.read())
    except OSError as error:
        raise TestFailure(f"Owned HTTP request failed: {error}") from error


def wait_for_health(port: int) -> None:
    for _ in range(50):
        try:
            result = http_request("GET", f"http://127.0.0.1:{port}/health", timeout=1)
            if result.status == 200 and json.loads(result.body).get("status") == "ok":
                return
        except (TestFailure, ValueError):
            pass
        time.sleep(0.1)
    raise TestFailure(f"Owned registry on port {port} did not become healthy")


class AuditedHTTP:
    """An owned synthetic upstream or transparent GET gateway; never log headers."""

    def __init__(self, port: int, *, packages=(), target: str = ""):
        self.requests: list[str] = []
        self.errors: list[dict] = []
        self.closed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:
                owner.requests.append(self.path)
                if target:
                    try:
                        response = http_request("GET", target + self.path,
                            headers={"Authorization": self.headers.get("Authorization", "")})
                        status, body = response.status, response.body
                    except TestFailure:
                        status, body = 502, b"owned gateway target unavailable"
                elif self.headers.get("Authorization") != "upstream-read-fixture":
                    status, body = 401, b"authentication failed"
                else:
                    parsed = urlsplit(self.path)
                    organization = parse_qs(parsed.query).get("organization", [""])[0]
                    matches = [item for item in packages if item["organization"] == organization]
                    if parsed.path.startswith("/index/"):
                        name = parsed.path.rsplit("/", 1)[-1]
                        rows = [item["index"] for item in matches if item["name"] == name]
                        status = 200 if rows else 404
                        body = ("\n".join(json.dumps(row) for row in rows) + "\n").encode() if rows else b""
                    else:
                        match = next((item for item in matches
                            if parsed.path == f"/pkg/{item['name']}/{item['version']}"), None)
                        status, body = (200, match["artifact"]) if match else (404, b"")
                self.send_response(status)
                if status >= 500:
                    owner.errors.append(dict(path=self.path, status=status,
                                             message=body.decode("utf-8", errors="replace")[:2048]))
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.worker.start()

    def close(self) -> None:
        if not self.closed:
            self.server.shutdown()
            self.server.server_close()
            self.worker.join(timeout=5)
            self.closed = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjpm", type=Path, required=True)
    parser.add_argument("--server", type=Path,
                        default=platform_executable(TESTS.parent / "server/target/release/bin/main"))
    parser.add_argument("--port", type=int, default=39750, help="first of five consecutive loopback ports")
    parser.add_argument("--output-dir", type=Path, help="new report directory; defaults under ignored .tmp")
    args = parser.parse_args()
    client, server = args.cjpm.resolve(), args.server.resolve()
    if not client.is_file() or not server.is_file():
        parser.error("build the enhanced cjpm and server first; load the matching SDK/stdx environment")
    if not 1 <= args.port <= 65531:
        parser.error("--port must leave room for five consecutive ports")
    ports = tuple(range(args.port, args.port + 5))
    assert_ports_available(ports)
    suffix = uuid.uuid4().hex
    parent = TESTS / ".tmp"
    root = parent / ("enterprise-run-" + suffix)
    report = (args.output_dir or parent / ("enterprise-report-" + suffix)).resolve()
    report.mkdir(parents=True, exist_ok=False)
    logs = report / "logs"
    logs.mkdir()
    root.mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("CJREPO_", "CJREPOMESH_")) and key != "CJPM_CONFIG"}
    environment.update(HOME=str(home), USERPROFILE=str(home),
        CJREPOMESH_SHOWCASE_PRIVATE_TOKEN="private-read-fixture",
        CJREPOMESH_SHOWCASE_PUBLIC_TOKEN="proxy-read-fixture",
        CJREPOMESH_SHOWCASE_REPLICA_TOKEN="replica-read-fixture")
    upstream_url, private_url, proxy_url, replica_url, public_url = (
        f"http://127.0.0.1:{port}" for port in ports)
    stages = []
    actors: list[AuditedHTTP] = []
    success = False
    error = ""
    started = time.monotonic()
    inputs = dict(platform=sys.platform, cjpm_sha256=sha256(client), server_sha256=sha256(server),
                  runner_sha256=sha256(Path(__file__)), harness_sha256=sha256(TESTS / "lib/harness.py"))
    (report / "inputs.json").write_text(json.dumps(inputs, indent=2), encoding="utf-8")

    def passed(name: str, description: str, **facts) -> None:
        stages.append(dict(name=name, status="PASS", description=description, facts=facts))
        print(f"PASS {len(stages)}/7 {name}: {description}", flush=True)

    def fixture(relative: str, label: str, *, combined: bool = False) -> Path:
        destination = root / label
        destination.mkdir()
        for name in ("cjpm.toml", "README.md", "src"):
            source = TESTS / relative / name
            if source.is_dir():
                shutil.copytree(source, destination / name)
            elif source.is_file():
                shutil.copyfile(source, destination / name)
        if combined:
            config = destination / "cjpm.toml"
            config.write_text(config.read_text(encoding="utf-8") + '\nmeshdep = "[1.0.0, 3.0.0)"\n', encoding="utf-8")
            main_file = destination / "src/main.cj"
            source = main_file.read_text(encoding="utf-8")
            source = source.replace("import company::auth.*", "import company::auth.*\nimport meshdep.*")
            source = source.replace("println(authRegistryMarker())", "println(authRegistryMarker())\n    println(registryMarker())")
            main_file.write_text(source, encoding="utf-8")
        (destination / "cangjie-repo.toml").write_text(
            f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "{upstream_url}"\n', encoding="utf-8")
        return destination

    def command(label: str, argv, *, cwd: Path, env=None, expect_success=True):
        # Save failed output as well; a failure must remain reviewable.
        try:
            result = run_command(argv, cwd=cwd, env=env or environment, timeout=90,
                                 expect_success=expect_success)
        except TestFailure as failure:
            (logs / (label + ".log")).write_text(str(failure), encoding="utf-8")
            raise
        (logs / (label + ".log")).write_text(result.output, encoding="utf-8")
        return result

    def bundle(relative: str, label: str) -> dict:
        package = fixture(relative, label)
        command("bundle-" + label, (client, "bundle"), cwd=package)
        metadata = (package / "target/meta-data.json").read_bytes()
        data = json.loads(metadata)
        archives = list((package / "target").glob("*.cjp"))
        assert_equal(len(archives), 1, label="one real bundled archive")
        artifact = archives[0].read_bytes()
        checksum = hashlib.sha256(artifact).hexdigest()
        assert_equal(checksum, data["index"]["sha256sum"], label="real archive digest")
        return dict(name=data["name"], organization=data["organization"], version=data["version"],
                    index=data["index"], checksum=checksum, artifact=artifact,
                    frame=publish_frame(metadata, artifact))

    def repositories(app: Path, *, exclusive: bool = True, replica: bool = False) -> None:
        text = '[repository.cache]\npath = "cache"\n'
        if replica:
            text += f'[repository.home]\nregistry = "{replica_url}"\ntoken-env = "CJREPOMESH_SHOWCASE_REPLICA_TOKEN"\n'
        else:
            text += (f'[repository.private]\nregistry = "{private_url}"\npriority = 100\n'
                     'token-env = "CJREPOMESH_SHOWCASE_PRIVATE_TOKEN"\n'
                     f'[repository.public]\nregistry = "{public_url}"\npriority = 10\n'
                     'token-env = "CJREPOMESH_SHOWCASE_PUBLIC_TOKEN"\n')
            if exclusive:
                text += '[[route]]\nnamespace = "company::*"\nregistry = "private"\nexclusive = true\n'
        (app / "cangjie-repo.toml").write_text(text, encoding="utf-8")

    def app(label: str, *, exclusive=True, replica=False, combined=True) -> Path:
        destination = fixture("multirepo/app-namespace", label, combined=combined)
        repositories(destination, exclusive=exclusive, replica=replica)
        assert_equal((destination / "cache").exists(), False, label="fresh project cache")
        assert_equal((destination / "target").exists(), False, label="fresh build output")
        assert_equal((destination / "cjpm.lock").exists(), False, label="fresh lockfile")
        return destination

    def sources(app: Path, packages: list[tuple[dict, str, str]]) -> list[dict]:
        document = json.loads((app / "cjpm-provenance.json").read_text(encoding="utf-8"))
        rows = document["packages"]
        assert_equal(len(rows), len(packages), label="complete recorded dependency set")
        for package, repository, address in packages:
            full_name = (package["organization"] + "::" if package["organization"] else "") + package["name"]
            selected = [row for row in rows if row["package"] == full_name]
            assert_equal(len(selected), 1, label="one recorded source per package")
            for field, expected in (("version", package["version"]), ("repository", repository),
                                    ("registry", address), ("sha256", package["checksum"])):
                assert_equal(selected[0][field], expected, label="recorded " + field)
        # Keep registry identity by role in the public summary, without machine paths.
        return [{key: row[key] for key in ("package", "version", "repository", "sha256")} for row in rows]

    try:
        high = bundle("multirepo/packages/meshdep-v1-high", "internal-meshdep-v1")
        low = bundle("multirepo/packages/meshdep-v1-low", "public-meshdep-v1")
        latest = bundle("multirepo/packages/meshdep-v2-low", "public-meshdep-v2")
        trusted = bundle("multirepo/packages/company-auth-v1-private", "internal-auth-v1")
        adversarial = bundle("multirepo/packages/company-auth-v9-public", "public-auth-v9")
        (report / "artifacts.json").write_text(json.dumps([
            {key: item[key] for key in ("name", "version", "organization", "checksum")}
            for item in (high, low, latest, trusted, adversarial)], indent=2), encoding="utf-8")
        upstream = AuditedHTTP(ports[0], packages=(low, latest, adversarial))
        actors.append(upstream)
        with ManagedProcesses() as processes:
            def start(label: str, port: int, *, read: str, publish: str, upstream_address=""):
                variables = dict(environment, CJREPO_ADDRESS="127.0.0.1", CJREPO_PORT=str(port),
                    CJREPO_STORAGE=str(root / (label + "-storage")), CJREPO_READ_TOKEN=read,
                    CJREPO_PUBLISH_TOKEN=publish, CJREPO_UPSTREAM=upstream_address,
                    CJREPO_UPSTREAM_TOKEN="upstream-read-fixture", CJREPO_PROXY_TTL_SECONDS="86400")
                process = processes.start((server,), cwd=root, env=variables,
                                          output_path=logs / (label + "-server.log"))
                wait_for_health(port)
                return process

            private = start("private", ports[1], read="private-read-fixture", publish="private-publish-fixture")
            proxy = start("proxy", ports[2], read="proxy-read-fixture", publish="proxy-publish-fixture",
                          upstream_address=upstream_url)
            replica = start("replica", ports[3], read="replica-read-fixture", publish="replica-publish-fixture")
            gateway = AuditedHTTP(ports[4], target=proxy_url)
            actors.append(gateway)
            def publish(package: dict) -> None:
                query = "?organization=" + package["organization"] if package["organization"] else ""
                result = http_request("POST", private_url + "/pkg/" + package["name"] + query,
                    headers={"Authorization": "private-publish-fixture"}, body=package["frame"])
                assert_equal(result.status, 200, label="publish internal package")

            # Different package locks still share filesystem ancestors.
            with ThreadPoolExecutor(max_workers=2) as publisher:
                list(publisher.map(publish, (high, trusted)))

            control = app("unrestricted-control", exclusive=False)
            result = command("01-unrestricted-control", (client, "run"), cwd=control)
            assert_contains(result.output, "public-9.0.0")
            assert_contains(result.output, "low-2.0.0")
            control_sources = sources(control, [(adversarial, "public", public_url), (latest, "public", public_url)])
            passed("unrestricted-control", "Without an exclusive route, the compatible public auth 9.0.0 is selected.",
                   client="same enhanced client; this is a policy control, not the official binary", sources=control_sources)

            before = len(gateway.requests)
            protected = app("protected-online")
            result = command("02-protected-online", (client, "run"), cwd=protected)
            assert_contains(result.output, "private-1.0.0")
            assert_contains(result.output, "low-2.0.0")
            assert_equal(any("organization=company" in path for path in gateway.requests[before:]), False,
                         label="protected private dependency never reaches public gateway, including cache hits")
            recorded = sources(protected, [(trusted, "private", private_url), (latest, "public", public_url)])
            passed("protected-online", "Exclusive routing selects internal auth 1.0.0; the solver still selects public meshdep 2.0.0.",
                   public_private_namespace_requests=0, sources=recorded)

            before = len(gateway.requests)
            denied = app("authentication-denied", combined=False)
            denied_env = dict(environment, CJREPOMESH_SHOWCASE_PRIVATE_TOKEN="wrong-fixture-token")
            result = command("03-authentication-denied", (client, "build"), cwd=denied,
                             env=denied_env, expect_success=False)
            assert_contains(result.output, "status 401")
            assert_equal(len(gateway.requests), before, label="401 must not fall back to public repository")
            assert_equal((denied / "cjpm-provenance.json").exists(), False, label="no successful provenance on failed build")
            passed("authentication-denied", "An invalid internal read token stops the build, even with public auth already cached.",
                   expected_build_failure=True, public_requests=0)

            upstream.close()
            wait_for_ports_closed((ports[0],))
            disconnected = app("fresh-cache-offline-upstream")
            result = command("04-upstream-offline", (client, "run"), cwd=disconnected)
            assert_contains(result.output, "private-1.0.0")
            assert_contains(result.output, "low-2.0.0")
            sources(disconnected, [(trusted, "private", private_url), (latest, "public", public_url)])
            passed("upstream-offline", "A fresh client cache builds using the private registry and the verified proxy cache after upstream shutdown.",
                   upstream_stopped=True, fresh_client_cache=True)

            for label, source_url, package, token in (
                ("public", public_url, latest, "proxy-read-fixture"),
                ("private", private_url, trusted, "private-read-fixture"),
            ):
                full_name = (package["organization"] + "::" if package["organization"] else "") + package["name"]
                sync_env = dict(environment, CJREPO_UPSTREAM_TOKEN=token,
                    CJREPO_SYNC_DESTINATION_TOKEN="replica-publish-fixture",
                    CJREPO_SYNC_DESTINATION_READ_TOKEN="replica-read-fixture")
                argv = (server, "sync", source_url, replica_url, full_name, package["version"])
                first = command("05-sync-" + label, argv, cwd=root, env=sync_env)
                assert_contains(first.output, "result=SYNCED")
                again = command("05-sync-again-" + label, argv, cwd=root, env=sync_env)
                assert_contains(again.output, "result=SKIP")
                query = "?organization=" + package["organization"] if package["organization"] else ""
                artifact_url = replica_url + f"/pkg/{package['name']}/{package['version']}" + query
                assert_equal(http_request("GET", artifact_url).status, 401, label="replica stays private")
                copied = http_request("GET", artifact_url, headers={"Authorization": "replica-read-fixture"})
                assert_equal(copied.status, 200, label="replica artifact available")
                assert_equal(copied.body, package["artifact"], label="replica contains the real source archive")
            passed("sync-replica", "Public and internal organization packages synchronize to one private replica; reruns are verified SKIP.",
                   packages=2, repeated_sync="SKIP", archive_bytes_verified=True)

            processes.stop(private)
            processes.stop(proxy)
            gateway.close()
            wait_for_ports_closed((ports[1], ports[2], ports[4]))
            independent = app("replica-independent", replica=True)
            result = command("06-replica-independent", (client, "run"), cwd=independent)
            assert_contains(result.output, "private-1.0.0")
            assert_contains(result.output, "low-2.0.0")
            replica_sources = sources(independent, [(trusted, "home", replica_url), (latest, "home", replica_url)])
            passed("replica-independent", "Another fresh client builds using only the replica after both source registries are stopped.",
                   all_sources_stopped=True, fresh_client_cache=True, sources=replica_sources)

            processes.stop(replica)
            wait_for_ports_closed(ports)
            previous = sha256(independent / "cjpm-provenance.json")
            for full_name, package in (("company::auth", trusted), ("meshdep", latest)):
                result = command("07-recorded-" + package["name"],
                    (client, "repo", "explain", full_name, "--recorded"), cwd=independent)
                assert_contains(result.output, "Recorded resolution:")
                for field, value in (("package", full_name), ("version", package["version"]),
                                     ("repository", "home"), ("registry", replica_url)):
                    assert_contains(result.output, f"  {field}: {value}\n")
                assert_contains(result.output, "sha256:" + package["checksum"])
            assert_equal(sha256(independent / "cjpm-provenance.json"), previous, label="offline explain does not modify provenance")
            passed("offline-explain", "Recorded versions and SHA-256 remain explainable with every registry stopped.",
                   all_registry_ports_closed=True, provenance_unchanged=True)
        success = True
    except (TestFailure, OSError, ValueError, KeyError) as failure:
        error = str(failure)
        print("FAIL enterprise scenario: " + error, flush=True)
    finally:
        for actor in reversed(actors):
            actor.close()
        if actors:
            (report / "upstream-requests.json").write_text(json.dumps(actors[0].requests, indent=2), encoding="utf-8")
        if len(actors) > 1:
            (report / "public-gateway-requests.json").write_text(json.dumps(actors[1].requests, indent=2), encoding="utf-8")
            (report / "public-gateway-errors.json").write_text(json.dumps(actors[1].errors, indent=2), encoding="utf-8")
        result = dict(synthetic_local_scenario=True, success=success, passed_stages=len(stages), total_stages=7,
            seconds=round(time.monotonic() - started, 2), inputs=inputs, stages=stages, error=error,
            boundaries=["Not an official Maple test or an official-client comparison.",
                        "The upstream is an owned HTTP fixture serving real cjpm archives.",
                        "Offline means the specified source services are stopped, not a disconnected operating system.",
                        "SDK/stdx and an already built enhanced client/server are prerequisites."])
        (report / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        lines = ["# CjRepoMesh enterprise scenario", "", "Isolated local fixtures; real cjpm archives and builds.", "",
                 f"Result: {'PASS' if success else 'FAIL'} ({len(stages)}/7 stages).", "",
                 "| Stage | Verified behavior |", "| --- | --- |"]
        lines += [f"| {item['name']} | {item['description']} |" for item in stages]
        lines += ["", "Runtime identities:", "", f"- Client SHA-256: `{inputs['cjpm_sha256']}`",
                  f"- Server SHA-256: `{inputs['server_sha256']}`", "", "Scope:", ""]
        lines += ["- " + boundary for boundary in result["boundaries"]]
        if error:
            lines += ["", "The run failed. Inspect the retained local logs and fixture directory."]
        (report / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if success:
            remove_within(root, (parent,))
        else:
            print(f"Failure fixtures retained: {root}", flush=True)
    print(f"Enterprise scenario: {len(stages)}/7; success={success}; report: {report}", flush=True)
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
