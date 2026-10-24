#!/usr/bin/env python3
"""Check real doctor metadata probes and fallback labels against routed successors."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cjpm', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True, help='new private directory; retained on failure')
    args = parser.parse_args()
    client = args.cjpm.resolve()
    if not client.is_file():
        parser.error('an existing enhanced client is required')
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    requests, active = [], {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            name = self.path.split('/')[1]
            status = active[name]
            requests.append(dict(repository=name, status=status, path=self.path, method='GET'))
            value = (dict(name='teamhello', version='1.0.0', organization='company', deps=[], sha256sum='a'*64)
                     if status == 200 else dict(errors=[dict(message='synthetic metadata status')]))
            body = (json.dumps(value)+'\n').encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    fixture.daemon_threads = True
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    origin = 'http://127.0.0.1:'+str(fixture.server_port)
    # label,statuses,route target,exclusive,second enabled,request order,ALLOWED count,BLOCKED count
    cases = [
        ('exclusive404', [404,200], 'first', True, True, ['first'], 0,1),
        ('single404', [404], '', False, True, ['first'], 0,1),
        ('first404-next200', [404,200], '', False, True, ['first','second'], 1,0),
        ('final404', [200,404], '', False, True, ['first','second'], 0,1),
        ('first401-independent-probes', [401,200], '', False, True, ['first','second'], 0,1),
        ('first403-independent-probes', [403,200], '', False, True, ['first','second'], 0,1),
        ('first503-next200', [503,200], '', False, True, ['first','second'], 1,0),
        ('exclusive503', [503,200], 'first', True, True, ['first'], 0,1),
        ('disabled-successor404', [404,200], '', False, False, ['first'], 0,1),
        ('routed-order404', [200,404], 'second', False, True, ['second','first'], 1,0),
        ('all200', [200,200], '', False, True, ['first','second'], 0,0),
    ]
    results, cleanup = [], []
    started = time.monotonic()
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))
           and k.upper() != 'CJPM_CONFIG'}
    try:
        for label,statuses,target,exclusive,enabled,order,allowed,blocked in cases:
            job = report/label
            job.mkdir()
            home = job/'.home'
            home.mkdir()
            text = '[repository.cache]\npath = "cache"\n'
            active.clear()
            for index,status in enumerate(statuses):
                name = ('first','second')[index]
                active[name] = status
                text += ('[repository.'+name+']\nregistry = '+json.dumps(origin+'/'+name)+
                         '\npriority = '+str(100-index*10)+'\n')
                if name == 'second' and not enabled:
                    text += 'enabled = false\n'
            if target:
                text += ('[[route]]\nnamespace = "company::*"\nregistry = '+json.dumps(target)+
                         '\nexclusive = '+str(exclusive).lower()+'\n')
            config = job/'cangjie-repo.toml'
            config.write_text(text, encoding='utf-8')
            before = config.read_bytes()
            requests.clear()
            entry = dict(name=label, passed=False)
            try:
                proc = subprocess.run([str(client),'repo','doctor','company::teamhello'], cwd=job,
                    env=dict(env,HOME=str(home),USERPROFILE=str(home)), capture_output=True,
                    text=True, encoding='utf-8', errors='replace', timeout=45)
                output = proc.stdout+proc.stderr
                (job/'output.log').write_text(output, encoding='utf-8')
                entry.update(exitCode=proc.returncode, requests=list(requests))
                assert [r['repository'] for r in requests] == order, 'unexpected diagnostic probe order'
                assert all('/index/' in r['path'] for r in requests), 'doctor must only request metadata'
                assert (proc.returncode == 0) == all(active[name] == 200 for name in order), 'doctor exit semantics changed'
                assert output.count('Fallback       ALLOWED') == allowed, 'incorrect ALLOWED fallback count'
                assert output.count('Fallback       BLOCKED') == blocked, 'incorrect BLOCKED fallback count'
                assert config.read_bytes() == before, 'configuration changed'
                entry['passed'] = True
                print('PASS '+label, flush=True)
            except Exception as error:
                entry['error'] = type(error).__name__+': '+str(error)
                print('FAIL '+label+': '+entry['error'], flush=True)
            results.append(entry)
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            cleanup.append('owned HTTP fixture thread did not stop')
    summary = dict(success=all(r['passed'] for r in results) and len(results)==len(cases) and not cleanup,
        passed=sum(r['passed'] for r in results), total=len(cases), seconds=round(time.monotonic()-started,2),
        clientSha256=hashlib.sha256(client.read_bytes()).hexdigest(), stages=results, cleanupErrors=cleanup,
        limits=['Owned loopback metadata fixtures only; no artifact download, build, TLS or fixed-package refresh.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(str(summary['passed'])+'/'+str(summary['total'])+'; cleanup='+str(cleanup), flush=True)
    return int(not summary['success'])


if __name__ == '__main__':
    raise SystemExit(main())
