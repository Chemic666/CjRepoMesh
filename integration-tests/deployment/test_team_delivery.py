"""Delivered client preflight must finish before Docker or evidence writes."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'integration-tests/deployment/portable.py'


class TeamDeliveryTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='team-delivery-', dir=parent)
        self.work = Path(self.temporary.name)
        self.bundle = self.work / 'client bundle'
        (self.bundle / 'lib').mkdir(parents=True)
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HH', header, 16, 3, 62)
        names = runpy.run_path(str(ROOT / 'deployment/client/verify.py'))['FILES']
        for name in names:
            # The candidate's own verifier must never be imported or executed.
            payload = (bytes(header) if name == 'cjpm' or name.endswith('.so') else
                       b"raise RuntimeError('untrusted verifier executed')\n")
            (self.bundle / name).write_bytes(payload)
        files = {name: dict(bytes=(self.bundle / name).stat().st_size,
                 sha256=hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()) for name in names}
        (self.bundle / 'manifest.json').write_text(json.dumps(dict(formatVersion=1,
            platform=dict(os='linux', architecture='amd64'), files=files)))
        self.functions = runpy.run_path(str(SCRIPT))

    def tearDown(self):
        self.temporary.cleanup()

    def identity(self):
        self.assertTrue('client_bundle_identity' in self.functions,
                        'receiver lacks delivered client verification')
        return self.functions['client_bundle_identity'](self.bundle)

    def invoke(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), '--bundle', str(self.work / 'server'),
            '--package-dir', str(self.work / 'package'), '--evidence-dir', str(self.work / 'evidence'),
            *map(str, arguments)], capture_output=True, text=True, timeout=15)

    def test_verified_identity_does_not_execute_candidate_verifier(self):
        identity = self.identity()
        self.assertEqual(identity['mode'], 'client-bundle')
        self.assertEqual(identity['binarySha256'], hashlib.sha256((self.bundle / 'cjpm').read_bytes()).hexdigest())
        self.assertEqual(identity['manifestSha256'], hashlib.sha256((self.bundle / 'manifest.json').read_bytes()).hexdigest())

    def test_modified_runtime_rejected(self):
        (self.bundle / 'lib/libboundscheck.so').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.identity()

    def test_extra_credential_file_rejected(self):
        (self.bundle / '.env').write_text('SYNTHETIC=do-not-read')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.identity()

    def test_bundle_requires_sdk_before_side_effects(self):
        result = self.invoke('--team-client-bundle', self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be supplied together', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_raw_client_and_bundle_are_mutually_exclusive(self):
        result = self.invoke('--team-client-bundle', self.bundle, '--team-client', self.work / 'cjpm')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not allowed with argument', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_corrupt_bundle_rejected_before_evidence_creation(self):
        sdk = self.work / 'sdk'
        sdk.mkdir()
        (sdk / 'envsetup.sh').write_text('# synthetic; never executed\n')
        (self.bundle / 'cjpm').write_bytes(b'corrupt')
        result = self.invoke('--team-sdk', sdk, '--team-client-bundle', self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('integrity', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_protected_mode_requires_complete_client_before_side_effects(self):
        result = self.invoke('--team-protected')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires team-client-bundle and team-sdk', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_protected_mode_rejects_raw_client_before_side_effects(self):
        result = self.invoke('--team-protected', '--team-client', self.work / 'raw-client',
                             '--team-sdk', self.work / 'sdk')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires team-client-bundle and team-sdk', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_packaged_mode_requires_protected_mode_before_side_effects(self):
        result = self.invoke('--team-packaged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('team-packaged requires team-protected', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_packaged_mode_refuses_legacy_client_before_evidence(self):
        sdk = self.work / 'sdk'
        sdk.mkdir()
        (sdk / 'envsetup.sh').write_text('# synthetic; never executed\n')
        result = self.invoke('--team-packaged', '--team-protected', '--team-sdk', sdk,
                             '--team-client-bundle', self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('team preparation capability', result.stderr)
        self.assertNotIn('untrusted verifier executed', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_required_capability_is_checked_by_trusted_verifier(self):
        with self.assertRaisesRegex(ValueError, 'team preparation capability'):
            self.functions['client_bundle_identity'](self.bundle, require_team=True)

    def test_packaged_command_actually_prepares_both_roles_without_source_path(self):
        kit = self.work / 'team-kit'
        result = subprocess.run([sys.executable, str(ROOT / 'deployment/client/package.py'),
            '--cjpm', str(self.bundle / 'cjpm'), '--runtime-dir', str(self.bundle / 'lib'),
            '--output', str(kit), '--include-team'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for role in ('publisher', 'consumer'):
            job = self.work / role
            command = self.functions['team_workspace_command'](kit, role, 'http://cjrepo:8080', job, packaged=True)
            self.assertEqual(Path(command[1]), kit / 'prepare-team.py')
            result = subprocess.run(command, cwd=self.work, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            metadata = json.loads((job / 'workspace.json').read_text())
            self.assertEqual(metadata['role'], role)
            self.assertEqual('execution' in metadata, role == 'consumer')
            self.assertEqual((job / 'job.py').exists(), role == 'consumer')
        identity = self.functions['client_bundle_identity'](kit, require_team=True)
        self.assertEqual(identity['teamPreparation'], 'single-use-cold-v1')

    def test_default_command_keeps_ordinary_source_preparation(self):
        command = self.functions['team_workspace_command'](None, 'consumer', 'http://cjrepo:8080', self.work / 'ordinary')
        self.assertEqual(Path(command[1]), ROOT / 'examples/team/prepare.py')
        self.assertNotIn('--single-use', command)

    def test_relative_packaged_path_survives_changed_execution_directory(self):
        kit = self.work / 'relative-kit'
        result = subprocess.run([sys.executable, str(ROOT / 'deployment/client/package.py'),
            '--cjpm', str(self.bundle / 'cjpm'), '--runtime-dir', str(self.bundle / 'lib'),
            '--output', str(kit), '--include-team'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        relative = Path(os.path.relpath(kit, Path.cwd()))
        identity = self.functions['client_bundle_identity'](relative, require_team=True)
        self.assertEqual(identity['teamPreparation'], 'single-use-cold-v1')
        elsewhere = self.work / 'different-cwd'
        elsewhere.mkdir()
        command = self.functions['team_workspace_command'](relative, 'consumer', 'http://cjrepo:8080',
                                                           self.work / 'relative-job', packaged=True)
        result = subprocess.run(command, cwd=elsewhere, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.work / 'relative-job/job.py').is_file())

    def repeat_fixture(self):
        job = self.work / 'completed'
        job.mkdir()
        (job / '.cjrepomesh-job-started').mkdir()
        (job / 'target').mkdir()
        (job / 'target/keep').write_bytes(b'owned original build output')
        before = self.functions['team_task_state'](job)
        result = SimpleNamespace(returncode=2, stdout='FAIL: single-use task contains previous cache or build state\n', stderr='')
        return job, before, result

    def test_repeat_accepts_only_real_guard_refusal_with_preserved_state(self):
        job, before, result = self.repeat_fixture()
        self.functions['check_team_repeat'](job, result, before)

    def test_repeat_rejects_success_or_unrelated_failure_or_application_output(self):
        job, before, result = self.repeat_fixture()
        for code, output in ((0, result.stdout), (7, result.stdout), (2, 'unrelated failure'),
                             (2, result.stdout + 'CjRepoMesh team 1.0.0: CI\n')):
            with self.subTest(code=code, output=output):
                bad = SimpleNamespace(returncode=code, stdout=output, stderr='')
                with self.assertRaises(AssertionError):
                    self.functions['check_team_repeat'](job, bad, before)

    def test_repeat_must_preserve_bytes_and_claim(self):
        job, before, result = self.repeat_fixture()
        (job / 'target/keep').write_bytes(b'changed')
        with self.assertRaises(AssertionError):
            self.functions['check_team_repeat'](job, result, before)
        (job / 'target/keep').write_bytes(b'owned original build output')
        (job / '.cjrepomesh-job-started').rmdir()
        with self.assertRaises(AssertionError):
            self.functions['check_team_repeat'](job, result, before)

    @unittest.skipUnless(os.name == 'nt', 'extended Windows path regression')
    def test_task_state_reads_long_windows_cache_paths_without_policy_changes(self):
        root = self.work / 'long-job'
        self.assertTrue(root.resolve().is_relative_to((ROOT / 'integration-tests/.tmp').resolve()))
        extended = Path('\\\\?\\' + str(root.absolute()))
        relative = Path('cache') / ('a' * 80) / ('b' * 80) / 'source.cj'
        target = extended / relative
        self.assertGreater(len(str(root / relative)), 260)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'owned long-path source')
        try:
            state = self.functions['team_task_state'](root)
            self.assertEqual(state[relative.as_posix()], ('file', hashlib.sha256(b'owned long-path source').hexdigest()))
        finally:
            # This new directory was checked inside this test's owned workspace.
            shutil.rmtree(extended)
    def publisher(self):
        publisher = self.work / 'publisher'
        target = publisher / 'target'
        target.mkdir(parents=True)
        archive = target / 'teamhello-1.0.0.cjp'
        archive.write_bytes(b'synthetic controlled publisher archive')
        index = dict(organization='company', name='teamhello', version='1.0.0',
                     sha256sum=hashlib.sha256(archive.read_bytes()).hexdigest())
        (target / 'meta-data.json').write_text(json.dumps(dict(index=index)))
        return publisher, archive, index

    def approval(self, publisher):
        self.assertTrue('team_source_approval' in self.functions, 'missing controlled fixture approval')
        return self.functions['team_source_approval'](publisher, 'http://cjrepo:8080')

    def test_approval_refuses_archive_not_matching_controlled_metadata(self):
        publisher, archive, _ = self.publisher()
        archive.write_bytes(b'changed bytes after publication')
        with self.assertRaisesRegex(ValueError, 'publisher fixture'):
            self.approval(publisher)

    def test_approval_refuses_unexpected_package_identity(self):
        publisher, _, index = self.publisher()
        index['organization'] = 'other'
        (publisher / 'target/meta-data.json').write_text(json.dumps(dict(index=index)))
        with self.assertRaisesRegex(ValueError, 'publisher fixture'):
            self.approval(publisher)

    def test_approval_does_not_trust_existing_consumer_provenance(self):
        publisher, archive, _ = self.publisher()
        (publisher / 'cjpm-provenance.json').write_text('untrusted consumer provenance')
        approved = self.approval(publisher)
        self.assertEqual(approved['packages'][0]['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(approved['packages'][0]['registry'], 'http://cjrepo:8080')

    def test_large_fixture_is_deterministic_text_and_preserves_existing_files(self):
        import base64
        writer = self.functions.get('create_large_team_fixture')
        self.assertIsNotNone(writer, 'receiver lacks a real large-package fixture')
        first = self.work / 'first'; first.mkdir()
        second = self.work / 'second'; second.mkdir()
        identity = writer(first, 1)
        self.assertEqual(identity, writer(second, 1))
        body = (first / 'large-payload.txt').read_bytes()
        self.assertEqual(len(base64.b64decode(body, validate=True)), 1048576)
        self.assertNotIn(b'\0', body)
        self.assertEqual(identity['sourceSha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(identity['sourceBytes'], len(body))
        with self.assertRaises(FileExistsError):
            writer(first, 1)
        self.assertEqual((first / 'large-payload.txt').read_bytes(), body)

    def test_large_fixture_rejects_invalid_size_before_writing(self):
        writer = self.functions.get('create_large_team_fixture')
        self.assertIsNotNone(writer, 'receiver lacks large-package bounds')
        for size in (-1, 0, 33):
            with self.subTest(size=size), self.assertRaises(ValueError):
                writer(self.work, size)
        self.assertFalse((self.work / 'large-payload.txt').exists())

    def test_large_cli_requires_packaged_team_before_side_effects(self):
        result = self.invoke('--team-large-payload-mib', '16')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('large payload requires team-packaged', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_large_cli_rejects_out_of_range_before_side_effects(self):
        for size in ('-1', '33'):
            result = self.invoke('--team-large-payload-mib', size)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('between 0 and 32', result.stderr)
            self.assertFalse((self.work / 'evidence').exists())

    def test_large_cold_cache_rejects_missing_corrupt_or_duplicate_content(self):
        verify = self.functions.get('verify_large_team_cache')
        self.assertIsNotNone(verify, 'large CJP cold-cache verification is missing')
        job = self.work / 'cold-job'; job.mkdir()
        identity = dict(sourceBytes=4, sourceSha256=hashlib.sha256(b'text').hexdigest())
        with self.assertRaises(ValueError):
            verify(job, identity)
        target = job / 'cache/repository/registries/internal/identity/source/company/teamhello-1.0.0/large-payload.txt'
        target.parent.mkdir(parents=True); target.write_bytes(b'text')
        verify(job, identity)
        target.write_bytes(b'fake')
        with self.assertRaises(ValueError):
            verify(job, identity)
        target.write_bytes(b'text')
        other = job / 'cache/another/large-payload.txt'; other.parent.mkdir(); other.write_bytes(b'text')
        with self.assertRaises(ValueError):
            verify(job, identity)


if __name__ == '__main__':
    unittest.main()
