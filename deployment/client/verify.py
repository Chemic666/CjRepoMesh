#!/usr/bin/env python3
"""Check a Linux client distribution without loading or executing its binaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import struct

FILES = {'cjpm', 'lib/libcangjie-runtime.so', 'lib/libboundscheck.so',
         'run.sh', 'verify.py', 'README.md', 'LICENSE'}
ROOT_ENTRIES = {'cjpm', 'lib', 'run.sh', 'verify.py', 'README.md', 'LICENSE', 'manifest.json'}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def regular(path: Path, *, directory: bool = False) -> bool:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    return expected(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def require_elf(path: Path) -> None:
    if not regular(path): raise ValueError('ELF input must be a regular file')
    with path.open('rb') as stream: header = stream.read(64)
    if (len(header) != 64 or header[:7] != b'\x7fELF\x02\x01\x01' or
            struct.unpack_from('<H', header, 18)[0] != 62 or
            struct.unpack_from('<H', header, 16)[0] not in (2, 3)):
        raise ValueError('expected a Linux amd64 ELF binary')


def verify_bundle(root: Path) -> dict:
    if not regular(root / 'lib', directory=True): raise ValueError('lib must be a regular directory')
    if not regular(root / 'manifest.json'): raise ValueError('manifest must be a regular file')
    if set(p.name for p in root.iterdir()) != ROOT_ENTRIES: raise ValueError('unexpected bundle entry')
    if set(p.name for p in (root / 'lib').iterdir()) != {'libcangjie-runtime.so', 'libboundscheck.so'}:
        raise ValueError('unexpected runtime entry')
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict): raise ValueError('manifest must be an object')
    if type(manifest.get('formatVersion')) is not int or manifest['formatVersion'] != 1:
        raise ValueError('unsupported client manifest version')
    if manifest.get('platform') != dict(os='linux', architecture='amd64'):
        raise ValueError('unsupported client platform')
    if not isinstance(manifest.get('files'), dict) or set(manifest['files']) != FILES:
        raise ValueError('unexpected client file list')
    for name in sorted(FILES):
        path, entry = root / name, manifest['files'][name]
        if (not isinstance(entry, dict) or not regular(path) or type(entry.get('bytes')) is not int or
                entry['bytes'] != path.stat().st_size or not isinstance(entry.get('sha256'), str) or
                not re.fullmatch('[a-f0-9]{64}', entry['sha256']) or entry['sha256'] != digest(path)):
            raise ValueError('client integrity check failed: ' + name)
    for name in ('cjpm', 'lib/libcangjie-runtime.so', 'lib/libboundscheck.so'): require_elf(root / name)
    return manifest


def main() -> int:
    try:
        manifest = verify_bundle(Path(__file__).absolute().parent)
        print('PASS: client bundle integrity; cjpm SHA-256 ' + manifest['files']['cjpm']['sha256'])
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('FAIL: ' + str(error))
        return 1


if __name__ == '__main__': raise SystemExit(main())
