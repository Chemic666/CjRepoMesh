"""Approved-set snapshot contracts, using synthetic private files only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'deployment/portable'
IMAGE = dict(id='sha256:' + 'a'*64, tag='cjrepomesh-portable:sha256-' + 'a'*64,
             os='linux', architecture='amd64', serverSha256='b'*64)
REGISTRY = 'https://registry.example/team'
PROJECT = 'cjrepomesh-' + '1'*16
CONFIG = (f'COMPOSE_PROJECT_NAME={PROJECT}\nCJREPO_HOST_PORT=18743\n'
          'CJREPO_READ_TOKEN=private-read-not-for-snapshot\n'
          'CJREPO_PUBLISH_TOKEN=private-write-not-for-snapshot\nCJREPO_CA_SHA256=\n').encode()


class DependencySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((SOURCE/'snapshot.py').is_file(), 'approved dependency snapshot is not implemented')
        sys.path.insert(0, str(SOURCE))
        self.addCleanup(sys.path.remove, str(SOURCE))
        spec = importlib.util.spec_from_file_location('receiver_snapshot', SOURCE/'snapshot.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        parent = SOURCE.parents[1]/'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='snapshot-unit-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.approval = self.root/'approved.json'
        self.backup = self.root/'backup'
        self.output = self.root/'snapshot'
        self.indexes, self.artifacts = {}, {}
        packages = []
        for org, name, dependencies in (('', 'meshdep', []), ('company', 'parentpkg', ['meshdep']),
                                         ('company', 'unrelated', [])):
            full = (org+'::' if org else '')+name
            body = ('synthetic-cjp:'+full).encode()
            self.artifacts[full] = body
            checksum = hashlib.sha256(body).hexdigest()
            self.indexes[full] = dict(organization=org, name=name, version='1.0.0', sha256sum=checksum,
                dependencies=[dict(name=dep, require='1.0.0', target=None, type=None,
                                   **{'output-type': None}) for dep in dependencies],
                **{'test-dependencies': [], 'script-dependencies': [], 'yanked': False,
                   'cjc-version': '1.0.0', 'index-version': 1})
            if name != 'unrelated':
                packages.append(dict(package=full, version='1.0.0', repository='home', registry=REGISTRY, sha256=checksum))
        self.approved = dict(formatVersion=1, packages=packages)
        self.approval.write_text(json.dumps(self.approved), encoding='utf-8')
        self.write_backup()

    def paths(self, full):
        org, name = full.split('::') if '::' in full else ('default', full)
        return (f'index/{org}/{name[:2]}/{name[2:4]}/{name}',
                f'artifacts/{org}/{name}/1.0.0/{name}-1.0.0.cjp')

    def write_backup(self, additions=()):
        self.backup.mkdir(exist_ok=True)
        with tarfile.open(self.backup/'data.tar', 'w:') as archive:
            for full in self.indexes:
                index, artifact = self.paths(full)
                selected = self.indexes[full]
                old = dict(selected, version='0.9.0', sha256sum='c'*64)
                for name, data in ((index, (json.dumps(old)+'\n'+json.dumps(selected)+'\n').encode()),
                                   (artifact, self.artifacts[full])):
                    item = tarfile.TarInfo('./'+name); item.size = len(data); item.mode = 0o644
                    archive.addfile(item, io.BytesIO(data))
            for item, data in additions:
                archive.addfile(item, io.BytesIO(data) if data else None)
        (self.backup/'.env').write_bytes(CONFIG)
        self.reseal_backup()

    def reseal_backup(self):
        value = dict(formatVersion=1, kind='cjrepomesh-cold-backup', image=IMAGE,
            source=dict(project=PROJECT, volume=PROJECT+'_cjrepo-data', port=18743), caSha256='',
            storage=self.module.archive_manifest(self.backup/'data.tar'), files={})
        for name in ('.env', 'data.tar'):
            path = self.backup/name
            value['files'][name] = dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (self.backup/'backup.json').write_text(json.dumps(value), encoding='utf-8')

    def export(self):
        return self.module.export_snapshot(self.backup, self.approval, self.output)

    def reseal_snapshot(self):
        path = self.output/'snapshot.json'; value = json.loads(path.read_text())
        value['storage'] = self.module.archive_manifest(self.output/'data.tar')
        value['files']['data.tar'] = dict(bytes=(self.output/'data.tar').stat().st_size,
            sha256=hashlib.sha256((self.output/'data.tar').read_bytes()).hexdigest())
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_export_is_exact_selected_set_without_configuration_or_other_versions(self):
        source_before = {p.name: p.read_bytes() for p in self.backup.iterdir()}
        approved_before = self.approval.read_bytes()
        value = self.export()
        self.assertEqual({'snapshot.json', 'data.tar'}, {p.name for p in self.output.iterdir()})
        self.assertEqual(REGISTRY, value['registry'])
        self.assertEqual({path for full in ('meshdep', 'company::parentpkg') for path in self.paths(full)},
                         set(value['storage']['files']))
        with tarfile.open(self.output/'data.tar') as archive:
            for full in ('meshdep', 'company::parentpkg'):
                index, artifact = self.paths(full)
                self.assertEqual([self.indexes[full]], [json.loads(line) for line in archive.extractfile(index)])
                self.assertEqual(self.artifacts[full], archive.extractfile(artifact).read())
        for path in self.output.iterdir():
            self.assertNotIn(b'private-read-not-for-snapshot', path.read_bytes())
            self.assertNotIn(b'unrelated', path.read_bytes())
        self.assertEqual(source_before, {p.name: p.read_bytes() for p in self.backup.iterdir()})
        self.assertEqual(approved_before, self.approval.read_bytes())
        self.assertEqual(value, self.module.verify_snapshot(self.output, self.approval))

    def test_missing_unconditional_dependency_rejects_before_output(self):
        self.approved['packages'] = [p for p in self.approved['packages'] if p['package'] != 'meshdep']
        self.approval.write_text(json.dumps(self.approved))
        with self.assertRaisesRegex(ValueError, 'dependency'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_multiple_origins_and_unsafe_approval_fields_reject(self):
        variants = []
        for field, invalid in (('registry', 'https://other.example'), ('registry', 'https://private:secret@registry.example'),
                               ('registry', 'https://registry.example?token=secret'), ('package', '../meshdep'),
                               ('package', 'default::meshdep'), ('version', '../1'), ('sha256', 'A'*64),
                               ('repository', ''), ('version', True)):
            value = copy.deepcopy(self.approved); value['packages'][0][field] = invalid; variants.append(value)
        variants += [dict(formatVersion=True, packages=[]), dict(formatVersion=1, packages=[]),
                     dict(formatVersion=1, packages=self.approved['packages']*2)]
        for value in variants:
            with self.subTest(value=value):
                self.approval.write_text(json.dumps(value))
                with self.assertRaises(ValueError): self.export()
                self.assertFalse(self.output.exists())

    def test_duplicate_json_keys_and_oversized_approval_reject(self):
        for data in (b'{"formatVersion":1,"formatVersion":1,"packages":[]}', b' '* (1024*1024+1)):
            self.approval.write_bytes(data)
            with self.assertRaises(ValueError): self.export()
            self.assertFalse(self.output.exists())

    def test_index_identity_checksum_yanked_and_dependency_type_reject(self):
        original = copy.deepcopy(self.indexes)
        for field, invalid in (('organization', 'wrong'), ('sha256sum', 'd'*64), ('yanked', True),
                               ('dependencies', 'invalid'), ('index-version', True)):
            self.indexes = copy.deepcopy(original); self.indexes['company::parentpkg'][field] = invalid
            self.write_backup()
            with self.subTest(field=field):
                with self.assertRaises(ValueError): self.export()
                self.assertFalse(self.output.exists())

    def test_artifact_hash_mismatch_rejects_even_with_valid_backup_hashes(self):
        self.artifacts['meshdep'] += b'changed'; self.write_backup()
        with self.assertRaises(ValueError): self.export()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir(); (self.output/'owner').write_bytes(b'keep')
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(b'keep', (self.output/'owner').read_bytes())

    def test_verification_requires_exact_external_approval_bytes(self):
        self.export(); self.approval.write_bytes(self.approval.read_bytes()+b'\n')
        with self.assertRaises(ValueError): self.module.verify_snapshot(self.output, self.approval)

    def test_corrupt_archive_and_unlisted_files_reject(self):
        self.export(); original = (self.output/'data.tar').read_bytes()
        (self.output/'data.tar').write_bytes(b'corrupt')
        with self.assertRaises(ValueError): self.module.verify_snapshot(self.output, self.approval)
        (self.output/'data.tar').write_bytes(original); (self.output/'.env').write_bytes(CONFIG)
        with self.assertRaises(ValueError): self.module.verify_snapshot(self.output, self.approval)

    def test_resealed_unapproved_storage_and_malicious_archive_reject(self):
        self.export(); original = (self.output/'data.tar').read_bytes()
        for name, kind in (('artifacts/default/unapproved/1/unapproved-1.cjp', tarfile.REGTYPE),
                            ('../../escape', tarfile.REGTYPE), ('index/link', tarfile.SYMTYPE)):
            (self.output/'data.tar').write_bytes(original)
            with tarfile.open(self.output/'data.tar', 'a:') as archive:
                item = tarfile.TarInfo(name); item.type = kind; item.mode = 0o644
                if kind == tarfile.SYMTYPE: item.linkname = '/outside'
                archive.addfile(item)
            try: self.reseal_snapshot()
            except ValueError: continue
            with self.assertRaises(ValueError): self.module.verify_snapshot(self.output, self.approval)

    def test_seed_bad_input_never_calls_docker_or_changes_target(self):
        target = self.root/'target'; target.mkdir(); (target/'.env').write_bytes(CONFIG)
        with patch.object(self.module, 'deployment') as deployment:
            with self.assertRaises(ValueError): self.module.seed(target, self.output, self.approval)
            deployment.assert_not_called()
        self.assertEqual(CONFIG, (target/'.env').read_bytes())

    def test_seed_refuses_proxy_configuration_before_new_volume(self):
        self.export()
        manifest = dict(image=IMAGE, dependencySnapshot='approved-set-v1')
        target = self.root/'target'; target.mkdir()
        values = dict(COMPOSE_PROJECT_NAME=PROJECT, CJREPO_UPSTREAM='https://upstream.example')
        with patch.object(self.module, 'verify_bundle', return_value=manifest), patch.object(
                self.module, 'deployment', return_value=(manifest, CONFIG, values, None)), patch.object(
                self.module, 'create_restore_volume', side_effect=AssertionError('must not create a volume')) as create:
            with self.assertRaisesRegex(ValueError, 'Hosted'):
                self.module.seed(target, self.output, self.approval)
            create.assert_not_called()

    def test_cli_diagnostic_does_not_echo_sensitive_input(self):
        nonce = 'private-diagnostic-marker'; self.approval.write_text(nonce)
        result = subprocess.run([sys.executable, SOURCE/'snapshot.py', 'export', '--backup', self.backup,
            '--baseline', self.approval, '--output', self.root/nonce], capture_output=True, text=True)
        self.assertEqual(1, result.returncode)
        self.assertNotIn(nonce, result.stdout+result.stderr)
        self.assertIn('FAIL:', result.stdout)

    def test_bundle_capability_requires_snapshot_file_and_preserves_legacy_sets(self):
        target = self.root/'bundle'; target.mkdir()
        legacy = {'image.tar', 'compose.yaml', 'configure.py', 'verify.py', 'README.md', 'LICENSE'}
        for capabilities, extra in (({}, set()), ({'maintenance': 'cold-backup-v1'}, {'maintenance.py'}),
                ({'maintenance': 'cold-backup-v1', 'dependencySnapshot': 'approved-set-v1'},
                 {'maintenance.py', 'snapshot.py'})):
            names = legacy | extra
            for name in names: (target/name).write_bytes(b'synthetic-bundle-file')
            value = dict(formatVersion=1, image=IMAGE, files={name: dict(bytes=(target/name).stat().st_size,
                sha256=hashlib.sha256((target/name).read_bytes()).hexdigest()) for name in names}, **capabilities)
            (target/'manifest.json').write_text(json.dumps(value))
            self.assertEqual(value, self.module.verify_bundle(target))
        for mutation in ({'dependencySnapshot': 'unknown'}, {'maintenance': None}):
            bad = dict(value, **mutation); (target/'manifest.json').write_text(json.dumps(bad))
            with self.assertRaises(ValueError): self.module.verify_bundle(target)
        (target/'manifest.json').write_text(json.dumps(value)); (target/'snapshot.py').unlink()
        with self.assertRaises((ValueError, OSError)): self.module.verify_bundle(target)


class SnapshotAcceptanceCleanupTests(unittest.TestCase):
    def test_failed_log_capture_still_stops_owned_resources_and_preserves_failure_state(self):
        functions = runpy.run_path(str(SOURCE.parents[1]/'integration-tests/deployment/dependency_snapshot.py'))
        self.assertTrue('finish_owned' in functions, 'snapshot acceptance has no independent stop after log failure')
        for kind in ('consumer', 'registry'):
            calls, errors = [], []
            def capture():
                calls.append('capture'); raise OSError('private-log-body')
            def stop():
                calls.append('stop-preserving-volume' if errors else 'normal-stop')
            functions['finish_owned'](capture, stop, errors, kind=kind)
            self.assertEqual(['capture', 'stop-preserving-volume'], calls)
            self.assertEqual(['owned '+kind+' log capture failed'], errors)
            self.assertNotIn('private-log-body', str(errors))


if __name__ == '__main__':
    unittest.main()
