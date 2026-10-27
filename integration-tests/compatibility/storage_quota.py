#!/usr/bin/env python3
"""Exercise opt-in single-process storage byte quotas on owned Linux servers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse, hashlib, http.client, json, os, secrets, socket, subprocess, sys, threading, time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses, publish_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--case', action='append', help='Run only the named case; repeat for several cases')
    args = parser.parse_args()
    if os.name != 'posix': parser.error('Windows Cangjie execution is paused')
    server = args.server.resolve(); report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    variable = 'CJREPO_STORAGE_QUOTA_BYTES'; token = secrets.token_hex(32)
    base = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    artifact = hashlib.shake_256(b'CjRepoMesh storage quota').digest(16384)
    checksum = hashlib.sha256(artifact).hexdigest(); cases = []; started = time.monotonic()
    selected = set(args.case or ()); available = set()

    def metadata(name='quotaone', version='1.0.0'):
        row = dict(name=name, version=version, organization='', sha256sum=checksum, dependencies=[])
        return dict(name=name, version=version, organization='', index=row)

    def request(port, path, data=None, authorized=True):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            conn.request('POST' if data is not None else 'GET', path, body=data,
                         headers={'Authorization': token} if authorized else {})
            response = conn.getresponse(); return response.status, response.read()
        finally: conn.close()

    def publish(port, name='quotaone', version='1.0.0', authorized=True):
        body = publish_frame(json.dumps(metadata(name, version), separators=(',', ':')).encode(), artifact)
        return request(port, '/pkg/' + name, body, authorized)[0]

    def files(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}

    @contextmanager
    def owned(label, quota=None, storage=None, extra=None):
        folder = report / label; folder.mkdir()
        root = storage if storage is not None else folder / 'storage'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        env = dict(base, HOME=str(folder), USERPROFILE=str(folder), CJREPO_ADDRESS='127.0.0.1',
                   CJREPO_PORT=str(port), CJREPO_STORAGE=str(root), CJREPO_PUBLISH_TOKEN=token,
                   CJREPO_READ_TOKEN=token)
        if quota is not None: env[variable] = str(quota)
        env.update(extra or {})
        with ManagedProcesses() as processes:
            process = processes.start([server], cwd=folder, env=env, output_path=folder / 'server.log')
            ready = False
            for _ in range(150):
                if process.poll() is not None: break
                try:
                    ready = request(port, '/health')[0] == 200
                    if ready: break
                except OSError: pass
                time.sleep(.02)
            yield port, root, process, ready
        assert process.poll() is not None
        assert token not in (folder / 'server.log').read_text(errors='replace'), 'credential leaked in log'

    def case(name, operation):
        available.add(name)
        if selected and name not in selected: return
        error = ''
        try: operation()
        except Exception as failure: error = type(failure).__name__ + ': ' + str(failure)
        cases.append(dict(name=name, passed=not error, error=error))
        print(('FAIL ' if error else 'PASS ') + name, flush=True)

    index_rel = Path('index/default/qu/ot/quotaone')
    artifact_rel = lambda version: Path('artifacts/default/quotaone') / version / ('quotaone-' + version + '.cjp')
    # Calibrate actual server JSON serialization before setting exact byte boundaries.
    with owned('calibration') as (port, calibration, _, ready):
        assert ready and publish(port) == 200
        first = (calibration / index_rel).read_bytes()
        assert publish(port, version='2.0.0') == 200
        combined = (calibration / index_rel).read_bytes()
    initial = len(artifact) + len(first)
    assert len(combined) == 2 * len(first)
    (report / 'calibration.json').write_text(json.dumps(dict(artifactBytes=len(artifact),
        firstIndexBytes=len(first), combinedIndexBytes=len(combined)), indent=2))

    for label, raw in (('empty', ''), ('negative', '-1'), ('text', 'private-invalid-quota'),
                       ('overflow', '9223372036854775808')):
        def invalid(label=label, raw=raw):
            with owned('invalid-' + label, raw) as (_, _, process, ready):
                assert not ready and process.poll() == 2, 'invalid quota must exit 2 before HTTP'
            log = (report / ('invalid-' + label) / 'server.log').read_text()
            assert variable in log and 'private-invalid-quota' not in log
        case('invalid-' + label, invalid)

    for label, quota in (('omitted', None), ('zero', 0)):
        def unlimited(label=label, quota=quota):
            with owned(label, quota) as (port, _, _, ready):
                assert ready and publish(port) == publish(port, version='2.0.0') == 200
        case('compatibility-' + label, unlimited)

    def tiny():
        with owned('one-byte', 1) as (port, root, _, ready):
            assert ready and publish(port, authorized=False) == 401 and files(root) == {}
            status = publish(port)
            assert status == 507, f'quota refusal returned {status}, expected 507'
            assert files(root) == {}, 'rejected publication left files'
    case('auth-before-one-byte-quota', tiny)

    def exact():
        with owned('exact', initial) as (port, root, _, ready):
            assert ready and publish(port) == 200
            before = files(root)
            assert sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) == initial
            assert publish(port) == 409 and files(root) == before
            assert publish(port, name='quotatwo') == 507 and files(root) == before
    case('exact-boundary-and-global-package-sharing', exact)

    def restart():
        root = report / 'restart-storage'
        with owned('restart-seed', 0, root) as (port, _, _, ready): assert ready and publish(port) == 200
        before = files(root)
        with owned('restart-counted', initial, root) as (port, _, _, ready):
            assert ready and request(port, '/pkg/quotaone/1.0.0') == (200, artifact)
            assert publish(port) == 409 and publish(port, version='2.0.0') == 507
            assert files(root) == before
        with owned('restart-already-over', 1, root) as (port, _, _, ready):
            assert ready and request(port, '/pkg/quotaone/1.0.0') == (200, artifact)
            assert publish(port, version='2.0.0') == 507 and files(root) == before
    case('restart-counts-existing-and-preserves-over-quota-reads', restart)

    def replacement_peak():
        root = report / 'peak-storage'
        with owned('peak-seed', 0, root) as (port, _, _, ready): assert ready and publish(port) == 200
        before = files(root)
        # Final bytes for two versions fit, but replacing the old index requires both old and new bytes.
        with owned('peak-rollback', 2 * initial, root) as (port, _, _, ready):
            assert ready and publish(port, version='2.0.0') == 507, 'temporary replacement peak not charged'
            assert files(root) == before, 'failed index update did not roll back its artifact'
            assert publish(port, name='quotatwo') == 200, 'rollback failed to release storage budget'
            assert not list(root.rglob('*.tmp'))
    case('replacement-peak-rollback-and-budget-release', replacement_peak)

    def replacement_exact():
        root = report / 'peak-exact-storage'
        with owned('peak-exact-seed', 0, root) as (port, _, _, ready): assert ready and publish(port) == 200
        peak = 2 * len(artifact) + len(first) + len(combined)
        with owned('peak-exact', peak, root) as (port, _, _, ready):
            assert ready and publish(port, version='2.0.0') == 200
            assert (root / index_rel).read_bytes() == combined
            assert sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) == 2 * initial
            assert not list(root.rglob('*.tmp'))
    case('replacement-exact-temporary-peak-succeeds', replacement_exact)

    def concurrent():
        barrier = threading.Barrier(2)
        with owned('concurrent', initial) as (port, root, _, ready):
            assert ready
            def send(name): barrier.wait(timeout=5); return publish(port, name=name)
            with ThreadPoolExecutor(max_workers=2) as pool: statuses = list(pool.map(send, ('quotaone', 'quotatwo')))
            assert sorted(statuses) == [200, 507], statuses
            assert sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) == initial
            assert not list(root.rglob('*.tmp'))
    case('concurrent-packages-cannot-exceed-global-quota', concurrent)

    def stale_temporary():
        root = report / 'stale-storage'; stale = root / 'artifacts/default/.crash.tmp'
        stale.parent.mkdir(parents=True); stale.write_bytes(b'x' * 8192); before = files(root)
        with owned('stale-counted', initial + 8191, root) as (port, _, _, ready):
            assert ready and publish(port) == 507
            assert files(root) == before, 'stale temporary was ignored, deleted, or publication was left'
    case('startup-counts-and-preserves-crash-temporary', stale_temporary)

    def dangling_link():
        root = report / 'dangling-storage'; link = root / 'index/default/qu/ot/.quotaone.tmp'
        target = report / 'owned-link-target' / 'missing-file'
        link.parent.mkdir(parents=True); target.parent.mkdir()
        link.symlink_to(target)
        with owned('dangling-rejected', 1048576, root) as (_, _, process, ready):
            assert not ready and process.poll() == 2, 'dangling link bypassed quota startup validation'
        assert link.is_symlink() and os.readlink(link) == str(target), 'owned test link was changed'
        assert not target.exists(), 'quota initialization followed the dangling link'
    case('startup-dangling-link-rejected', dangling_link)

    class Upstream(BaseHTTPRequestHandler):
        index_body = first
        def do_GET(self):
            data = self.index_body if self.path == '/index/qu/ot/quotaone' else artifact
            self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
        def log_message(self, *_): pass
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    upstream.daemon_threads = True; worker = threading.Thread(target=upstream.serve_forever, daemon=True); worker.start()
    address = 'http://127.0.0.1:' + str(upstream.server_port)
    try:
        def proxy_index():
            with owned('proxy-index', 1, extra={'CJREPO_UPSTREAM': address}) as (port, root, _, ready):
                assert ready and request(port, '/index/qu/ot/quotaone')[0] in (502, 507)
                assert files(root) == {}
        case('proxy-index-write-shares-quota', proxy_index)
        def proxy_artifact():
            root = report / 'proxy-storage'; p = root / index_rel; p.parent.mkdir(parents=True); p.write_bytes(first)
            before = files(root)
            with owned('proxy-artifact', initial - 1, root, {'CJREPO_UPSTREAM': address}) as (port, _, _, ready):
                assert ready and request(port, '/pkg/quotaone/1.0.0')[0] in (502, 507)
                assert files(root) == before
        case('proxy-artifact-write-shares-quota', proxy_artifact)
        def mirror():
            folder = report / 'mirror'; folder.mkdir(); root = folder / 'storage'
            env = dict(base, HOME=str(folder), USERPROFILE=str(folder), CJREPO_STORAGE=str(root), **{variable: '1'})
            result = subprocess.run([str(server), 'mirror', address, 'quotaone', '1.0.0'],
                                    cwd=folder, env=env, capture_output=True, text=True, timeout=15)
            (folder / 'result.json').write_text(json.dumps(dict(returncode=result.returncode,
                stdout=result.stdout, stderr=result.stderr), indent=2))
            assert result.returncode == 1 and files(root) == {}, 'mirror bypassed global disk quota'
        case('mirror-write-shares-quota', mirror)
        def mirror_rollback_retry():
            root = report / 'mirror-retry-storage'
            def run(label, version, quota):
                folder = report / label; folder.mkdir()
                env = dict(base, HOME=str(folder), USERPROFILE=str(folder), CJREPO_STORAGE=str(root),
                           **{variable: str(quota)})
                result = subprocess.run([str(server), 'mirror', address, 'quotaone', version],
                                        cwd=folder, env=env, capture_output=True, text=True, timeout=15)
                (folder / 'result.json').write_text(json.dumps(dict(returncode=result.returncode,
                    stdout=result.stdout, stderr=result.stderr), indent=2))
                return result
            Upstream.index_body = combined
            try:
                seed = run('mirror-retry-seed', '1.0.0', 0)
                assert seed.returncode == 0 and (root / index_rel).read_bytes() == first
                before = files(root)
                refused = run('mirror-retry-refused', '2.0.0', 2 * initial)
                after_refusal = files(root)
                assert refused.returncode == 1 and 'storage byte quota reached' in refused.stderr
                assert (root / index_rel).read_bytes() == first, 'failed mirror changed its old index'
                # Retry even when the old binary left an orphan, retaining both failures as evidence.
                retry = run('mirror-retry-increased', '2.0.0', 2 * len(artifact) + len(first) + len(combined))
                assert after_refusal == before, ('failed mirror left its newly created artifact; '
                    f'larger-quota retry returncode={retry.returncode}')
                assert retry.returncode == 0, 'larger-quota retry remained blocked after rollback'
                assert (root / index_rel).read_bytes() == combined
                assert all((root / artifact_rel(v)).read_bytes() == artifact for v in ('1.0.0', '2.0.0'))
                assert not list(root.rglob('*.tmp'))
            finally:
                Upstream.index_body = first
        case('mirror-index-failure-rolls-back-new-artifact-and-allows-retry', mirror_rollback_retry)
    finally:
        upstream.shutdown(); upstream.server_close(); worker.join(timeout=3)
    assert selected <= available, 'unknown requested case: ' + ', '.join(sorted(selected - available))
    summary = dict(success=all(c['passed'] for c in cases), passed=sum(c['passed'] for c in cases),
        total=len(cases), cases=cases, seconds=round(time.monotonic()-started, 2), cleanupErrors=[],
        serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations=['Single process and exclusive storage root; no multi-process or external file mutation guarantee.',
                      'Logical managed-file bytes including temporary files, not filesystem blocks, free-space or fsync durability.'])
    (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in ('success', 'passed', 'total', 'cleanupErrors')}), flush=True)
    return int(not summary['success'])


if __name__ == '__main__': raise SystemExit(main())
