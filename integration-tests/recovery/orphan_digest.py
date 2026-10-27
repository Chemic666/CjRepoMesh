#!/usr/bin/env python3
"""Exercise isolated Hosted orphan-file digest boundaries without real data."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import (ManagedProcesses, assert_equal, assert_ports_available,
                         http_request, publish_frame, wait_for_health, wait_for_ports_closed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--port', type=int, default=39820)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    args = parser.parse_args()
    server = args.server.resolve()
    if not server.is_file(): parser.error('server must be an existing executable')
    assert_ports_available((args.port,))
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    root = TESTS / '.tmp' / ('orphan-digest-' + uuid.uuid4().hex)
    storage = root / 'storage'
    root.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CJREPO_', 'CJREPOMESH_'))}
    env.update(CJREPO_ADDRESS='127.0.0.1', CJREPO_PORT=str(args.port), CJREPO_STORAGE=str(storage),
               CJREPO_READ_TOKEN='orphan-read-fixture', CJREPO_PUBLISH_TOKEN='orphan-write-fixture')
    base = f'http://127.0.0.1:{args.port}'
    checks = []
    started = time.perf_counter()
    success = False
    error = ''

    def paths(name):
        return (storage / 'artifacts/default' / name / '1.0.0' / (name + '-1.0.0.cjp'),
                storage / 'index/default' / name[:2] / name[2:4] / name)

    def publish(name, body):
        row = dict(name=name, version='1.0.0', organization='',
                   sha256sum=hashlib.sha256(body).hexdigest(), dependencies=[])
        meta = dict(name=name, version='1.0.0', organization='', index=row)
        return http_request('POST', base + '/pkg/' + name,
                            headers={'Authorization': env['CJREPO_PUBLISH_TOKEN']},
                            body=publish_frame(json.dumps(meta).encode(), body)).status, row

    def seed(name, data):
        artifact, index = paths(name)
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(data)
        return artifact, index, artifact.stat().st_mtime_ns

    def passed(name):
        checks.append(name)
        print('PASS ' + name, flush=True)

    try:
        with ManagedProcesses() as processes:
            process = processes.start((server,), cwd=server.parent, env=env,
                                      output_path=evidence / 'server.log')
            wait_for_health(args.port)
            for size in (1, 65535, 65536, 65537, 131072, 131073):
                body = (b'A' * (size - 1)) + b'Z'
                name = 'digestboundary' + str(size)
                artifact, index, mtime = seed(name, body)
                status, row = publish(name, body)
                assert_equal(status, 200, label='matching orphan recovery')
                original_index = index.read_bytes()
                assert_equal([json.loads(l) for l in original_index.splitlines()], [row], label='exact index')
                assert_equal(artifact.stat().st_mtime_ns, mtime, label='orphan not rewritten')
                assert_equal(publish(name, body)[0], 409, label='immutable recovered duplicate')
                assert_equal(index.read_bytes(), original_index, label='duplicate index unchanged')
                response = http_request('GET', base + '/pkg/' + name + '/1.0.0',
                                        headers={'Authorization': env['CJREPO_READ_TOKEN']})
                assert_equal((response.status, response.body), (200, body), label='download after repair')
                passed('digest boundary ' + str(size))

            body = b'A' * 65536 + b'Z'
            for label, existing in [('same-length', body[:-1] + b'X'),
                                    ('short', body[:-1]), ('long', body + b'X'), ('empty', b'')]:
                name = 'digestconflict' + label.replace('-', '')
                artifact, index, mtime = seed(name, existing)
                assert_equal(publish(name, body)[0], 409, label='conflicting orphan rejected')
                assert_equal(index.exists(), False, label='conflict creates no index')
                assert_equal(artifact.read_bytes(), existing, label='conflicting bytes preserved')
                assert_equal(artifact.stat().st_mtime_ns, mtime, label='conflict mtime preserved')
                passed('conflicting orphan ' + label)

            name = 'digestconcurrent'
            artifact, index, mtime = seed(name, body)
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(lambda _: publish(name, body)[0], range(2)))
            assert_equal(statuses, [200, 409], label='one concurrent repair wins')
            assert_equal(len(index.read_bytes().splitlines()), 1, label='one committed record')
            assert_equal(artifact.stat().st_mtime_ns, mtime, label='concurrent orphan preserved')
            passed('concurrent matching retries')

            name = 'digestoversized'
            artifact, index, _ = seed(name, b'')
            with artifact.open('r+b') as stream:
                stream.truncate(256 * 1024 * 1024)
            before = artifact.stat()
            assert_equal(publish(name, b'Z')[0], 409, label='oversized orphan is a conflict')
            assert_equal(index.exists(), False, label='oversized orphan creates no index')
            after = artifact.stat()
            assert_equal((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns),
                         label='oversized orphan is untouched')
            passed('oversized disk orphan with one-byte upload')
            processes.stop(process)
            wait_for_ports_closed((args.port,))
            # Exactly one request fits: a leaked lease makes the retry fail.
            env['CJREPO_MAX_INFLIGHT_ARTIFACT_BYTES'] = str(len(body))
            process = processes.start((server,), cwd=server.parent, env=env,
                                      output_path=evidence / 'server-tight-budget.log')
            wait_for_health(args.port)
            name = 'digestreaderror'
            artifact, index = paths(name)
            artifact.mkdir(parents=True)
            assert_equal(publish(name, body)[0], 400, label='directory cannot be read as artifact')
            assert_equal(index.exists(), False, label='read error creates no index')
            assert_equal(artifact.is_dir(), True, label='existing path preserved')
            artifact.rmdir()
            artifact.write_bytes(body)
            assert_equal(publish(name, body)[0], 200, label='retry releases lock and lease')
            passed('open/read error then retry')

            processes.stop(process)
            wait_for_ports_closed((args.port,))
        success = True
    except Exception as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        print('FAIL ' + error, flush=True)
    finally:
        if success: shutil.rmtree(root)
        summary = dict(success=success, passed=len(checks), total=13, checks=checks, error=error,
                       seconds=round(time.perf_counter() - started, 2),
                       serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),
                       limits=['Synthetic bytes and a sparse oversized orphan, not real CJP or 128MiB capacity.',
                               'Directory read failure does not prove a mid-stream I/O failure.'])
        (evidence / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return int(not success)


if __name__ == '__main__': raise SystemExit(main())
