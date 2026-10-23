"""Receiver maintenance contracts; all files and credentials are synthetic."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'deployment/portable'
PROJECT = 'cjrepomesh-' + '1' * 16
NEW_PROJECT = 'cjrepomesh-' + '2' * 16
IMAGE = dict(id='sha256:' + 'a' * 64,
             tag='cjrepomesh-portable:sha256-' + 'a' * 64,
             os='linux', architecture='amd64', serverSha256='b' * 64)
CONFIG = (f'COMPOSE_PROJECT_NAME={PROJECT}\nCJREPO_HOST_PORT=18743\n'
          'CJREPO_READ_TOKEN=synthetic-read-value\n'
          'CJREPO_PUBLISH_TOKEN=synthetic-publish-value\n'
          'CJREPO_CA_SHA256=\nCJREPO_UPSTREAM=https://trusted.example/registry\n').encode()


class PortableMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((SOURCE/'maintenance.py').is_file(),
                        'receiver maintenance entry point is not implemented')
        sys.path.insert(0, str(SOURCE))
        spec = importlib.util.spec_from_file_location('receiver_maintenance', SOURCE/'maintenance.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        parent = SOURCE.parents[1]/'integration-tests/.tmp'
        parent.mkdir(exist_ok=True, parents=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='maintenance-unit-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(sys.path.remove, str(SOURCE))
        self.root = Path(self.temporary.name)

    def tar(self, entries, name='data.tar'):
        path = self.root/name
        with tarfile.open(path, 'w:') as archive:
            for name, data, kind in entries:
                item = tarfile.TarInfo(name)
                item.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
                item.type = kind
                if kind in (tarfile.LNKTYPE, tarfile.SYMTYPE):
                    item.linkname = '/outside'
                item.size = len(data) if kind == tarfile.REGTYPE else 0
                archive.addfile(item, io.BytesIO(data) if item.size else None)
        return path

    def snapshot(self):
        archive = self.tar([('.', b'', tarfile.DIRTYPE),
                            ('./index', b'', tarfile.DIRTYPE),
                            ('./index/default', b'', tarfile.DIRTYPE),
                            ('./index/default/pkg', b'index', tarfile.REGTYPE),
                            ('./artifacts', b'', tarfile.DIRTYPE),
                            ('./artifacts/pkg.cjp', b'package', tarfile.REGTYPE)])
        (self.root/'.env').write_bytes(CONFIG)
        manifest = dict(formatVersion=1, kind='cjrepomesh-cold-backup', image=IMAGE,
                        source=dict(project=PROJECT, volume=PROJECT+'_cjrepo-data', port=18743),
                        caSha256='', storage=self.module.archive_manifest(archive), files={})
        for name in ('data.tar', '.env'):
            data = (self.root/name).read_bytes()
            manifest['files'][name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (self.root/'backup.json').write_text(json.dumps(manifest), encoding='utf-8')
        return manifest

    def test_archive_covers_full_regular_file_set(self):
        archive = self.tar([('.', b'', tarfile.DIRTYPE), ('./index', b'', tarfile.DIRTYPE),
                            ('./index/pkg', b'hello', tarfile.REGTYPE)])
        value = self.module.archive_manifest(archive)
        self.assertEqual(value['files'], {'index/pkg': dict(bytes=5,
                         sha256=hashlib.sha256(b'hello').hexdigest())})
        self.assertEqual(value['directories'], ['index'])

    def test_archive_rejects_unsafe_names_and_types(self):
        for index, (name, kind) in enumerate([
                ('../escape', tarfile.REGTYPE), ('/index/pkg', tarfile.REGTYPE),
                ('index/../../escape', tarfile.REGTYPE), ('index\\pkg', tarfile.REGTYPE),
                ('other/file', tarfile.REGTYPE), ('index/link', tarfile.SYMTYPE),
                ('index/hard', tarfile.LNKTYPE), ('index/pipe', tarfile.FIFOTYPE)]):
            with self.subTest(name=name):
                archive = self.tar([(name, b'x', kind)], f'bad-{index}.tar')
                with self.assertRaises(ValueError):
                    self.module.archive_manifest(archive)

    def test_archive_rejects_duplicate_and_parent_file_collision(self):
        for entries in ([('index/pkg', b'x', tarfile.REGTYPE),
                         ('./index/pkg', b'y', tarfile.REGTYPE)],
                        [('index/pkg', b'x', tarfile.REGTYPE),
                         ('index/pkg/child', b'y', tarfile.REGTYPE)]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.module.archive_manifest(self.tar(entries))

    def test_archive_root_headers_are_unique_and_have_safe_modes(self):
        for index, headers in enumerate(([('.', 0o755), ('./', 0o755)], [('.', 0o4777)])):
            path = self.root/f'root-{index}.tar'
            with tarfile.open(path, 'w:') as archive:
                for name, mode in headers:
                    item = tarfile.TarInfo(name)
                    item.type, item.mode = tarfile.DIRTYPE, mode
                    archive.addfile(item)
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                self.module.archive_manifest(path)

    def test_backup_round_trip_verification_needs_no_docker(self):
        expected = self.snapshot()
        with patch.object(self.module, 'docker', side_effect=AssertionError('Docker must not run')):
            self.assertEqual(self.module.verify_backup(self.root), expected)

    def test_corrupt_or_missing_backup_preserves_inputs(self):
        self.snapshot()
        before = (self.root/'.env').read_bytes()
        (self.root/'data.tar').write_bytes(b'damaged-private-input')
        with self.assertRaises(ValueError) as caught:
            self.module.verify_backup(self.root)
        self.assertNotIn('synthetic-read-value', str(caught.exception))
        self.assertEqual((self.root/'.env').read_bytes(), before)
        (self.root/'data.tar').unlink()
        with self.assertRaises(ValueError):
            self.module.verify_backup(self.root)

    def test_backup_rejects_ambiguous_version_and_file_set(self):
        manifest = self.snapshot()
        for replacement in (True, 2, '1'):
            manifest['formatVersion'] = replacement
            (self.root/'backup.json').write_text(json.dumps(manifest))
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.module.verify_backup(self.root)
        manifest['formatVersion'] = 1
        manifest['files']['../outside'] = manifest['files']['.env']
        (self.root/'backup.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.module.verify_backup(self.root)

    def test_restore_configuration_preserves_credentials_ca_and_registry(self):
        result = self.module.restored_configuration(CONFIG, NEW_PROJECT, None)
        self.assertEqual(result, CONFIG.replace(PROJECT.encode(), NEW_PROJECT.encode(), 1))
        changed_port = self.module.restored_configuration(CONFIG, NEW_PROJECT, 18744)
        self.assertEqual(changed_port, result.replace(b'18743', b'18744', 1))

    def test_configuration_rejects_duplicates_interpolation_and_quoting_without_values(self):
        for suffix in (b'CJREPO_READ_TOKEN=second\n', b'CJREPO_UPSTREAM=${PRIVATE_SECRET}\n',
                       b'CJREPO_UPSTREAM="quoted"\n', b'COMPOSE_FILE=other.yaml\n'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError) as caught:
                self.module.read_configuration(CONFIG + suffix)
            self.assertNotIn('synthetic-read-value', str(caught.exception))
            self.assertNotIn('PRIVATE_SECRET', str(caught.exception))
        for before in (CONFIG.replace(b'synthetic-read-value', b''),
                       CONFIG.replace(PROJECT.encode(), b'other'), CONFIG.replace(b'18743', b'99999')):
            with self.assertRaises(ValueError):
                self.module.read_configuration(before)

    def test_existing_backup_destination_is_refused_before_docker(self):
        output = self.root/'existing'
        output.mkdir()
        (output/'keep').write_bytes(b'old evidence')
        with patch.object(self.module, 'docker', side_effect=AssertionError('unexpected Docker call')):
            with self.assertRaises(ValueError):
                self.module.backup(self.root, output)
        self.assertEqual((output/'keep').read_bytes(), b'old evidence')

    def test_restore_refuses_existing_configuration_before_docker(self):
        source = self.root/'backup'
        source.mkdir()
        target = self.root/'target'
        target.mkdir()
        (target/'.env').write_bytes(b'original credentials')
        with patch.object(self.module, 'docker', side_effect=AssertionError('unexpected Docker call')):
            with self.assertRaises(ValueError):
                self.module.restore(target, source)
        self.assertEqual((target/'.env').read_bytes(), b'original credentials')

    def test_running_foreign_writer_blocks_backup(self):
        identifier = 'c' * 64
        writer = dict(State=dict(Running=True), Mounts=[dict(Type='volume', Name='owned-volume', RW=True)])
        with patch.object(self.module, 'docker', side_effect=[identifier, json.dumps([writer])]):
            with self.assertRaises(ValueError):
                self.module.require_stopped('owned-volume')

    def test_stopped_and_read_only_mounts_are_not_writers(self):
        for running, writable in ((False, True), (True, False)):
            item = dict(State=dict(Running=running),
                        Mounts=[dict(Type='volume', Name='owned-volume', RW=writable)])
            with self.subTest(running=running, writable=writable), patch.object(
                    self.module, 'docker', side_effect=['c' * 64, json.dumps([item])]):
                self.module.require_stopped('owned-volume')

    def bundle(self):
        target = self.root/'bundle'
        target.mkdir()
        names = ('image.tar', 'compose.yaml', 'configure.py', 'verify.py', 'maintenance.py', 'README.md', 'LICENSE')
        for name in names:
            source = SOURCE/name
            if source.is_file():
                shutil.copyfile(source, target/name)
            else:
                (target/name).write_bytes(b'synthetic distribution input')
        manifest = dict(formatVersion=1, maintenance='cold-backup-v1',
                        caConfiguration='pem-directory-v1', image=IMAGE, files={})
        for name in names:
            path = target/name
            manifest['files'][name] = dict(bytes=path.stat().st_size,
                                          sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (target/'manifest.json').write_text(json.dumps(manifest))
        return target, manifest

    def test_new_bundle_declares_and_verifies_maintenance(self):
        target, manifest = self.bundle()
        self.assertEqual(self.module.verify_bundle(target), manifest)
        (target/'maintenance.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.module.verify_bundle(target)

    def test_unknown_maintenance_capability_is_not_ignored_on_legacy_files(self):
        target, manifest = self.bundle()
        manifest['files'].pop('maintenance.py')
        manifest['maintenance'] = 'future-unrecognized-value'
        (target/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.module.verify_bundle(target)

    def test_existing_restore_volume_is_never_adopted(self):
        self.assertTrue(hasattr(self.module, 'create_restore_volume'),
                        'restore has no explicit pre-existing volume refusal')
        volume = NEW_PROJECT + '_cjrepo-data'
        with patch.object(self.module, 'docker', return_value=volume) as docker:
            with self.assertRaises(ValueError):
                self.module.create_restore_volume(IMAGE, NEW_PROJECT, 'owned-operation')
        self.assertEqual(docker.call_count, 1, 'existing volume must not be relabelled or extracted')

    def test_failed_helper_is_stopped_and_retained_for_diagnosis(self):
        for running in (False, True):
            calls = []
            def docker(*arguments, **options):
                calls.append(arguments)
                if arguments[0] == 'create':
                    return 'c' * 64
                if arguments[0] == 'start':
                    raise self.module.MaintenanceError('synthetic transfer failure')
                if arguments[0] == 'inspect':
                    return json.dumps([dict(Config=dict(Labels={self.module.LABEL: 'a' * 32}),
                                            State=dict(Running=running, ExitCode=1))])
                return ''
            with self.subTest(running=running), patch.object(self.module.secrets, 'token_hex', return_value='a' * 32), \
                    patch.object(self.module, 'docker', side_effect=docker):
                with self.assertRaises(ValueError):
                    self.module.helper(IMAGE['id'], 'owned-volume', '/bin/tar', readonly=True)
            self.assertNotIn('rm', [call[0] for call in calls], 'failed helper and its Docker logs must remain')
            self.assertEqual('stop' in [call[0] for call in calls], running)

    def test_successful_helper_is_still_cleaned_up(self):
        calls = []
        def docker(*arguments, **options):
            calls.append(arguments)
            if arguments[0] == 'create':
                return 'c' * 64
            if arguments[0] == 'inspect':
                return json.dumps([dict(Config=dict(Labels={self.module.LABEL: 'a' * 32}),
                                        State=dict(Running=False, ExitCode=0))])
            return 'output' if arguments[0] == 'start' else ''
        with patch.object(self.module.secrets, 'token_hex', return_value='a' * 32), \
                patch.object(self.module, 'docker', side_effect=docker):
            result = self.module.helper(IMAGE['id'], 'owned-volume', '/bin/ls', readonly=True)
        self.assertEqual(result, 'output')
        self.assertEqual([call[0] for call in calls].count('rm'), 1)


if __name__ == '__main__':
    unittest.main()
