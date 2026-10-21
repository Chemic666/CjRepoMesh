#!/usr/bin/env python3
"""Prepare an isolated publisher or read-only CI example without reading secrets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit


def safe_registry(value: str) -> bool:
    try:
        url = urlsplit(value)
        port = url.port
        return (url.scheme in ("http", "https") and bool(url.hostname) and
                (port is None or 1 <= port <= 65535) and not url.username and not url.password and
                not any(char in value for char in ("?", "#", "\\")) and
                not any(char in url.netloc for char in ("@", "%")) and
                all(ord(char) > 32 and ord(char) != 127 for char in value))
    except ValueError:
        return False


def prepare(role: str, registry: str, output: Path) -> None:
    if not safe_registry(registry):
        raise ValueError("registry must be a credential-free HTTP(S) base address")
    if output.exists():
        raise FileExistsError("workspace already exists; use a new directory")
    source = Path(__file__).resolve().parent / role
    output.mkdir(parents=True, exist_ok=False)
    for name in ("cjpm.toml", "README.md", "run.sh"):
        shutil.copyfile(source / name, output / name)
    shutil.copytree(source / "src", output / "src")
    (output / ".home").mkdir()
    config = '[repository.cache]\npath = "cache"\n'
    if role == "publisher":
        config += '[repository.home]\nregistry = ' + json.dumps(registry) + '\n'
        config += 'token-env = "CJREPO_PUBLISH_TOKEN"\n'
    else:
        config += '[repository.internal]\nregistry = ' + json.dumps(registry) + '\n'
        config += 'token-env = "CJREPO_READ_TOKEN"\n'
        config += '[[route]]\nnamespace = "company::*"\nregistry = "internal"\nexclusive = true\n'
    (output / "cangjie-repo.toml").write_text(config, encoding="utf-8")
    (output / "workspace.json").write_text(json.dumps(dict(formatVersion=1, role=role,
        registry=registry, package="company::teamhello", version="1.0.0"), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("publisher", "consumer"))
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True, type=Path, help="new standalone workspace")
    args = parser.parse_args()
    try:
        prepare(args.role, args.registry, args.output.resolve())
        print(f"Prepared {args.role} workspace; load your SDK environment and run bash run.sh there.")
        print("Credentials are referenced by environment variable only; none were read or written.")
        return 0
    except (OSError, ValueError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
