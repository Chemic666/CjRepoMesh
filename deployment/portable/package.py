#!/usr/bin/env python3
"""Export an existing local server image as a source-free offline distribution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from verify import FILES, digest, docker, verify_bundle


def package(image: str, output: Path) -> dict:
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("output must be a new directory")
    info = json.loads(docker("image", "inspect", image))[0]
    if info["Os"] != "linux" or info["Architecture"] != "amd64":
        raise ValueError("this distribution currently supports Linux amd64 images only")
    identifier = info["Id"]
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier):
        raise ValueError("invalid local image identity")
    tag = "cjrepomesh-portable:sha256-" + identifier[7:]
    existing = subprocess.run(("docker", "image", "inspect", tag), capture_output=True, text=True)
    if existing.returncode == 0:
        if json.loads(existing.stdout)[0]["Id"] != identifier:
            raise ValueError("portable image tag already refers to another image")
    elif "no such image" not in existing.stderr.lower():
        raise RuntimeError("cannot check the portable image tag")
    server_sha = docker("run", "--rm", "--pull=never", "--network", "none", "--read-only",
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                        "--entrypoint", "sha256sum", identifier, "/usr/local/bin/cjrepo").split()[0]
    if not re.fullmatch(r"[a-f0-9]{64}", server_sha):
        raise ValueError("cannot identify the server binary")
    output.mkdir(parents=True, exist_ok=False)
    docker("image", "tag", identifier, tag)
    docker("image", "save", "--output", str(output / "image.tar"), tag, timeout=300)
    source = Path(__file__).resolve().parent
    for name in ("configure.py", "verify.py", "maintenance.py", "snapshot.py", "README.md"):
        shutil.copyfile(source / name, output / name)
    shutil.copyfile(source.parents[1] / "LICENSE", output / "LICENSE")
    (output / "compose.yaml").write_text(
        (source / "compose.yaml").read_text(encoding="utf-8").replace("@IMAGE@", tag), encoding="utf-8")
    manifest = dict(formatVersion=1, caConfiguration='pem-directory-v1', maintenance='cold-backup-v1',
                    restorePreflight='offline-inputs-v1',
                    snapshotSeedPreflight='offline-inputs-v1',
                    dependencySnapshot='approved-origins-v2',
                    createdAtUtc=datetime.now(timezone.utc).isoformat(),
                    image=dict(id=identifier, tag=tag, os="linux", architecture="amd64", serverSha256=server_sha),
                    files={name: dict(bytes=(output/name).stat().st_size, sha256=digest(output/name))
                           for name in sorted(FILES)})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_bundle(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already built, locally available server image")
    parser.add_argument("--output", required=True, type=Path, help="new distribution directory")
    args = parser.parse_args()
    try:
        output = args.output.absolute()
        manifest = package(args.image, output)
        print("PASS: offline bundle created at " + str(output))
        print("Image: " + manifest["image"]["id"])
        print("Manifest SHA-256: " + digest(output / "manifest.json"))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
