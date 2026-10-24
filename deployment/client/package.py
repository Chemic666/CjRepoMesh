#!/usr/bin/env python3
"""Copy an existing Linux cjpm and its two runtime libraries into a new bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from verify import FILES, TEAM_FILES, TEAM_CAPABILITY, digest, regular, require_elf, verify_bundle


def package(client: Path, runtime: Path, output: Path, include_team: bool = False) -> dict:
    try: output.lstat()
    except FileNotFoundError: pass
    else: raise FileExistsError('output must be a new directory')
    # Explicit SDK input links are copied as resolved regular files, never links.
    inputs = {'cjpm': client.resolve(),
              'lib/libcangjie-runtime.so': (runtime / 'libcangjie-runtime.so').resolve(),
              'lib/libboundscheck.so': (runtime / 'libboundscheck.so').resolve()}
    for path in inputs.values(): require_elf(path)
    source = Path(__file__).resolve().parent
    team_inputs = {}
    if include_team:
        for name in TEAM_FILES:
            path = (source / name if name == 'prepare-team.py' else
                    source.parents[1] / 'examples' / name)
            if not regular(path):
                raise ValueError('team preparation inputs must be regular files')
            team_inputs[name] = path
    output.mkdir(parents=True, exist_ok=False)
    (output / 'lib').mkdir()
    for name, path in inputs.items(): shutil.copyfile(path, output / name)
    for name in ('run.sh', 'verify.py', 'README.md'):
        (output / name).write_bytes((source / name).read_bytes().replace(b'\r\n', b'\n'))
    shutil.copyfile(source.parents[1] / 'LICENSE', output / 'LICENSE')
    for name, path in team_inputs.items():
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
    expected = FILES | set(team_inputs)
    for name in expected: (output / name).chmod(0o755 if name in ('cjpm', 'run.sh') else 0o644)
    manifest = dict(formatVersion=1, platform=dict(os='linux', architecture='amd64'),
                    files={name: dict(bytes=(output / name).stat().st_size, sha256=digest(output / name))
                           for name in sorted(expected)})
    if include_team:
        manifest['capabilities'] = dict(TEAM_CAPABILITY)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    verify_bundle(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cjpm', required=True, type=Path, help='existing Linux amd64 enhanced client')
    parser.add_argument('--runtime-dir', required=True, type=Path, help='matching existing SDK runtime directory')
    parser.add_argument('--output', required=True, type=Path, help='new output directory, never an initialized bundle')
    parser.add_argument('--include-team', action='store_true', help='include verified offline publisher/consumer preparation tools')
    args = parser.parse_args()
    try:
        manifest = package(args.cjpm, args.runtime_dir, args.output.absolute(), args.include_team)
        print('PASS: client distribution created; cjpm SHA-256 ' + manifest['files']['cjpm']['sha256'])
        print('Manifest SHA-256: ' + digest(args.output / 'manifest.json'))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('FAIL: ' + str(error))
        return 1


if __name__ == '__main__': raise SystemExit(main())
