#!/usr/bin/env python3
"""Validate the public process trust of a prepared standalone team task."""
import argparse
import hashlib
from pathlib import Path
import re
import ssl
import stat
import sys

LIMIT = 1024 * 1024


def ordinary(path: Path, kind) -> bool:
    info = path.lstat()
    return kind(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def read_ca(path: Path, expected_sha256: str | None = None) -> bytes:
    try:
        if not ordinary(path, stat.S_ISREG) or path.stat().st_size > LIMIT:
            raise ValueError()
        with path.open('rb') as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError()
        text = data.decode('ascii')
        pattern = r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----'
        if not re.findall(pattern, text, re.DOTALL) or re.sub(pattern, '', text, flags=re.DOTALL).strip():
            raise ValueError()
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=text)
        if expected_sha256 is not None:
            if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256):
                raise ValueError()
            if hashlib.sha256(data).hexdigest() != expected_sha256.lower():
                raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError):
        raise ValueError('trusted CA must be a regular certificate-only PEM of at most 1 MiB with the expected SHA-256; no keys or links') from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha256', required=True, help='independently checked prepared public CA digest')
    args = parser.parse_args()
    try:
        trust = Path(__file__).resolve().parent / 'trust'
        empty = trust / 'empty'
        if not ordinary(trust, stat.S_ISDIR) or not ordinary(empty, stat.S_ISDIR) or any(empty.iterdir()):
            raise ValueError('extra trust directory must be an empty ordinary directory')
        read_ca(trust / 'ca.pem', args.sha256)
        return 0
    except (OSError, ValueError):
        print('Prepared HTTPS trust verification failed; retain the original task and recheck the approved CA.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
