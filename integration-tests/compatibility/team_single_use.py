"""Native loopback HTTPS acceptance of independently approved single-use CI jobs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import runpy
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import threading
import time
import traceback

parser = argparse.ArgumentParser(description=__doc__)
for name in ('client-bundle', 'server', 'evidence-dir', 'work-dir'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--expected-client-sha256', default='f433b415f3c5af15bc795b603b8975694edc4bee1be88284aaefaac79d4d01e3')
parser.add_argument('--expected-server-sha256', default='8fc30842e87cff0dee34a76898b9ebc339780e7d5d95ea1d78ff7f8b4acfb3df')
parser.add_argument('--packaged-preparation', action='store_true',
                    help='prepare only through the verified client kit entry; source templates are not used (10 checks)')
args = parser.parse_args()
if os.name != 'posix':
    parser.error('Linux SDK environment required; Windows Cangjie execution is paused')
SOURCE = Path(__file__).resolve().parents[2]
EVIDENCE, WORK = args.evidence_dir.absolute(), args.work_dir.absolute()
for output in (EVIDENCE, WORK):
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        parser.error('evidence and work paths must be new')
if EVIDENCE == WORK or EVIDENCE in WORK.parents or WORK in EVIDENCE.parents:
    parser.error('evidence and work directories must be separate')
CLIENT, SERVER = args.client_bundle.resolve(), args.server.resolve()
CLIENT_SHA, SERVER_SHA = args.expected_client_sha256, args.expected_server_sha256
publish_token, read_token = secrets.token_hex(32), secrets.token_hex(32)
hidden = (publish_token, read_token)
gateways = []
backend = None
evidence_owned = False
result = dict(success=False, passed=0, total=10 if args.packaged_preparation else 9,
              preparationMode='packaged' if args.packaged_preparation else 'source', preparedTaskCount=0,
              stages=[], clientSha256=CLIENT_SHA, serverSha256=SERVER_SHA,
              receiverAccessed=False, systemTrustModified=False, cleanupErrors=[])
started = time.monotonic()


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def redacted(text):
    for value in hidden:
        text = text.replace(value, '[REDACTED]')
    return text


def record(name, **facts):
    result['stages'].append(dict(name=name, passed=True, **facts))
    print('PASS ' + name, flush=True)


def run(label, command, *, cwd=WORK, env=None, timeout=150):
    proc = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        data, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        data, _ = proc.communicate()
        (EVIDENCE / (label + '.log')).write_text(redacted(data.decode('utf-8', 'replace')))
        raise RuntimeError(label + ' timed out')
    text = data.decode('utf-8', 'replace')
    (EVIDENCE / (label + '.log')).write_text(redacted(text), encoding='utf-8')
    assert all(value not in text for value in hidden), 'credential appeared in captured output'
    return proc.returncode, text


def openssl(*args):
    code, _ = run('openssl-' + secrets.token_hex(3), ['openssl', *args], cwd=certs, env=base)
    assert code == 0, 'synthetic certificate generation failed'


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    def get_request(self):
        connection, address = super().get_request()
        self.accepted += 1
        connection.settimeout(10)
        try:
            return self.context.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise


class Handler(BaseHTTPRequestHandler):
    def forward(self):
        length = int(self.headers.get('Content-Length', '0'))
        assert 0 <= length <= 2 * 1024 * 1024
        body = self.rfile.read(length) if length else None
        auth = self.headers.get('Authorization', '')
        role = 'read' if auth == read_token else 'publish' if auth == publish_token else 'other'
        self.server.requests.append(dict(method=self.command, path=self.path, role=role))
        peer = http.client.HTTPConnection('127.0.0.1', backend_port, timeout=15)
        try:
            peer.request(self.command, self.path, body=body, headers={'Authorization': auth})
            response = peer.getresponse()
            payload = response.read(2 * 1024 * 1024 + 1)
            assert len(payload) <= 2 * 1024 * 1024
            self.send_response(response.status)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            peer.close()
    do_GET = do_POST = forward
    def log_message(self, *_):
        pass


def gateway(name):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certs / (name + '.pem'), certs / (name + '.key'))
    server = Gateway(('127.0.0.1', 0), Handler)
    server.context, server.requests, server.accepted = context, [], 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    gateways.append((server, thread))
    return server, 'https://127.0.0.1:' + str(server.server_port)


try:
    EVIDENCE.mkdir(exist_ok=False)
    evidence_owned = True
    WORK.mkdir(parents=True, mode=0o700, exist_ok=False)
    assert sha(CLIENT / 'cjpm') == CLIENT_SHA and sha(SERVER) == SERVER_SHA
    manifest = runpy.run_path(str(SOURCE / 'deployment/client/verify.py'))['verify_bundle'](CLIENT)
    assert manifest['files']['cjpm']['sha256'] == CLIENT_SHA
    if args.packaged_preparation:
        assert manifest.get('capabilities') == {'teamPreparation': 'single-use-cold-v1'}, 'team preparation kit required'
    frozen = {item.relative_to(SOURCE).as_posix(): sha(item) for item in (SOURCE / 'examples/team').rglob('*')
              if item.is_file() and item.suffix in ('.py', '.sh', '.cj', '.toml', '.md')}
    frozen['integration-tests/compatibility/team_single_use.py'] = sha(Path(__file__))
    delivered_files = {item.relative_to(CLIENT).as_posix(): sha(item) for item in CLIENT.rglob('*') if item.is_file()}
    (EVIDENCE / 'inputs.json').write_text(json.dumps(dict(source=frozen, clientManifestSha256=sha(CLIENT / 'manifest.json'),
        runnerSha256=sha(Path(__file__))), indent=2), encoding='utf-8')
    base = {k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))
            and k.upper() not in ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'CJPM_CONFIG') and 'PROXY' not in k.upper()}
    if args.packaged_preparation:
        damaged = WORK / 'damaged-kit'
        shutil.copytree(CLIENT, damaged)
        target = damaged / 'team/prepare.py'
        target.chmod(0o644)
        target.write_bytes(target.read_bytes() + b'\nraise RuntimeError("untrusted-preparer-must-not-run")\n')
        code, output = run('offline-corruption-refusal', ['python3', damaged / 'prepare-team.py',
            '--role', 'consumer', '--registry', 'https://registry.example.invalid',
            '--output', WORK / 'must-not-be-prepared', '--single-use'], env=base)
        assert code == 1 and 'untrusted-preparer-must-not-run' not in output
        assert not (WORK / 'must-not-be-prepared').exists()
        record('packaged-entry-rejects-corruption-offline-before-task-creation')
    assert shutil.which('openssl')
    certs = WORK / 'certificates'
    certs.mkdir(mode=0o700)
    for ca in ('ca',):
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
            '-subj', '/CN=CjRepoMesh isolated team CA', '-keyout', ca + '.key', '-out', ca + '.pem',
            '-addext', 'basicConstraints=critical,CA:TRUE')
    for name, ip in [('good', '127.0.0.1')]:
        openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
            '-keyout', name + '.key', '-out', name + '.csr')
        (certs / (name + '.ext')).write_text('subjectAltName=IP:' + ip + '\nextendedKeyUsage=serverAuth\n')
        openssl('x509', '-req', '-in', name + '.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
            '-CAcreateserial', '-days', '2', '-extfile', name + '.ext', '-out', name + '.pem')
    ca_hash = sha(certs / 'ca.pem')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        backend_port = probe.getsockname()[1]
    storage = WORK / 'storage'
    storage.mkdir(mode=0o700)
    server_env = dict(base, CJREPO_ADDRESS='127.0.0.1', CJREPO_PORT=str(backend_port),
        CJREPO_STORAGE=str(storage), CJREPO_PUBLISH_TOKEN=publish_token,
        CJREPO_READ_TOKEN=read_token, CJREPO_UPSTREAM='', CJREPO_UPSTREAM_TOKEN='')
    backend = subprocess.Popen([str(SERVER)], cwd=WORK, env=server_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 20
    while True:
        assert backend.poll() is None, 'owned backend exited before health'
        try:
            peer = http.client.HTTPConnection('127.0.0.1', backend_port, timeout=1)
            peer.request('GET', '/health')
            status = peer.getresponse().status
            peer.close()
            if status == 200:
                break
        except OSError:
            pass
        assert time.monotonic() < deadline, 'owned backend health timeout'
        time.sleep(0.1)
    good, address = gateway('good')
    if not args.packaged_preparation:
        prepare = runpy.run_path(str(SOURCE / 'examples/team/prepare.py'))['prepare']

    def task(label, *, role='consumer', endpoint=address, ca='ca.pem'):
        folder = WORK / label
        if args.packaged_preparation:
            code, output = run(label + '-prepare', ['python3', CLIENT / 'prepare-team.py',
                '--role', role, '--registry', endpoint, '--output', folder,
                '--ca-file', certs / ca, '--ca-sha256', sha(certs / ca),
                *(['--single-use'] if role == 'consumer' else [])], env=base)
            assert code == 0, 'packaged team preparation failed'
        else:
            prepare(role, endpoint, folder, certs / ca, sha(certs / ca), single_use=(role == 'consumer'))
        result['preparedTaskCount'] += 1
        env = dict(base, CJREPOMESH_CJPM=str(CLIENT / 'run.sh'),
                   SSL_CERT_FILE='/inherited/unapproved-ca', SSL_CERT_DIR='/inherited/unapproved-directory')
        env['CJREPO_PUBLISH_TOKEN' if role == 'publisher' else 'CJREPO_READ_TOKEN'] = publish_token if role == 'publisher' else read_token
        return folder, env

    publisher, penv = task('publisher', role='publisher')
    code, output = run('publisher', ['bash', 'run.sh'], cwd=publisher, env=penv)
    assert code == 0 and any(r['method'] == 'POST' and r['role'] == 'publish' for r in good.requests), 'actual HTTPS publication failed'
    metadata = json.loads((publisher / 'target/meta-data.json').read_text())
    package_sha = sha(publisher / 'target/teamhello-1.0.0.cjp')
    assert metadata['index']['sha256sum'] == package_sha
    record('prepared-HTTPS-publisher-publishes-real-package', packageSha256=package_sha)

    def approval(folder, endpoint):
        approved = dict(formatVersion=1, packages=[dict(package='company::teamhello', version='1.0.0',
            repository='internal', registry=endpoint, sha256=package_sha)])
        path = WORK / (folder.name + '-independent-approval.json')
        path.write_text(json.dumps(approved, indent=2), encoding='utf-8')
        path.chmod(0o400)
        return path, approved

    storage_before = {str(item.relative_to(storage)): sha(item) for item in storage.rglob('*') if item.is_file()}
    consumer, cenv = task('cold-consumer')
    approved_path, approved = approval(consumer, address)
    approved_bytes = approved_path.read_bytes()
    cenv['CJREPOMESH_SOURCE_BASELINE'] = str(approved_path)
    assert not (consumer / 'cache').exists() and not (consumer / 'target').exists()
    code, output = run('cold-consumer', ['bash', 'run.sh'], cwd=consumer, env=cenv)
    assert code == 0 and 'CjRepoMesh team 1.0.0: CI' in output
    assert json.loads((consumer / 'cjpm-provenance.json').read_text()) == approved
    assert approved_path.read_bytes() == approved_bytes and any(r['role'] == 'read' for r in good.requests)
    record('prepared-HTTPS-consumer-cold-build-run-and-exact-approved-source', output='CjRepoMesh team 1.0.0: CI')

    assert (consumer / '.cjrepomesh-job-started').is_dir()
    snapshot = lambda folder: {str(f.relative_to(folder)): sha(f) for f in folder.rglob('*') if f.is_file()}
    completed = snapshot(consumer)
    before = good.accepted
    code, output = run('completed-task-repeat', ['bash', 'run.sh'], cwd=consumer, env=cenv)
    assert code == 2 and good.accepted == before and snapshot(consumer) == completed
    record('completed-task-repeat-refused-before-network-with-files-preserved', newTCPConnections=0)

    for label in ('prefilled-cache', 'modified-configuration', 'missing-approval-setting'):
        folder, env = task(label)
        env['CJREPOMESH_SOURCE_BASELINE'] = str(approved_path)
        if label == 'prefilled-cache':
            (folder / 'cache').mkdir()
            (folder / 'cache/keep').write_bytes(b'owned preexisting cache evidence')
        elif label == 'modified-configuration':
            with (folder / 'cangjie-repo.toml').open('a') as config:
                config.write('# owned configuration drift\n')
        else:
            env.pop('CJREPOMESH_SOURCE_BASELINE')
        original = snapshot(folder)
        before = good.accepted
        code, output = run(label, ['bash', 'run.sh'], cwd=folder, env=env)
        assert code == 2 and good.accepted == before and snapshot(folder) == original
        assert not (folder / '.cjrepomesh-job-started').exists()
        record(label + '-refused-without-claim-or-network', newTCPConnections=0)

    shared, shared_env = task('concurrent-task')
    shared_env['CJREPOMESH_SOURCE_BASELINE'] = str(approved_path)
    offset = len(good.requests)
    def launch(number):
        return run('concurrent-' + str(number), ['bash', 'run.sh'], cwd=shared, env=shared_env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(launch, range(2)))
    assert sorted(code for code, _ in outcomes) == [0, 2]
    assert sum('CjRepoMesh team 1.0.0: CI' in output for _, output in outcomes) == 1
    assert sum(r['method'] == 'GET' and r['path'].startswith('/pkg/') for r in good.requests[offset:]) == 1
    assert (shared / '.cjrepomesh-job-started').is_dir() and approved_path.read_bytes() == approved_bytes
    record('two-launches-one-real-cold-build-and-one-refusal', artifactRequests=1)

    rejected, rejected_env = task('source-drift')
    wrong = json.loads(json.dumps(approved))
    wrong['packages'][0]['sha256'] = '0' * 64
    rejected_approval = WORK / 'independent-drift.json'
    rejected_approval.write_text(json.dumps(wrong))
    rejected_approval.chmod(0o400)
    rejected_bytes = rejected_approval.read_bytes()
    rejected_env['CJREPOMESH_SOURCE_BASELINE'] = str(rejected_approval)
    offset = len(good.requests)
    code, output = run('source-drift', ['bash', 'run.sh'], cwd=rejected, env=rejected_env)
    assert code != 0 and 'repository source baseline rejected' in output
    assert not any(r['path'].startswith('/pkg/') for r in good.requests[offset:])
    assert (rejected / '.cjrepomesh-job-started').is_dir()
    assert not (rejected / 'target/release/bin/main').exists() and not (rejected / 'cjpm-provenance.json').exists()
    before = good.accepted
    code, output = run('source-drift-repeat', ['bash', 'run.sh'], cwd=rejected, env=rejected_env)
    assert code == 2 and good.accepted == before and rejected_approval.read_bytes() == rejected_bytes
    record('failed-source-admission-keeps-claim-and-refuses-repeat', newRepeatTCPConnections=0)

    failed, failed_env = task('application-failure')
    failed_env['CJREPOMESH_SOURCE_BASELINE'] = str(approved_path)
    (failed / 'src/main.cj').write_text('package team_consumer\nimport company::teamhello.*\nimport std.env.*\n'
        'main(): Int64 {\n if (getVariable("CJREPO_READ_TOKEN").isSome() || getVariable("CJREPO_PUBLISH_TOKEN").isSome()) { return 19 }\n'
        ' println(teamGreeting("CI")); return 7\n}\n')
    code, output = run('application-failure', ['bash', 'run.sh'], cwd=failed, env=failed_env)
    assert code == 7 and 'CjRepoMesh team 1.0.0: CI' in output and (failed / '.cjrepomesh-job-started').is_dir()
    before = good.accepted
    code, output = run('application-failure-repeat', ['bash', 'run.sh'], cwd=failed, env=failed_env)
    assert code == 2 and good.accepted == before
    record('real-application-status-seven-and-claim-preserved', applicationExit=7, newRepeatTCPConnections=0)
    assert storage_before == {str(item.relative_to(storage)): sha(item) for item in storage.rglob('*') if item.is_file()}
    assert approved_path.read_bytes() == approved_bytes
    assert delivered_files == {item.relative_to(CLIENT).as_posix(): sha(item) for item in CLIENT.rglob('*') if item.is_file()}
    assert sha(certs / 'ca.pem') == ca_hash
    assert all(sha(SOURCE / name) == digest for name,digest in frozen.items())
    assert manifest == runpy.run_path(str(SOURCE / 'deployment/client/verify.py'))['verify_bundle'](CLIENT)
    result['success'] = len(result['stages']) == result['total']
except Exception as error:
    result['error'] = redacted(type(error).__name__ + ': ' + str(error))
    print('FAIL ' + result['error'], flush=True)
finally:
    for server, thread in reversed(gateways):
        try:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive()
        except Exception as error:
            result['cleanupErrors'].append(str(error))
    if backend is not None:
        try:
            if backend.poll() is None:
                os.killpg(backend.pid, signal.SIGTERM)
            try:
                output, _ = backend.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(backend.pid, signal.SIGKILL)
                output, _ = backend.communicate()
            (EVIDENCE / 'backend.log').write_text(redacted(output.decode('utf-8', 'replace')), encoding='utf-8')
        except Exception as error:
            result['cleanupErrors'].append(str(error))
    if 'certs' in globals() and result['success']:
        for key in certs.glob('*.key'):
            key.unlink()
    result['success'] = result['success'] and not result['cleanupErrors']
    result['passed'] = len(result['stages'])
    result['limits'] = ['Owned loopback HTTPS fixture on existing Linux host; no physical receiver, production ingress or system trust changes.',
                        'Cold state and one-time admission for trusted prepared jobs; no cache revalidation, hostile concurrent file mutation, script sandbox or power-loss transaction.']
    result['seconds'] = round(time.monotonic() - started, 2)
    result['workDirectory'] = str(WORK)
    if evidence_owned:
        (EVIDENCE / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('RESULT ' + json.dumps(result), flush=True)
raise SystemExit(0 if result['success'] else 1)
