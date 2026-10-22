#!/usr/bin/env python3
"""Invalid TTL diagnostics must retain fallback behavior without echoing input."""
from __future__ import annotations
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import wait_for_health, wait_for_ports_closed


def startup_output(server,folder,env,port):
    # Cangjie stdout is buffered when redirected to a file. A private PTY keeps
    # startup lines observable before terminating this owned test process.
    import pty
    master,slave=pty.openpty()
    try:
        try:process=subprocess.Popen([str(server)],cwd=folder,env=env,stdin=subprocess.DEVNULL,stdout=slave,stderr=subprocess.STDOUT)
        finally:os.close(slave)
        try:
            wait_for_health(port);assert process.poll() is None
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        chunks=[]
        while True:
            try:chunk=os.read(master,65536)
            except OSError as failure:
                if failure.errno==errno.EIO:break
                raise
            if not chunk:break
            chunks.append(chunk)
        return b''.join(chunks).decode(errors='replace')
    finally:os.close(master)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows native execution is paused; use the existing Linux runtime')
    server=args.server.resolve();report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    base={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    cases=[];started=time.monotonic()
    definitions=[('omitted',None,86400),('zero','0',0),('negative','-1',86400),
                 ('private-text','synthetic-private-ttl-'+secrets.token_hex(16),86400),('overflow','9'*40,86400)]
    for label,value,ttl in definitions:
        folder=report/label;folder.mkdir();log=folder/'server.log';facts={};error=''
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env=dict(base,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),
            CJREPO_STORAGE=str(folder/'storage'),CJREPO_UPSTREAM='http://127.0.0.1:1')
        if value is not None:env['CJREPO_PROXY_TTL_SECONDS']=value
        try:
            output=startup_output(server,folder,env,port)
            # Keep assertions on original memory bytes, but never persist the
            # generated invalid value, even if execution is interrupted later.
            safe=output.replace(value,'[REDACTED]') if value is not None and label!='zero' else output
            log.write_text(safe)
            wait_for_ports_closed((port,))
            facts['readyWithExpectedTtl']=f'CjRepo proxy index TTL: {ttl} seconds' in output
            if label in ('negative','private-text','overflow'):
                facts['genericFallbackWarning']='Warning: invalid CJREPO_PROXY_TTL_SECONDS, using 86400' in output
                facts['rawValueHidden']=value not in output
            else:facts['noWarning']='Warning:' not in output
        except Exception as failure:error=type(failure).__name__
        passed=not error and bool(facts) and all(facts.values())
        cases.append(dict(name=label,passed=passed,facts=facts,error=error))
        print(('PASS ' if passed else 'FAIL ')+label,flush=True)
    summary=dict(success=all(c['passed'] for c in cases),passed=sum(c['passed'] for c in cases),total=5,cases=cases,
        seconds=round(time.monotonic()-started,2),serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limits=['Owned local server startup and health checks only; no TTL expiry timing, upstream fetch, Docker, Windows Cangjie or full acceptance.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return int(not summary['success'])


if __name__=='__main__':raise SystemExit(main())
