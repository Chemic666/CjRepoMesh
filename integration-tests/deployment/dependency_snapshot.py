#!/usr/bin/env python3
"""Exercise the delivered approved-set snapshot with real, previously bundled CJP inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid

from portable_ca import run_process, safe_error


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def finish_owned(capture, stop, errors: list, *, kind: str) -> None:
    """A diagnostic failure must not skip stopping an already owned resource."""
    try:
        capture()
    except Exception:
        errors.append('owned '+kind+' log capture failed')
    try:
        stop()
    except Exception:
        errors.append('owned '+kind+' cleanup failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'client-bundle', 'client-sdk', 'native', 'evidence-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--package-dir', type=Path, action='append', required=True,
        help='four existing real package dirs: meshdep 1/2, company::baselineparent and company::teamhello')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2]
    bundle, report = args.bundle.resolve(), args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    server = runpy.run_path(str(source/'deployment/portable/verify.py'))['verify_bundle'](bundle)
    client = runpy.run_path(str(source/'deployment/client/verify.py'))['verify_bundle'](args.client_bundle)
    if (server.get('dependencySnapshot') != 'approved-set-v1' or (bundle/'.env').exists() or
            not (args.native/'bin/python3').is_file() or not (args.client_sdk/'envsetup.sh').is_file()):
        parser.error('verified unconfigured snapshot bundle and existing native tools/SDK required')
    packages = {}
    frame = runpy.run_path(str(source/'integration-tests/lib/harness.py'))['publish_frame']
    for directory in args.package_dir:
        metadata_bytes = (directory/'meta-data.json').read_bytes()
        meta = json.loads(metadata_bytes)
        org, name, version = meta['organization'], meta['name'], meta['version']
        artifact = (directory/f'{name}-{version}.cjp').read_bytes()
        assert hashlib.sha256(artifact).hexdigest() == meta['index']['sha256sum']
        assert (org, name, version) not in packages
        packages[org, name, version] = (meta, artifact, frame(metadata_bytes, artifact))
    assert set(packages) == {('', 'meshdep', '1.0.0'), ('', 'meshdep', '2.0.0'),
                            ('company', 'baselineparent', '1.0.0'), ('company', 'teamhello', '1.0.0')}
    image = server['image']['id']
    started = time.monotonic()
    stages, projects, jobs, hidden, cleanup = [], [], [], [], []
    failure = ''
    proof = 'cjrepomesh-snapshot-'+uuid.uuid4().hex
    network = proof+'-network'
    network_created = False
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('COMPOSE_', 'CJREPO_', 'CJREPOMESH_'))}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def run(label, arguments, *, directory=report, success=True, log=True, timeout=120):
        result = run_process(arguments, cwd=directory, env=environment, timeout=timeout)
        text = result.stdout+result.stderr
        for secret in hidden:
            text = text.replace(secret, '[REDACTED]')
        if log: (report/(label+'.log')).write_text(text, encoding='utf-8')
        if success is not None:
            assert (result.returncode == 0) == success, label+' returned unexpected status'
        return result.stdout

    def passed(name, **facts):
        stages.append(dict(name=name, **facts)); print('PASS '+name, flush=True)

    def configure(name):
        root = report/name; shutil.copytree(bundle, root)
        run(name+'-configure', [sys.executable, root/'configure.py', '--port', free_port()], directory=root)
        values = dict(line.split('=', 1) for line in (root/'.env').read_text().splitlines())
        hidden.extend(values[key] for key in ('CJREPO_READ_TOKEN', 'CJREPO_PUBLISH_TOKEN'))
        projects.append((root, values))
        return root, values

    def compose(root, values, label, *arguments, isolated=False):
        command = ['docker', 'compose', '-p', values['COMPOSE_PROJECT_NAME'], '-f', root/'compose.yaml']
        if isolated: command += ['-f', report/'isolation.yaml']
        return run(label, command+['--env-file', root/'.env', *arguments], directory=root)

    def container(root, values, isolated=False):
        return compose(root, values, 'container-'+root.name, 'ps', '-a', '-q', isolated=isolated).strip()

    def healthy(identifier):
        end = time.monotonic()+50
        while time.monotonic() < end:
            item = json.loads(run('health-'+identifier[:12], ['docker', 'inspect', identifier], log=False))[0]
            if item['State'].get('Health', {}).get('Status') == 'healthy': return item
            assert item['State'].get('Running'), 'owned registry exited before health readiness'
            time.sleep(0.25)
        raise AssertionError('owned registry health timeout')

    def http(values, path, *, token='', data=None):
        request = urllib.request.Request('http://127.0.0.1:'+values['CJREPO_HOST_PORT']+path,
            data=data, headers={'Authorization': token} if token else {})
        try:
            with opener.open(request, timeout=10) as response: return response.status, response.read()
        except urllib.error.HTTPError as error: return error.code, error.read()

    def snapshot_command(root, command, *arguments):
        return [sys.executable, root/'snapshot.py', command, *arguments]

    registry = 'http://snapshot-registry:8080'
    approval = report/'approved-source.json'
    approved = dict(formatVersion=1, packages=[])
    for org, name, version in (('company', 'baselineparent', '1.0.0'), ('', 'meshdep', '1.0.0')):
        meta = packages[org, name, version][0]
        approved['packages'].append(dict(package=(org+'::' if org else '')+name, version=version,
            repository='home', registry=registry, sha256=meta['index']['sha256sum']))
    approval.write_text(json.dumps(approved, indent=2)+'\n', encoding='utf-8')
    approval_before = approval.read_bytes()
    try:
        run('network-create', ['docker', 'network', 'create', '--internal', '--label',
            'cjrepomesh.snapshot-proof='+proof, network]); network_created = True
        net = json.loads(run('network-inspect', ['docker', 'network', 'inspect', network], log=False))[0]
        assert net['Internal'] is True
        (report/'isolation.yaml').write_text(json.dumps(dict(services=dict(cjrepo=dict(networks=dict(
            isolated=dict(aliases=['snapshot-registry'])))), networks=dict(isolated=dict(external=True, name=network)))))
        original, original_values = configure('original')
        compose(original, original_values, 'original-up', 'up', '-d', '--no-build', '--pull', 'never')
        original_id = container(original, original_values); healthy(original_id)
        run('original-alias', ['docker', 'network', 'connect', '--alias', 'snapshot-registry', network, original_id])
        for (org, name, version), (_, artifact, body) in packages.items():
            path = '/pkg/'+name+('?organization='+org if org else '')
            status = http(original_values, path, token=original_values['CJREPO_PUBLISH_TOKEN'], data=body)[0]
            assert status == 200, 'owned fixture publish returned status '+str(status)
            assert http(original_values, f'/pkg/{name}/{version}'+('?organization='+org if org else ''),
                        token=original_values['CJREPO_READ_TOKEN']) == (200, artifact)
        passed('real-transitive-organization-default-and-unselected-packages-published')
        compose(original, original_values, 'stop-original', 'down')
        backup = report/'stopped-backup'
        run('backup', [sys.executable, original/'maintenance.py', 'backup', '--output', backup], directory=original)
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in backup.iterdir()}
        original_env = (original/'.env').read_bytes()
        passed('actual-stopped-backup-retains-original-data-and-private-configuration')
        snapshot = report/'approved-snapshot'
        run('export', snapshot_command(original, 'export', '--backup', backup, '--baseline', approval, '--output', snapshot))
        run('verify', snapshot_command(original, 'verify', '--snapshot', snapshot, '--baseline', approval))
        value = json.loads((snapshot/'snapshot.json').read_text())
        expected = {'index/default/me/sh/meshdep', 'index/company/ba/se/baselineparent',
                    'artifacts/default/meshdep/1.0.0/meshdep-1.0.0.cjp',
                    'artifacts/company/baselineparent/1.0.0/baselineparent-1.0.0.cjp'}
        assert set(value['storage']['files']) == expected and {p.name for p in snapshot.iterdir()} == {'data.tar', 'snapshot.json'}
        assert all(secret.encode() not in path.read_bytes() for path in snapshot.iterdir() for secret in hidden)
        snapshot_before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in snapshot.iterdir()}
        passed('snapshot-is-exact-approved-set-without-other-version-package-or-runtime-configuration')
        incomplete = report/'incomplete-approval.json'
        incomplete.write_text(json.dumps(dict(formatVersion=1, packages=approved['packages'][:1])))
        refused = report/'missing-dependency-output'
        run('missing-dependency', snapshot_command(original, 'export', '--backup', backup, '--baseline', incomplete,
            '--output', refused), success=False)
        assert not refused.exists()
        passed('missing-transitive-dependency-refused-before-output')
        target, target_values = configure('seeded')
        target_env = (target/'.env').read_bytes()
        volumes = run('volumes-before-refusals', ['docker', 'volume', 'ls', '--quiet'], log=False)
        damaged = report/'damaged-snapshot'; shutil.copytree(snapshot, damaged)
        (damaged/'data.tar').write_bytes(b'synthetic damaged archive')
        drift = report/'drift-approval.json'; drift_value = json.loads(approval.read_text())
        drift_value['packages'][0]['sha256'] = '0'*64; drift.write_text(json.dumps(drift_value))
        for label, snap, approved_file in (('damaged', damaged, approval), ('drift', snapshot, drift)):
            run(label+'-seed-refused', snapshot_command(target, 'seed', '--snapshot', snap, '--baseline', approved_file), success=False)
        assert run('volumes-after-refusals', ['docker', 'volume', 'ls', '--quiet'], log=False) == volumes
        assert (target/'.env').read_bytes() == target_env
        passed('corruption-and-external-approval-drift-refused-without-volume-or-configuration-mutation')
        run('seed', snapshot_command(target, 'seed', '--snapshot', snapshot, '--baseline', approval), directory=target)
        seeded = json.loads((target/'snapshot-import.json').read_text())
        assert seeded['serviceStarted'] is False and seeded['storage'] == value['storage']
        assert (target/'.env').read_bytes() == target_env and not container(target, target_values)
        passed('new-labelled-volume-seeded-verified-and-left-stopped-with-new-receiver-credentials')
        run('repeat-seed-refused', snapshot_command(target, 'seed', '--snapshot', snapshot, '--baseline', approval), success=False)
        assert json.loads((target/'snapshot-import.json').read_text()) == seeded
        assert (target/'.env').read_bytes() == target_env
        passed('repeat-seed-refused-with-existing-volume-and-import-record-retained')
        compose(target, target_values, 'isolated-up', 'up', '-d', '--no-build', '--pull', 'never', isolated=True)
        target_id = container(target, target_values, isolated=True); item = healthy(target_id)
        assert set(item['NetworkSettings']['Networks']) == {network}
        assert not compose(original, original_values, 'original-offline', 'ps', '-a', '-q').strip()
        passed('source-offline-and-seeded-registry-confined-to-internal-network')

        def cold_job(label, approved_file, succeed):
            job = report/label; (job/'src').mkdir(parents=True)
            (job/'cjpm.toml').write_text('[package]\ncjc-version = "1.0.0"\nname = "snapshot_app"\nversion = "1.0.0"\noutput-type = "executable"\n\n[dependencies]\n"company::baselineparent" = "1.0.0"\n')
            (job/'src/main.cj').write_text('package snapshot_app\nimport company::baselineparent.*\nmain(): Int64 { println(baselineMarker()); return 0 }\n')
            (job/'cangjie-repo.toml').write_text('[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "'+registry+'"\ntoken-env = "CJREPOMESH_SNAPSHOT_READ_TOKEN"\n')
            (job/'check.py').write_text('''import json,os,urllib.request,urllib.error
base="http://snapshot-registry:8080"
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path,auth=True):
 req=urllib.request.Request(base+path,headers={"Authorization":os.environ["CJREPOMESH_SNAPSHOT_READ_TOKEN"]} if auth else {})
 try:
  with opener.open(req,timeout=5) as response:return response.status,response.read()
 except urllib.error.HTTPError as error:return error.code,error.read()
assert get("/index/me/sh/meshdep",False)[0]==401
assert get("/pkg/teamhello/1.0.0?organization=company")[0]==404
assert get("/pkg/meshdep/2.0.0")[0]==404
status,body=get("/index/me/sh/meshdep");assert status==200
assert [json.loads(line)["version"] for line in body.splitlines()]==["1.0.0"]
print("PASS private reads and unselected package/version unavailable")
''')
            identifier = proof+'-'+label
            command = ['docker', 'create', '--pull=never', '--name', identifier, '--network', network, '--read-only',
                '--label', 'cjrepomesh.snapshot-proof='+proof, '--cap-drop=ALL', '--security-opt', 'no-new-privileges:true',
                '--tmpfs', '/tmp:size=128m,mode=1777', '--workdir', '/job']
            for host, destination in ((job, '/job'), (args.client_bundle.resolve(), '/client'),
                    (args.client_sdk.resolve(), '/opt/cangjie'), (args.native.resolve(), '/opt/native'),
                    (approved_file, '/approved/source.json')):
                command += ['--mount', f'type=bind,source={host},target={destination}'+('' if host == job else ',readonly')]
            for host in sorted((args.native/'system').rglob('*')):
                if host.is_file():
                    command += ['--mount', f'type=bind,source={host.resolve()},target=/{host.relative_to(args.native/"system").as_posix()},readonly']
            script = ('source /opt/cangjie/envsetup.sh; export PATH="/opt/native/bin:$PATH" LD_LIBRARY_PATH="/opt/native/lib:$LD_LIBRARY_PATH"; '
                      'set -u; python3 check.py; /client/run.sh repo supports source-baseline-v1; /client/run.sh build; ./target/release/bin/main')
            command += ['--env', 'HOME=/job/.home', '--env', 'CJREPOMESH_SOURCE_BASELINE=/approved/source.json',
                '--env', 'CJREPOMESH_SNAPSHOT_READ_TOKEN='+target_values['CJREPO_READ_TOKEN'],
                '--entrypoint', '/bin/bash', image, '-ec', script]
            run(label+'-create', command); jobs.append(identifier)
            run(label+'-run', ['docker', 'start', '--attach', identifier], success=None, timeout=180)
            text = (report/(label+'-run.log')).read_text(encoding='utf-8')
            item = json.loads(run(label+'-state', ['docker', 'inspect', identifier], log=False))[0]
            assert set(item['NetworkSettings']['Networks']) == {network}
            assert (item['State']['ExitCode'] == 0) == succeed
            assert 'PASS private reads and unselected package/version unavailable' in text
            if succeed:
                assert 'baseline:high-1.0.0' in text
                assert json.loads((job/'cjpm-provenance.json').read_text()) == approved
                assert 'cjpm SHA-256 '+client['files']['cjpm']['sha256'] in text
            else:
                assert 'repository source baseline rejected' in text
                assert not (job/'cjpm-provenance.json').exists() and not (job/'target/release/bin/main').exists()

        cold_job('cold-consumer', approval, True)
        passed('full-client-cold-build-and-real-transitive-application-match-independent-readonly-approval',
               clientSha256=client['files']['cjpm']['sha256'])
        passed('anonymous-read-and-unselected-package-and-version-remain-unavailable')
        drift_before = drift.read_bytes(); cold_job('drift-consumer', drift, False)
        assert drift.read_bytes() == drift_before
        passed('separate-cold-consumer-rejects-source-drift-before-build-output')
        compose(target, target_values, 'recreate', 'up', '-d', '--force-recreate', '--no-build', '--pull', 'never', isolated=True)
        healthy(container(target, target_values, isolated=True))
        # A second valid build here would repeat the same checks; the persistent
        # volume is instead exported read-only and compared file-for-file.
        sys.path.insert(0, str(source/'deployment/portable'))
        try:
            maintenance = runpy.run_path(str(source/'deployment/portable/maintenance.py'))
            check = report/'seeded-after-recreation.tar'
            with check.open('xb') as stream:
                maintenance['helper'](image, seeded['volume'], '/bin/tar', '-C', '/var/lib/cjrepo', '-cf', '-', '.', readonly=True, stdout=stream)
            assert maintenance['archive_manifest'](check) == value['storage']
        finally:
            sys.path.remove(str(source/'deployment/portable'))
        assert (target/'.env').read_bytes() == target_env and (original/'.env').read_bytes() == original_env
        assert approval.read_bytes() == approval_before
        assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in backup.iterdir()}
        assert snapshot_before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in snapshot.iterdir()}
        passed('recreation-preserves-exact-seeded-storage-and-original-backup-snapshot-approval')
    except Exception as error:
        location = traceback.extract_tb(error.__traceback__)[-1]
        failure = safe_error(error, hidden)+' ['+Path(location.filename).name+':'+str(location.lineno)+']'
        print('FAIL '+failure, flush=True)
    finally:
        for identifier in reversed(jobs):
            try:
                item = json.loads(run('cleanup-inspect-'+identifier, ['docker', 'inspect', identifier], log=False))[0]
                assert item['Config']['Labels'].get('cjrepomesh.snapshot-proof') == proof
                finish_owned(lambda: run('retained-'+identifier, ['docker', 'logs', identifier]),
                    lambda: run('remove-'+identifier, ['docker', 'rm', '--force', identifier]), cleanup, kind='consumer')
            except Exception: cleanup.append('owned consumer cleanup failed')
        for root, values in reversed(projects):
            finish_owned(lambda: compose(root, values, 'retained-'+root.name, 'logs', '--no-color', isolated=root.name == 'seeded'),
                lambda: compose(root, values, 'remove-'+root.name, 'down',
                    *([] if failure or cleanup or len(stages) != 12 else ['-v']), isolated=root.name == 'seeded'),
                cleanup, kind='registry')
        if network_created:
            try:
                item = json.loads(run('cleanup-network-identity', ['docker', 'network', 'inspect', network], log=False))[0]
                assert item['Labels'].get('cjrepomesh.snapshot-proof') == proof
                run('remove-network', ['docker', 'network', 'rm', network])
            except Exception: cleanup.append('owned internal network cleanup failed')
    summary = dict(success=not failure and not cleanup and len(stages) == 12, passed=len(stages), total=12,
        seconds=round(time.monotonic()-started, 2), stages=stages, error=failure, cleanupErrors=cleanup,
        image=server['image'], clientSha256=client['files']['cjpm']['sha256'])
    (report/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(success=summary['success'], passed=len(stages), total=12, cleanupErrors=cleanup)), flush=True)
    return 0 if summary['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
