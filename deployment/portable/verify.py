#!/usr/bin/env python3
"""Verify a portable CjRepoMesh distribution before loading or configuring it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

FILES = {"image.tar", "compose.yaml", "configure.py", "verify.py", "README.md", "LICENSE"}


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
    if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != FILES:
        raise ValueError("unexpected bundle file list")
    image = manifest["image"]
    if (not re.fullmatch(r"sha256:[a-f0-9]{64}", image["id"]) or
            image["tag"] != "cjrepomesh-portable:sha256-" + image["id"][7:] or
            image["os"] != "linux" or image["architecture"] != "amd64" or
            not re.fullmatch(r"[a-f0-9]{64}", image["serverSha256"])):
        raise ValueError("unsupported bundle image identity or platform")
    for name in sorted(FILES):
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="also verify the already loaded image and server")
    args = parser.parse_args()
    try:
        manifest = verify_bundle(Path(__file__).absolute().parent, check_docker=args.docker)
        print("PASS: bundle files" + (", loaded image and server" if args.docker else ""))
        print("Image: " + manifest["image"]["id"])
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
