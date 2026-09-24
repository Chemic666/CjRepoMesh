#!/usr/bin/env python3
"""Verify isolated Docker private-registry auth and persistence across recreation."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


DOCKER_ROOT = Path(__file__).resolve().parents[1] / "deployment" / "docker"


def compose(project: str, env_file: Path, env: dict[str, str], *args: str) -> None:
    command = [
        "docker", "compose", "-p", project, "--project-directory", str(DOCKER_ROOT),
        "--env-file", str(env_file), *args,
    ]
    result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Docker Compose {args[0]} failed: {result.stderr.strip()}")


def request(base: str, path: str, *, token: str = "", body: bytes | None = None) -> tuple[int, bytes]:
    headers = {"Authorization": token} if token else {}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(base + path, data=body, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def expect(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {actual}")


def healthy(base: str) -> None:
    for _ in range(60):
        try:
            status, body = request(base, "/health")
            if status == 200 and json.loads(body).get("service") == "cjrepo":
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise TimeoutError("isolated CjRepo container did not become healthy")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main() -> None:
    project = "cjrepomeshverify" + secrets.token_hex(5)
    if not project.startswith("cjrepomeshverify") or len(project) != 26:
        raise RuntimeError("unexpected temporary Compose project name")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    publish_token = secrets.token_urlsafe(32)
    read_token = secrets.token_urlsafe(32)
    package = "meshverify" + secrets.token_hex(4)
    version = "1.0.0"
    artifact = b"CjRepoMesh isolated persistence probe\n" + secrets.token_bytes(16)
    checksum = hashlib.sha256(artifact).hexdigest()
    index = {
        "name": package, "version": version, "organization": "", "sha256sum": checksum,
    }
    metadata = {
        "name": package, "version": version, "organization": "", "index": index,
    }
    metadata_bytes = json.dumps(metadata, separators=(",", ":")).encode()
    frame = b"\x01" + struct.pack("<I", len(metadata_bytes)) + metadata_bytes
    frame += b"\x01" + struct.pack("<I", len(artifact)) + artifact
    index_path = f"/index/{package[:2]}/{package[2:4]}/{package}"
    artifact_path = f"/pkg/{package}/{version}"
    env = {key: value for key, value in os.environ.items() if not key.startswith("CJREPO_")}
    env.update({
        "CJREPO_HOST_PORT": str(port),
        "CJREPO_PUBLISH_TOKEN": publish_token,
        "CJREPO_READ_TOKEN": read_token,
        "CJREPO_UPSTREAM": "",
        "CJREPO_UPSTREAM_TOKEN": "",
        "CJREPO_PROXY_TTL_SECONDS": "86400",
    })
    with tempfile.TemporaryDirectory(prefix="cjrepomesh-docker-verify-") as temporary:
        # Use an empty env file: no credentials are persisted or echoed by this test.
        env_file = Path(temporary) / "compose.env"
        env_file.touch()
        try:
            compose(project, env_file, env, "up", "-d", "--no-build")
            healthy(base)
            expect(request(base, index_path)[0], 401, "private index")
            expect(request(base, artifact_path)[0], 401, "private artifact")
            expect(request(base, f"/pkg/{package}", body=frame)[0], 401, "anonymous publish")
            expect(request(base, f"/pkg/{package}", token=publish_token, body=frame)[0],
                   200, "authorized publish")
            expect(request(base, index_path, token=read_token)[0], 200, "published index")
            status, downloaded = request(base, artifact_path, token=read_token)
            expect(status, 200, "published artifact")
            if downloaded != artifact:
                raise AssertionError("published artifact differs from uploaded bytes")
            for path in (index_path, artifact_path):
                expect(request(base, path + "?organization=other")[0], 401,
                       "unauthorized organization query")
                expect(request(base, path + "?organization=other", token=read_token)[0], 400,
                       "organization query must not alias default storage")
            expect(request(base, f"/pkg/{package}?organization=other",
                           token=publish_token, body=frame)[0], 400,
                   "organization publish must not alias default storage")
            compose(project, env_file, env, "up", "-d", "--no-build", "--force-recreate")
            healthy(base)
            expect(request(base, index_path)[0], 401, "private index after recreation")
            expect(request(base, artifact_path)[0], 401, "private artifact after recreation")
            expect(request(base, index_path, token=read_token)[0], 200, "persisted index")
            status, downloaded = request(base, artifact_path, token=read_token)
            expect(status, 200, "persisted artifact")
            expect(request(base, artifact_path + "?organization=other", token=read_token)[0],
                   400, "organization query after recreation")
            if hashlib.sha256(downloaded).hexdigest() != checksum:
                raise AssertionError("persisted artifact SHA-256 mismatch")
            expect(request(base, f"/pkg/{package}", token=publish_token, body=frame)[0],
                   409, "duplicate publish after recreation")
            print("PASS: private auth, namespace isolation, publish, persistence, duplicate 409")
        finally:
            # The generated project name scopes this removal to this test's container and volume.
            compose(project, env_file, env, "down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
