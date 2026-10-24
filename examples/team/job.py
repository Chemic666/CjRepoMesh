#!/usr/bin/env python3
"""Claim one prepared cold consumer task without clearing any previous state."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat


CLAIM = '.cjrepomesh-job-started'
OUTPUTS = ('cache', 'target', 'build', 'build-script-cache', 'cjpm.lock',
           'cjpm-provenance.json', 'cjpm-provenance.json.tmp', 'build.cj.bak')


def ordinary(path: Path, directory: bool = False) -> bool:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    return expected(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def claim(root: Path, configuration_sha256: str) -> None:
    if not os.environ.get('CJREPOMESH_SOURCE_BASELINE'):
        raise ValueError('single-use consumer requires a nonempty main source baseline')
    if not re.fullmatch(r'[a-f0-9]{64}', configuration_sha256):
        raise ValueError('single-use task configuration pin is invalid')
    if not ordinary(root, directory=True) or not ordinary(root / 'cangjie-repo.toml'):
        raise ValueError('single-use task and configuration must be ordinary filesystem entries')
    with (root / 'cangjie-repo.toml').open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536 or hashlib.sha256(data).hexdigest() != configuration_sha256:
        raise ValueError('single-use task repository configuration changed; prepare a new task')
    if not ordinary(root / '.home', directory=True) or any((root / '.home').iterdir()):
        raise ValueError('single-use task HOME must be an ordinary empty directory')
    for name in OUTPUTS:
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError('single-use task contains previous cache or build state; prepare a new task')
    try:
        (root / CLAIM).mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError('single-use task was already claimed; preserve it and prepare a new task') from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration-sha256', required=True)
    args = parser.parse_args()
    try:
        claim(Path(__file__).absolute().parent, args.configuration_sha256)
        print('PASS: single-use cold task claimed; preserve this task after completion or failure')
        return 0
    except ValueError as error:
        print('FAIL: ' + str(error))
    except OSError:
        print('FAIL: single-use task could not be checked or claimed; preserve it and prepare a new task')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
