"""Fixed large fixtures and paced rounds for the optional bounded capacity soak."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import time

from lib.harness import TestFailure


class MeasurementClock:
    """UTC labels and durations from one monotonic origin for the entire run."""
    def __init__(self, *, clock=None, utc_now=None):
        # perf_counter is monotonic and avoids Windows 3.12 GetTickCount64's
        # coarse ticks, which can make an entire fast batch appear to take zero.
        self.clock = time.perf_counter if clock is None else clock
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.origin = self.clock()

    def elapsed(self):
        return self.clock() - self.origin

    def start(self):
        return dict(startedAtUtc=self.utc_now().isoformat(),
                    startOffsetSeconds=self.elapsed())

    def finish(self, started):
        end = self.elapsed()
        return dict(endedAtUtc=self.utc_now().isoformat(), endOffsetSeconds=end,
                    elapsedSeconds=end - started['startOffsetSeconds'])


@contextmanager
def record_soak_round(report, rounds, sequence, measurements):
    """Persist completed or interrupted rounds without consuming workload errors."""
    record = dict(sequence=sequence, phaseNames=[], valid=False, **measurements.start())
    workload_failure = None
    try:
        yield record
        record['valid'] = True
    except BaseException as failure:
        workload_failure = failure
        record['error'] = str(failure) or type(failure).__name__
        raise
    finally:
        try:
            record.update(measurements.finish(record))
            rounds.append(record)
            (report / 'soak-rounds.json').write_text(json.dumps(rounds, indent=2) + '\n', encoding='utf-8')
        except Exception as evidence_failure:
            if workload_failure is not None:
                raise workload_failure from evidence_failure
            raise


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
