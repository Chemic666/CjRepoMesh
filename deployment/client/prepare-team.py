#!/usr/bin/env python3
"""Verify this complete client kit, then prepare a separate offline team task."""
from pathlib import Path
import argparse
import runpy
import sys

# The delivery may be mounted read-only; loading its helpers must not add pyc files.
sys.dont_write_bytecode = True


def main() -> int:
    root = Path(__file__).absolute().parent
    try:
        manifest = runpy.run_path(str(root / 'verify.py'))['verify_bundle'](root)
        if manifest.get('capabilities') != {'teamPreparation': 'single-use-cold-v1'}:
            raise ValueError('this client delivery lacks team preparation support')
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--output', type=Path)
        options, _ = parser.parse_known_args()
        if options.output is not None and options.output.resolve().is_relative_to(root.resolve()):
            raise ValueError('team task output must be outside the client delivery')
    except (OSError, ValueError, KeyError, TypeError):
        print('FAIL: client kit or task output rejected; verify the trusted delivery and use a new external task directory')
        return 1
    # The verified preparer retains its full original argument validation and API.
    runpy.run_path(str(root / 'team/prepare.py'), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
