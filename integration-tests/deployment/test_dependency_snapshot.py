"""Approved-set snapshot contracts, using synthetic private files only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import shutil
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

    def test_snapshot_output_cannot_be_inside_a_source_backup(self):
        before = {path.name: path.read_bytes() for path in self.backup.iterdir()}
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.module.export_snapshot(self.backup, self.approval, self.backup/'nested-output')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.backup.iterdir()})
        sources = self.origin_graph()
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.module.export_set(sources, self.approval, self.backup/'nested-set')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.backup.iterdir()})

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
                 {'maintenance.py', 'snapshot.py'}),
                ({'maintenance': 'cold-backup-v1', 'dependencySnapshot': 'approved-origins-v2'},
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

    def origin_graph(self):
        self.assertTrue(callable(getattr(self.module, 'export_set', None)),
                        'full-approval origin snapshot set is not implemented')
        self.approved['packages'][1]['repository'] = 'internal'
        self.approved['packages'][1]['registry'] = 'https://private.example/team'
        self.approval.write_text(json.dumps(self.approved), encoding='utf-8')
        return {'home': self.backup, 'internal': self.backup}

    def test_origin_set_keeps_full_approval_and_cross_origin_dependency(self):
        sources = self.origin_graph(); before = self.approval.read_bytes()
        value = self.module.export_set(sources, self.approval, self.output)
        self.assertEqual('cjrepomesh-dependency-snapshot-set', value['kind'])
        self.assertEqual(hashlib.sha256(before).hexdigest(), value['baselineSha256'])
        self.assertEqual(2, len(value['origins']))
        self.assertEqual({'snapshot-set.json'} | {item['directory'] for item in value['origins']},
                         {path.name for path in self.output.iterdir()})
        combined = set()
        for origin in value['origins']:
            child = self.output/origin['directory']
            selected = self.module.verify_snapshot(child, self.approval)
            self.assertEqual(2, selected['formatVersion'])
            self.assertEqual('exact-registry-v1', selected['selection'])
            self.assertEqual(origin['registry'], selected['registry'])
            self.assertEqual(value['baselineSha256'], selected['baselineSha256'])
            self.assertEqual({'snapshot.json', 'data.tar'}, {path.name for path in child.iterdir()})
            expected = {path for item in self.approved['packages'] if item['registry'] == origin['registry']
                        for path in self.paths(item['package'])}
            self.assertEqual(expected, set(selected['storage']['files']))
            combined.update(expected)
        self.assertEqual(4, len(combined))
        self.assertEqual(before, self.approval.read_bytes())
        self.assertEqual(value, self.module.verify_set(self.output, self.approval))

    def test_origin_set_requires_exact_mapping_before_creating_output(self):
        sources = self.origin_graph()
        for mapping in ({}, {'home': self.backup}, {**sources, 'unapproved': self.backup}):
            with self.subTest(mapping=list(mapping)):
                with self.assertRaises(ValueError): self.module.export_set(mapping, self.approval, self.output)
                self.assertFalse(self.output.exists())
        self.approved['packages'][1]['registry'] = REGISTRY
        self.approval.write_text(json.dumps(self.approved))
        with self.assertRaises(ValueError): self.module.export_set(sources, self.approval, self.output)
        self.assertFalse(self.output.exists())
        value = self.module.export_set({'internal': self.backup}, self.approval, self.output)
        self.assertEqual(1, len(value['origins']), 'same-URL config aliases need one storage snapshot')

    def test_all_origins_preflight_before_output_even_if_later_backup_fails(self):
        self.origin_graph(); good = self.backup
        self.backup = self.root/'bad-home'; shutil.copytree(good, self.backup)
        self.artifacts['meshdep'] += b'wrong-source-bytes'; self.write_backup()
        with self.assertRaisesRegex(ValueError, 'approved SHA-256'):
            self.module.export_set({'internal': good, 'home': self.backup}, self.approval, self.output)
        self.assertFalse(self.output.exists())

    def test_origin_set_rejects_forged_missing_duplicate_and_swapped_origins(self):
        sources = self.origin_graph(); value = self.module.export_set(sources, self.approval, self.output)
        path = self.output/'snapshot-set.json'
        variants = []
        missing = copy.deepcopy(value); missing['origins'] = missing['origins'][:1]; variants.append(missing)
        duplicate = copy.deepcopy(value); duplicate['origins'][1]['registry'] = duplicate['origins'][0]['registry']; variants.append(duplicate)
        swapped = copy.deepcopy(value)
        swapped['origins'][0]['registry'], swapped['origins'][1]['registry'] = swapped['origins'][1]['registry'], swapped['origins'][0]['registry']
        variants.append(swapped)
        for mutation in ({'directory': '../outside'}, {'snapshotManifestSha256': '0'*64}):
            wrong = copy.deepcopy(value); wrong['origins'][0].update(mutation); variants.append(wrong)
        for wrong in variants:
            path.write_text(json.dumps(wrong))
            with self.assertRaises(ValueError): self.module.verify_set(self.output, self.approval)
        path.write_text(json.dumps(value)); (self.output/'unapproved').mkdir()
        with self.assertRaises(ValueError): self.module.verify_set(self.output, self.approval)

    def test_component_resealing_cannot_expand_into_another_origin(self):
        sources = self.origin_graph(); value = self.module.export_set(sources, self.approval, self.output)
        set_root = self.output
        origin = next(item for item in value['origins'] if item['registry'] != REGISTRY)
        self.output = set_root/origin['directory']
        with tarfile.open(self.output/'data.tar', 'a:') as archive:
            data = self.artifacts['meshdep']; item = tarfile.TarInfo(self.paths('meshdep')[1])
            item.size = len(data); item.mode = 0o644; archive.addfile(item, io.BytesIO(data))
        self.reseal_snapshot()
        origin['snapshotManifestSha256'] = hashlib.sha256((self.output/'snapshot.json').read_bytes()).hexdigest()
        (set_root/'snapshot-set.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.module.verify_set(set_root, self.approval)

    def test_new_components_require_new_capability_before_docker(self):
        sources = self.origin_graph(); value = self.module.export_set(sources, self.approval, self.output)
        child = self.output/value['origins'][0]['directory']
        target = self.root/'target'; target.mkdir()
        manifest = dict(image=IMAGE, dependencySnapshot='approved-set-v1')
        with patch.object(self.module, 'verify_bundle', return_value=manifest), patch.object(
                self.module, 'deployment', side_effect=AssertionError('must refuse before Docker')) as deploy:
            with self.assertRaises(ValueError): self.module.seed(target, child, self.approval)
            deploy.assert_not_called()

    def test_ambiguous_repository_name_and_duplicate_cli_sources_reject(self):
        self.origin_graph(); self.approved['packages'][1]['repository'] = 'home'
        self.approval.write_text(json.dumps(self.approved))
        with self.assertRaises(ValueError):
            self.module.export_set({'home': self.backup}, self.approval, self.output)
        self.assertFalse(self.output.exists())
        nonce = 'private-source-path-marker'
        result = subprocess.run([sys.executable, SOURCE/'snapshot.py', 'export-set', '--source', 'home', nonce,
            '--source', 'home', nonce, '--baseline', self.approval, '--output', self.output], capture_output=True, text=True)
        self.assertEqual(1, result.returncode)
        self.assertNotIn(nonce, result.stdout+result.stderr)


class SnapshotAcceptanceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_parent = SOURCE.parents[1]/'integration-tests/.tmp'
        self.temporary_parent.mkdir(parents=True, exist_ok=True)

    def recorded_runner(self):
        functions = runpy.run_path(str(SOURCE.parents[1]/'integration-tests/deployment/dependency_snapshot.py'))
        self.assertIn('run_recorded', functions, 'creation must register success before recording diagnostics')
        return functions['run_recorded']

    def test_created_resources_register_before_real_log_write_failure(self):
        runner = self.recorded_runner()
        for kind in ('network', 'consumer'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.temporary_parent) as temporary:
                root = Path(temporary)
                (root/'create.log').mkdir()  # A real output failure after the child exits successfully.
                owned = []
                with self.assertRaises(OSError):
                    runner('create', [sys.executable, '-c', 'print("created")'], directory=root,
                        report=root, environment=None, hidden=[], created=lambda: owned.append(kind))
                self.assertEqual([kind], owned)

    def test_failed_creation_does_not_register_even_when_log_write_fails(self):
        runner = self.recorded_runner()
        with tempfile.TemporaryDirectory(dir=self.temporary_parent) as temporary:
            root = Path(temporary); (root/'create.log').mkdir(); owned = []
            with self.assertRaises(OSError):
                runner('create', [sys.executable, '-c', 'raise SystemExit(4)'], directory=root,
                    report=root, environment=None, hidden=[], created=lambda: owned.append('uncreated'))
            self.assertEqual([], owned)

    def test_recorded_success_keeps_output_redaction_and_exactly_once_registration(self):
        runner = self.recorded_runner()
        with tempfile.TemporaryDirectory(dir=self.temporary_parent) as temporary:
            root = Path(temporary); owned = []
            def created():
                self.assertFalse((root/'create.log').exists())
                owned.append('created')
            output = runner('create', [sys.executable, '-c',
                'import sys; print("synthetic-private-token"); print("stderr", file=sys.stderr)'],
                directory=root, report=root, environment=None, hidden=['synthetic-private-token'], created=created)
            self.assertEqual(['created'], owned)
            self.assertEqual('synthetic-private-token\n', output)
            self.assertEqual('[REDACTED]\nstderr\n', (root/'create.log').read_text())

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
