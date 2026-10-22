#!/usr/bin/env python3
"""Check server TCP connect deadlines with an owned saturated loopback listener."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--case', action='append', help='run only the named case; repeat to select several')
    args = parser.parse_args()
    if os.name == 'nt': parser.error('Windows native execution is paused; use the existing Linux environment')
    server = args.server.resolve()
    metadata = json.loads((args.package_dir/'meta-data.json').read_text())
    name, version = metadata['name'], metadata['version']
    if metadata['organization'] or len(name) < 4: parser.error('use an existing default-organization CJP fixture')
    artifact = (args.package_dir/f'{name}-{version}.cjp').read_bytes()
    assert digest(artifact) == metadata['index']['sha256sum']
    index_path, artifact_path = f'/index/{name[:2]}/{name[2:4]}/{name}', f'/pkg/{name}/{version}'
    index = json.dumps(metadata['index']).encode()+b'\n'
    report = args.evidence_dir.resolve(); report.mkdir(parents=True, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results = []; started = time.monotonic()

    class Fixture:
        def __init__(self, paused=False, pause_after_index=False):
            self.paths = []; self.fillers = []; self.worker = None; fixture = self
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    fixture.paths.append(self.path)
                    if pause_after_index and self.path == index_path:
                        # Stop accepting before returning the absent-version preflight.
                        # The next connection must be the publication POST.
                        fixture.http.shutdown(); fixture.worker.join(timeout=3)
                        fixture.worker = None
                        fixture.saturate()
                        self.send_response(404); self.end_headers(); return
                    self.send_response(200); self.end_headers()
                    self.wfile.write(index if self.path == index_path else artifact)
                def log_message(self, *args): pass
            self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.http.daemon_threads = True
            self.base = f'http://127.0.0.1:{self.http.server_port}'
            self.saturated = False
            if paused: self.saturate()
            else: self.resume()
        def saturate(self):
            self.http.socket.listen(1)
            for _ in range(8):
                peer = socket.socket(); peer.settimeout(.25)
                try:
                    peer.connect(('127.0.0.1', self.http.server_port)); self.fillers.append(peer)
                except socket.timeout:
                    self.saturated = True; peer.close(); break
                except BaseException:
                    peer.close(); raise
            if not self.saturated: self.close(); raise AssertionError('owned listener could not be saturated')
        def resume(self):
            for peer in self.fillers: peer.close()
            self.fillers.clear()
            if self.worker is None:
                self.worker = threading.Thread(target=self.http.serve_forever, daemon=True); self.worker.start()
        def close(self):
            for peer in self.fillers: peer.close()
            self.fillers.clear()
            if self.worker:
                self.http.shutdown(); self.worker.join(timeout=3)
            self.http.server_close()

    def get(url, timeout=5):
        try:
            with opener.open(url, timeout=timeout) as response: return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error: return error.code, error.read()

    def files(folder):
        return {p.relative_to(folder).as_posix(): digest(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}

    def command(arguments, folder, env, timeout):
        before = time.monotonic()
        try:
            result = subprocess.run(list(map(str, arguments)), cwd=folder, env=env, capture_output=True,
                                    text=True, timeout=timeout)
            output = result.stdout+result.stderr
            (folder/'command.log').write_text(output)
            return dict(exitCode=result.returncode, driverTimedOut=False, seconds=round(time.monotonic()-before, 3)), output
        except subprocess.TimeoutExpired:
            return dict(exitCode=None, driverTimedOut=True, seconds=round(time.monotonic()-before, 3)), ''

    cases = [('blocked', mode) for mode in ('mirror-source', 'sync-source', 'sync-destination', 'proxy-source', 'sync-publish')]
    cases += [('invalid', value) for value in ('', '0', '-1', '301', '2.5', 'synthetic-private-value')]
    cases += [('valid', value) for value in ('default', '1', '300')]
    if args.case:
        names = {kind+'-'+(value or 'empty') for kind, value in cases}
        if set(args.case)-names: parser.error('unknown case selection')
        cases = [(kind,value) for kind,value in cases if kind+'-'+(value or 'empty') in args.case]
    for kind, value in cases:
        label = kind+'-'+(value or 'empty'); folder = report/label; folder.mkdir()
        storage = folder/'storage'; storage.mkdir()
        source = destination = None
        facts = dict(kind=kind, value=value); passed=False; error=''
        try:
            source = Fixture(paused=kind == 'blocked' and value not in ('sync-destination', 'sync-publish'))
            destination = Fixture(paused=kind == 'blocked' and value == 'sync-destination',
                                  pause_after_index=kind == 'blocked' and value == 'sync-publish')
            env = dict(environment, CJREPO_STORAGE=str(storage), CJREPO_UPSTREAM_TOKEN='fixture-source')
            if value != 'default': env['CJREPO_CONNECT_TIMEOUT_SECONDS'] = '2' if kind == 'blocked' else value
            if kind == 'blocked' and value == 'proxy-source':
                with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); port=probe.getsockname()[1]
                env.update(CJREPO_ADDRESS='127.0.0.1', CJREPO_PORT=str(port), CJREPO_UPSTREAM=source.base)
                with ManagedProcesses() as processes:
                    process = processes.start((server,), cwd=folder, env=env, output_path=folder/'server.log')
                    for _ in range(50):
                        try:
                            if get(f'http://127.0.0.1:{port}/health')[0] == 200: break
                        except OSError: pass
                        if process.poll() is not None: raise AssertionError('owned proxy stopped before ready')
                        time.sleep(.1)
                    else: raise AssertionError('owned proxy not ready')
                    before=time.monotonic()
                    code, body = get(f'http://127.0.0.1:{port}'+index_path, timeout=4)
                    facts.update(status=code, seconds=round(time.monotonic()-before, 3))
                    assert code == 502 and 1 <= facts['seconds'] < 4 and not files(storage)
                    source.resume()
                    code, body = get(f'http://127.0.0.1:{port}'+index_path)
                    assert code == 200 and json.loads(body)['sha256sum'] == digest(artifact)
                    code, body = get(f'http://127.0.0.1:{port}'+artifact_path)
                    assert code == 200 and body == artifact
                    facts['recoveredSameProxyAndPackage'] = True
            else:
                arguments = [server, 'sync' if kind == 'blocked' and value.startswith('sync') else 'mirror', source.base]
                if kind == 'blocked' and value.startswith('sync'): arguments.append(destination.base)
                arguments += [name, version]
                execution, output = command(arguments, folder, env, timeout=4 if kind == 'blocked' else 10)
                facts.update(execution)
                assert not execution['driverTimedOut'], 'driver deadline expired before server returned'
                if kind == 'blocked':
                    assert execution['exitCode'] != 0 and 1 <= execution['seconds'] < 4 and not files(storage)
                    if value == 'sync-destination': assert source.paths == [index_path]
                    if value == 'sync-publish':
                        assert source.paths == [index_path, artifact_path]
                        assert destination.paths == [index_path] and 'connect timeout' in output.lower()
                        facts['publicationConnectReachedAfter404AndVerifiedArtifact'] = True
                elif kind == 'invalid':
                    assert execution['exitCode'] == 2 and 'CJREPO_CONNECT_TIMEOUT_SECONDS' in output
                    assert 'synthetic-private-value' not in output and not source.paths and not files(storage)
                else:
                    assert execution['exitCode'] == 0 and 'result=SYNCED' in output
                    assert any(p.endswith('.cjp') and d == digest(artifact) for p,d in files(storage).items())
            if kind == 'blocked':
                blocked = destination if value in ('sync-destination', 'sync-publish') else source
                facts['listenerSaturated'] = blocked.saturated
                assert blocked.saturated
                if value not in ('proxy-source', 'sync-publish'): assert not blocked.paths
            passed=True
        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as failure:
            error=str(failure) or type(failure).__name__
        finally:
            facts.update(sourcePaths=source.paths if source else [], destinationPaths=destination.paths if destination else [], storage=files(storage))
            for fixture in (destination, source):
                if fixture: fixture.close()
        results.append(dict(name=label, passed=passed, error=error, facts=facts))
        print(('PASS ' if passed else 'FAIL ')+label+(' '+error if error else ''), flush=True)
    success=all(r['passed'] for r in results)
    summary=dict(success=success, passed=sum(r['passed'] for r in results), total=len(results),
        seconds=round(time.monotonic()-started, 2), serverSha256=digest(server.read_bytes()),
        runnerSha256=digest(Path(__file__).read_bytes()), realArtifactSha256=digest(artifact), cases=results,
        limits=['Owned saturated IPv4 loopback listeners only; no external blackhole or firewall changes.',
                'Configured two-second TCP timeout; no default30-second, DNS, TLS handshake, slow read/write or cross-host timing acceptance.',
                'Linux only; no Windows Cangjie execution.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(f'Server connect timeout: {summary["passed"]}/{len(results)}; success={success}',flush=True)
    return int(not success)


if __name__ == '__main__': raise SystemExit(main())
