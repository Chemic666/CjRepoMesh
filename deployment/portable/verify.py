#!/usr/bin/env python3
"""Verify a portable CjRepoMesh distribution before loading or configuring it."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import re
import stat
import subprocess
import urllib.error
import urllib.request

LEGACY_FILES = {"image.tar", "compose.yaml", "configure.py", "verify.py", "README.md", "LICENSE"}
MAINTENANCE_FILES = LEGACY_FILES | {"maintenance.py"}
FILES = MAINTENANCE_FILES | {"snapshot.py"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def regular_file(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)


def docker(*arguments: str, timeout: int = 120) -> str:
    result = subprocess.run(("docker", *arguments), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"docker {arguments[0]} failed; check the engine and image locally")
    return result.stdout


def verify_bundle(root: Path, *, check_docker: bool = False) -> dict:
    if not regular_file(root / "manifest.json"):
        raise ValueError("manifest must be a regular file")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be an object")
    if type(manifest.get("formatVersion")) is not int or manifest["formatVersion"] != 1:
        raise ValueError("unsupported bundle manifest version")
    if manifest.get('caConfiguration') not in (None, 'pem-directory-v1'):
        raise ValueError('unsupported bundle CA configuration')
    if manifest.get('maintenance') not in (None, 'cold-backup-v1'):
        raise ValueError('unsupported bundle maintenance capability')
    if manifest.get('restorePreflight') not in (None, 'offline-inputs-v1'):
        raise ValueError('unsupported bundle restore preflight capability')
    if manifest.get('restorePreflight') is not None and manifest.get('maintenance') != 'cold-backup-v1':
        raise ValueError('restore preflight requires the maintenance capability')
    if manifest.get('snapshotSeedPreflight') not in (None, 'offline-inputs-v1'):
        raise ValueError('unsupported snapshot seed preflight capability')
    if manifest.get('snapshotSeedPreflight') is not None and (
            manifest.get('dependencySnapshot') not in ('approved-set-v1', 'approved-origins-v2') or
            manifest.get('maintenance') != 'cold-backup-v1' or manifest.get('caConfiguration') != 'pem-directory-v1'):
        raise ValueError('snapshot seed preflight requires snapshot, maintenance and CA configuration capabilities')
    if manifest.get('dependencySnapshot') not in (None, 'approved-set-v1', 'approved-origins-v2'):
        raise ValueError('unsupported bundle dependency snapshot capability')
    if manifest.get('dependencySnapshot') in ('approved-set-v1', 'approved-origins-v2'):
        if manifest.get('maintenance') != 'cold-backup-v1':
            raise ValueError('dependency snapshot requires the maintenance capability')
        expected_files = FILES
    else:
        expected_files = MAINTENANCE_FILES if manifest.get('maintenance') == 'cold-backup-v1' else LEGACY_FILES
    if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != expected_files:
        raise ValueError("unexpected bundle file list")
    image = manifest["image"]
    if (not re.fullmatch(r"sha256:[a-f0-9]{64}", image["id"]) or
            image["tag"] != "cjrepomesh-portable:sha256-" + image["id"][7:] or
            image["os"] != "linux" or image["architecture"] != "amd64" or
            not re.fullmatch(r"[a-f0-9]{64}", image["serverSha256"])):
        raise ValueError("unsupported bundle image identity or platform")
    for name in sorted(expected_files):
        path = root / name
        entry = manifest["files"][name]
        if (not isinstance(entry, dict) or not regular_file(path) or type(entry.get("bytes")) is not int or
                entry["bytes"] != path.stat().st_size or entry.get("sha256") != digest(path)):
            raise ValueError(f"bundle integrity check failed: {name}")
    if check_docker:
        actual = json.loads(docker("image", "inspect", image["tag"]))[0]
        if (actual["Id"] != image["id"] or actual["Os"] != image["os"] or
                actual["Architecture"] != image["architecture"]):
            raise ValueError("loaded Docker image identity does not match the manifest")
        observed = docker("run", "--rm", "--pull=never", "--network", "none", "--read-only",
                          "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                          "--entrypoint", "sha256sum", image["tag"], "/usr/local/bin/cjrepo").split()[0]
        if observed != image["serverSha256"]:
            raise ValueError("loaded server binary does not match the manifest")
    return manifest


def runtime_configuration(root: Path) -> tuple[str, int]:
    path = root / ".env"
    if not regular_file(path):
        raise ValueError("runtime configuration must be a regular file")
    values = {}
    # Collect only public deployment identity; no token values are returned.
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            key, separator, value = line.strip().partition("=")
            if key not in {"COMPOSE_PROJECT_NAME", "CJREPO_HOST_PORT"}:
                continue
            if not separator or key in values:
                raise ValueError("duplicate or invalid runtime configuration")
            values[key] = value
    project, port = values.get("COMPOSE_PROJECT_NAME", ""), values.get("CJREPO_HOST_PORT", "")
    if (not re.fullmatch(r"cjrepomesh-[a-f0-9]{16}", project) or
            not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535):
        raise ValueError("invalid runtime configuration; retain the original project and port")
    return project, int(port)


def check_running_container(item: dict, image: dict, project: str, port: int) -> None:
    labels = item["Config"].get("Labels") or {}
    if (item["Image"] != image["id"] or labels.get("com.docker.compose.project") != project or
            labels.get("com.docker.compose.service") != "cjrepo" or
            labels.get("io.cjrepomesh.distribution") != image["tag"]):
        raise ValueError("running container identity does not match this deployment")
    if item["State"].get("Running") is not True or item["State"].get("Health", {}).get("Status") != "healthy":
        raise ValueError("deployment is not running and healthy; wait for startup or inspect it locally")
    host = item["HostConfig"]
    if (item["Config"]["User"] != "10001:10001" or host["ReadonlyRootfs"] is not True or
            host.get("Privileged", False) is not False or host.get("CapAdd") or
            "ALL" not in (host.get("CapDrop") or []) or
            "no-new-privileges:true" not in (host.get("SecurityOpt") or [])):
        raise ValueError("running container constraints do not match the distribution")
    expected = {"8080/tcp": [dict(HostIp="127.0.0.1", HostPort=str(port))]}
    if item["NetworkSettings"]["Ports"] != expected:
        raise ValueError("running port binding does not match the configured loopback endpoint")
    mounts = [mount for mount in item["Mounts"] if mount["Destination"] == "/var/lib/cjrepo"]
    if (len(mounts) != 1 or mounts[0]["Type"] != "volume" or
            mounts[0]["Name"] != project + "_cjrepo-data" or mounts[0]["RW"] is not True):
        raise ValueError("running data volume does not match this deployment")
    environment = dict(line.split("=", 1) for line in (item["Config"].get("Env") or []))
    if not environment.get("CJREPO_READ_TOKEN") or not environment.get("CJREPO_PUBLISH_TOKEN"):
        raise ValueError("running private credentials are missing")


def check_running_trust(root: Path, item: dict, identifier: str, *, required: bool = False) -> None:
    environment = dict(line.split('=', 1) for line in (item['Config'].get('Env') or []))
    values = []
    with (root/'.env').open(encoding='utf-8') as stream:
        for line in stream:
            key, separator, value = line.strip().partition('=')
            if key == 'CJREPO_CA_SHA256':
                if not separator:
                    raise ValueError('invalid CA configuration')
                values.append(value)
    # Older seven-file bundles did not declare a trust directory.
    if not required and not values and 'SSL_CERT_FILE' not in environment:
        return
    if len(values) != 1 or (values[0] and not re.fullmatch(r'[a-f0-9]{64}', values[0])):
        raise ValueError('missing, duplicate or invalid CA configuration')
    expected = values[0]
    trust = root/'trust'
    info = trust.lstat()
    if not stat.S_ISDIR(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('CA trust directory must be an ordinary directory')
    names = ['ca.pem'] if expected else []
    if sorted(path.name for path in trust.iterdir()) != names:
        raise ValueError('unexpected CA trust directory contents')
    if expected and (not regular_file(trust/'ca.pem') or digest(trust/'ca.pem') != expected):
        raise ValueError('host CA does not match the configured digest')
    mounts = [mount for mount in item['Mounts'] if mount['Destination'] == '/run/cjrepo-trust']
    if (len(mounts) != 1 or mounts[0]['Type'] != 'bind' or mounts[0]['RW'] is not False or
            environment.get('SSL_CERT_FILE') != '/run/cjrepo-trust/ca.pem' or
            environment.get('CJREPO_CA_SHA256') != expected):
        raise ValueError('running CA mount or configuration does not match this deployment')
    observed = docker('exec', identifier, '/bin/ls', '-A', '/run/cjrepo-trust').splitlines()
    if sorted(observed) != names:
        raise ValueError('container CA directory does not match this deployment')
    if expected:
        observed = docker('exec', identifier, 'sha256sum', '/run/cjrepo-trust/ca.pem').split()
        if not observed or observed[0] != expected:
            raise ValueError('container CA does not match the configured digest')


def check_running_credentials(item: dict, effective: dict) -> None:
    """Compare resolved Compose values in memory; never include them in errors."""
    message = 'running credentials do not match the effective Compose configuration'
    if not isinstance(effective, dict):
        raise ValueError(message)
    entries = item['Config'].get('Env') or []
    for key in ('CJREPO_READ_TOKEN', 'CJREPO_PUBLISH_TOKEN'):
        expected = effective.get(key)
        observed = [entry[len(key)+1:] for entry in entries
                    if isinstance(entry, str) and entry.startswith(key+'=')]
        if (not isinstance(expected, str) or not expected or len(observed) != 1 or
                not hmac.compare_digest(expected.encode('utf-8'), observed[0].encode('utf-8'))):
            raise ValueError(message)


def verify_running(root: Path, manifest: dict) -> None:
    project, port = runtime_configuration(root)
    identifiers = docker("compose", "--project-directory", str(root), "-p", project,
        "-f", str(root / "compose.yaml"), "--env-file", str(root / ".env"),
        "ps", "--all", "-q", "cjrepo").split()
    if len(identifiers) != 1 or not re.fullmatch(r"[a-f0-9]{64}", identifiers[0]):
        raise ValueError("expected exactly one deployment container; start or inspect this project locally")
    identifier = identifiers[0]
    inspected = json.loads(docker("inspect", identifier))
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise ValueError("cannot identify the running deployment")
    check_running_container(inspected[0], manifest["image"], project, port)
    # Let Compose resolve env_file quoting/interpolation using the same explicit
    # files as startup. Do not persist or print config output: it holds secrets.
    configuration = json.loads(docker('compose', '--project-directory', str(root), '-p', project,
        '-f', str(root/'compose.yaml'), '--env-file', str(root/'.env'), 'config', '--format', 'json'))
    check_running_credentials(inspected[0], configuration['services']['cjrepo'].get('environment'))
    check_running_trust(root, inspected[0], identifier,
                        required=manifest.get('caConfiguration') == 'pem-directory-v1')
    volume = json.loads(docker("volume", "inspect", project + "_cjrepo-data"))
    if not isinstance(volume, list) or len(volume) != 1:
        raise ValueError("cannot identify the persistent volume")
    labels = volume[0].get("Labels") or {}
    if (labels.get("com.docker.compose.project") != project or
            labels.get("io.cjrepomesh.distribution") != manifest["image"]["tag"]):
        raise ValueError("persistent volume identity does not match this deployment")
    observed = docker("exec", identifier, "sha256sum", "/usr/local/bin/cjrepo").split()
    if not observed or observed[0] != manifest["image"]["serverSha256"]:
        raise ValueError("running server binary does not match the manifest")
    class LocalHealthOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalHealthOnly())
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                raise ValueError("unexpected health response")
            health = json.loads(body)
            if not isinstance(health, dict) or health.get("status") != "ok" or health.get("service") != "cjrepo":
                raise ValueError("unexpected health response")
    except (OSError, ValueError) as error:
        if isinstance(error, urllib.error.HTTPError):
            error.close()
        raise ValueError("local registry health check failed; inspect this deployment locally") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--docker", action="store_true", help="also verify the already loaded image and server")
    mode.add_argument("--running", action="store_true", help="read-only diagnosis of this configured running deployment")
    args = parser.parse_args()
    try:
        root = Path(__file__).absolute().parent
        manifest = verify_bundle(root, check_docker=args.docker)
        if args.running:
            verify_running(root, manifest)
        print("PASS: bundle files" + (", running deployment" if args.running else
                                      ", loaded image and server" if args.docker else ""))
        print("Image: " + manifest["image"]["id"])
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
