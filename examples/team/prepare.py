#!/usr/bin/env python3
"""Prepare an isolated publisher or read-only CI example without reading secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
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


def prepare(role: str, registry: str, output: Path, ca_file: Path | None = None,
            ca_sha256: str | None = None, single_use: bool = False) -> None:
    if not safe_registry(registry):
        raise ValueError("registry must be a credential-free HTTP(S) base address")
    if single_use and role != 'consumer':
        raise ValueError('single-use mode is only supported for consumer tasks')
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError("workspace already exists; use a new directory")
    if ca_sha256 is not None and ca_file is None:
        raise ValueError('ca-sha256 requires ca-file')
    if ca_file is not None and urlsplit(registry).scheme != 'https':
        raise ValueError('CA options require an HTTPS registry')
    public_trust = None
    trust_helper = Path(__file__).with_name('trust.py')
    if ca_file is not None:
        public_trust = runpy.run_path(str(trust_helper))['read_ca'](ca_file, ca_sha256)
    source = Path(__file__).resolve().parent / role
    output.mkdir(parents=True, exist_ok=False)
    for name in ("cjpm.toml", "README.md"):
        shutil.copyfile(source / name, output / name)
    script_text = (source / 'run.sh').read_text(encoding='utf-8')
    metadata = dict(formatVersion=1, role=role, registry=registry,
                    package='company::teamhello', version='1.0.0')
    if public_trust is not None:
        trust = output / 'trust'
        (trust / 'empty').mkdir(parents=True)
        (trust / 'ca.pem').write_bytes(public_trust)
        if os.name == 'posix':
            (trust / 'ca.pem').chmod(0o444)
        digest = hashlib.sha256(public_trust).hexdigest()
        shutil.copyfile(trust_helper, output / 'trust.py')
        marker = '# Optional process trust is configured by prepare.py.'
        block = ('if ! python3 "$PWD/trust.py" --sha256 ' + digest + '; then\n'
                 '    exit 2\nfi\n'
                 'export SSL_CERT_FILE="$PWD/trust/ca.pem" SSL_CERT_DIR="$PWD/trust/empty"')
        if script_text.count(marker) != 1:
            raise ValueError('team task template lacks its process trust insertion point')
        script_text = script_text.replace(marker, block)
        metadata['trust'] = dict(mode='process-only', caSha256=digest)
    shutil.copytree(source / "src", output / "src")
    # copytree retains template modes, including a read-only delivery mount.
    # Only this newly owned task copy becomes editable; keep other permission bits.
    task_sources = output / 'src'
    for path in (task_sources, *task_sources.rglob('*')):
        path.chmod(path.stat().st_mode | (0o700 if path.is_dir() else 0o600))
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
    if single_use:
        shutil.copyfile(Path(__file__).with_name('job.py'), output / 'job.py')
        digest = hashlib.sha256((output / 'cangjie-repo.toml').read_bytes()).hexdigest()
        marker = '# Optional single-use admission is configured by prepare.py.'
        if script_text.count(marker) != 1:
            raise ValueError('consumer template lacks its single-use insertion point')
        script_text = script_text.replace(marker,
            'if ! python3 "$PWD/job.py" --configuration-sha256 ' + digest + '; then\n    exit 2\nfi')
        metadata['execution'] = dict(mode='single-use-cold-v1', configurationSha256=digest)
    (output / "workspace.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    pending_script = output / '.run.sh.tmp'
    pending_script.write_text(script_text, encoding='utf-8', newline='\n')
    pending_script.replace(output / 'run.sh')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("publisher", "consumer"))
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True, type=Path, help="new standalone workspace")
    parser.add_argument('--ca-file', type=Path, help='optional approved public PEM CA for an HTTPS task; copied, never installed')
    parser.add_argument('--ca-sha256', help='optional independently approved SHA-256 of ca-file')
    parser.add_argument('--single-use', action='store_true', help='consumer-only cold task; refuse previous state and permanently claim before build')
    args = parser.parse_args()
    try:
        prepare(args.role, args.registry, args.output.absolute(), args.ca_file, args.ca_sha256, args.single_use)
        print(f"Prepared {args.role} workspace; load your SDK environment and run bash run.sh there.")
        print("Credentials are referenced by environment variable only; none were read or written.")
        return 0
    except (OSError, ValueError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
