"""Fixed large fixtures and paced rounds for the optional bounded capacity soak."""
import hashlib
import json
import time

from lib.harness import TestFailure


def make_fixture(number, version, *, size=262144, description=None):
    name, ver = f"capacity_{number:03d}", f"1.0.{version}"
    org = "benchcorp" if number % 2 else ""
    body = hashlib.shake_256(f"CjRepoMesh capacity/{org}/{name}/{ver}".encode()).digest(size)
    checksum = hashlib.sha256(body).hexdigest()
    index = dict(name=name, version=ver, organization=org, sha256sum=checksum, dependencies=[])
    if description is not None:
        index['description'] = description
    query = "?organization=" + org if org else ""
    return dict(name=name, version=ver, organization=org, body=body, sha256=checksum,
                metadata=dict(name=name, version=ver, organization=org, index=index),
                publish=f"/pkg/{name}{query}", download=f"/pkg/{name}/{ver}{query}",
                index=f"/index/{name[:2]}/{name[2:4]}/{name}{query}")


def large_fixtures():
    return [make_fixture(64, n, size=16 * 1048576) for n in range(4)]


def index_fixtures():
    return [make_fixture(65, n, size=1024, description='x' * 65536) for n in range(64)]


def stream_fixture(sequence):
    return make_fixture(66, sequence)


def validate_complete_index(body, items):
    rows = [json.loads(line) for line in body.splitlines() if line]
    if any(not isinstance(row, dict) or not isinstance(row.get('version'), str) for row in rows):
        raise TestFailure('invalid index row shape')
    expected = {item['version']: item['metadata']['index'] for item in items}
    if len(rows) != len(expected) or {row['version']: row for row in rows} != expected:
        raise TestFailure('complete index differs from immutable source fixtures')


def paced_rounds(seconds, *, interval=5, clock=time.monotonic, sleep=time.sleep):
    start = clock()
    sequence = 0
    while clock() - start < seconds:
        yield sequence
        sequence += 1
        # Space rounds by at least interval; a slow round never creates catch-up bursts.
        remaining = start + seconds - clock()
        pause = min(interval, remaining)
        if pause > 0:
            sleep(pause)
