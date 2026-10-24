"""Contracts for preparing standalone publisher and CI workspaces."""
from pathlib import Path
import json
import hashlib
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_portable_ca import CA

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "team" / "prepare.py"


class TeamExampleTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "integration-tests" / ".tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="team-unit-", dir=parent)
        self.output = Path(self.temporary.name) / "workspace"

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, role="consumer", registry="http://127.0.0.1:18080", extra=()):
        return subprocess.run((sys.executable, str(SCRIPT), "--role", role, "--registry", registry,
                               "--output", str(self.output), *map(str, extra)), capture_output=True, text=True, timeout=15)

    def input_ca(self, data=CA):
        path = Path(self.temporary.name) / 'input.pem'
        path.write_bytes(data)
        return path

    def prepare_ca(self, role='consumer'):
        path = self.input_ca()
        result = self.invoke(role, 'https://127.0.0.1:18443', ('--ca-file', path,
            '--ca-sha256', hashlib.sha256(CA).hexdigest()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return path

    def test_consumer_prepared_without_credentials(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = (self.output / "cangjie-repo.toml").read_text()
        self.assertIn('token-env = "CJREPO_READ_TOKEN"', config)
        self.assertIn('exclusive = true', config)
        self.assertNotIn('PUBLISH_TOKEN', config)
        self.assertEqual(json.loads((self.output / "workspace.json").read_text())["role"], "consumer")
        self.assertFalse((self.output / ".env").exists())

    def test_publisher_uses_publish_credential_reference(self):
        result = self.invoke(role="publisher")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.output / "cangjie-repo.toml").read_text()
        self.assertIn('[repository.home]', config)
        self.assertIn('token-env = "CJREPO_PUBLISH_TOKEN"', config)
        self.assertNotIn('READ_TOKEN', config)

    def test_existing_workspace_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse((self.output / "cangjie-repo.toml").exists())

    def test_existing_file_not_overwritten(self):
        self.output.write_text('keep original file')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_text(), 'keep original file')

    def output_link(self, target):
        if os.name == 'nt':
            missing = not target.exists()
            if missing:
                target.mkdir()
            try:
                result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                    str(self.output), str(target)], capture_output=True, text=True, timeout=15)
            finally:
                if missing:
                    target.rmdir()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.output.symlink_to(target, target_is_directory=True)

    def test_dangling_output_link_rejected_without_creating_target(self):
        target = Path(self.temporary.name) / 'uncreated target'
        self.output_link(target)
        before = self.output.lstat()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('workspace already exists', result.stdout + result.stderr)
        self.assertFalse(target.exists())
        self.assertEqual(self.output.lstat().st_mode, before.st_mode)

    def test_output_link_to_existing_directory_preserves_target(self):
        target = Path(self.temporary.name) / 'existing target'
        target.mkdir()
        sentinel = target / 'keep.txt'
        sentinel.write_text('keep')
        self.output_link(target)
        result = self.invoke(role='publisher')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertEqual(sorted(path.name for path in target.iterdir()), ['keep.txt'])
        self.output.lstat()

    def test_api_rejects_dangling_output_before_ca_validation(self):
        target = Path(self.temporary.name) / 'uncreated target'
        self.output_link(target)
        prepare = runpy.run_path(str(SCRIPT))['prepare']
        with self.assertRaisesRegex(FileExistsError, 'workspace already exists'):
            prepare('consumer', 'https://127.0.0.1:18443', self.output,
                    Path(self.temporary.name) / 'unread-ca.pem')
        self.assertFalse(target.exists())
        self.output.lstat()

    def test_trust_copy_failure_keeps_evidence_without_run_entry(self):
        prepare = runpy.run_path(str(SCRIPT))['prepare']
        ca = self.input_ca()
        import shutil
        copyfile = shutil.copyfile
        def fail_trust(source, destination, *args, **kwargs):
            if Path(destination).name == 'trust.py':
                raise OSError('synthetic trust copy failure')
            return copyfile(source, destination, *args, **kwargs)
        with patch('shutil.copyfile', side_effect=fail_trust):
            with self.assertRaisesRegex(OSError, 'synthetic trust copy failure'):
                prepare('consumer', 'https://127.0.0.1:18443', self.output, ca)
        self.assertEqual((self.output / 'trust/ca.pem').read_bytes(), CA)
        self.assertTrue((self.output / 'cjpm.toml').is_file())
        self.assertFalse((self.output / 'run.sh').exists())
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('workspace already exists', result.stdout + result.stderr)

    def test_configuration_failure_keeps_evidence_without_run_entry(self):
        prepare = runpy.run_path(str(SCRIPT))['prepare']
        write_text = Path.write_text
        def fail_configuration(path, *args, **kwargs):
            if path.name == 'cangjie-repo.toml':
                raise OSError('synthetic configuration write failure')
            return write_text(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_configuration):
            with self.assertRaisesRegex(OSError, 'synthetic configuration write failure'):
                prepare('publisher', 'http://127.0.0.1:18080', self.output)
        self.assertTrue((self.output / 'src').is_dir())
        self.assertTrue((self.output / '.home').is_dir())
        self.assertFalse((self.output / 'run.sh').exists())

    def test_partial_entry_write_keeps_temporary_file_without_run_entry(self):
        prepare = runpy.run_path(str(SCRIPT))['prepare']
        write_text = Path.write_text
        def fail_entry(path, *args, **kwargs):
            if path.name in ('run.sh', '.run.sh.tmp'):
                write_text(path, '# incomplete synthetic entry\n', encoding='utf-8')
                raise OSError('synthetic entry write failure')
            return write_text(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_entry):
            with self.assertRaisesRegex(OSError, 'synthetic entry write failure'):
                prepare('consumer', 'http://127.0.0.1:18080', self.output)
        self.assertFalse((self.output / 'run.sh').exists())
        self.assertEqual((self.output / '.run.sh.tmp').read_text(), '# incomplete synthetic entry\n')
        self.assertTrue((self.output / 'workspace.json').is_file())

    def test_unsafe_registry_rejected_before_creating_workspace(self):
        result = self.invoke(registry="http://user:synthetic-secret@localhost:18080")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn("synthetic-secret", result.stdout + result.stderr)

    def test_https_both_roles_copy_public_ca_and_record_pin(self):
        for role in ('consumer', 'publisher'):
            with self.subTest(role=role):
                self.output = Path(self.temporary.name) / role
                source = self.prepare_ca(role)
                self.assertEqual(source.read_bytes(), CA)
                self.assertEqual((self.output / 'trust/ca.pem').read_bytes(), CA)
                meta = json.loads((self.output / 'workspace.json').read_text())
                self.assertEqual(meta['trust']['caSha256'], hashlib.sha256(CA).hexdigest())
                self.assertTrue((self.output / 'trust.py').is_file())
                self.assertFalse(any((self.output / 'trust/empty').iterdir()))
                self.assertFalse((self.output / '.env').exists())

    def test_ca_requires_https_before_output_creation(self):
        result = self.invoke(extra=('--ca-file', self.input_ca()))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CA options require an HTTPS registry', result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_digest_requires_ca_file(self):
        result = self.invoke(registry='https://127.0.0.1', extra=('--ca-sha256', '0' * 64))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ca-sha256 requires ca-file', result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_wrong_digest_rejected_without_output(self):
        result = self.invoke(registry='https://127.0.0.1', extra=('--ca-file', self.input_ca(), '--ca-sha256', '0' * 64))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('trusted CA', result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_private_key_or_malformed_pem_rejected_without_echo(self):
        marker = 'SYNTHETIC-PRIVATE-MARKER-DO-NOT-ECHO'
        result = self.invoke(registry='https://127.0.0.1', extra=('--ca-file', self.input_ca(CA + ('\n-----BEGIN PRIVATE KEY-----\n' + marker).encode())))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('trusted CA', result.stdout + result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_oversized_ca_rejected_before_output(self):
        result = self.invoke(registry='https://127.0.0.1', extra=('--ca-file', self.input_ca(b' ' * (1024 * 1024 + 1))))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('trusted CA', result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    @unittest.skipIf(os.name == 'nt', 'link creation requires separate Windows privilege')
    def test_ca_symlink_rejected(self):
        source = self.input_ca()
        link = source.with_name('linked.pem')
        link.symlink_to(source)
        result = self.invoke(registry='https://127.0.0.1', extra=('--ca-file', link))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('trusted CA', result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def run_prepared(self, *, tamper=None, role='consumer', app_exit=0, trust=True, protected=False):
        if trust:
            self.prepare_ca(role)
        else:
            result = self.invoke(role)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if tamper == 'modified':
            path = self.output / 'trust/ca.pem'
            path.chmod(0o600)
            path.write_bytes(CA + b'\n')
        elif tamper == 'missing':
            path = self.output / 'trust/ca.pem'
            path.chmod(0o600)
            path.unlink()
        elif tamper == 'extra-root':
            (self.output / 'trust/empty/unapproved.pem').write_bytes(CA)
        moved = self.output.with_name('moved ' + self.output.name)
        self.output.rename(moved)
        self.output = moved
        fake = Path(self.temporary.name) / 'client.py'
        fake.write_text('#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
            'with Path("calls.jsonl").open("a") as f: f.write(json.dumps({"args":sys.argv[1:],"ca":os.getenv("SSL_CERT_FILE"),"dir":os.getenv("SSL_CERT_DIR"),"readPresent":"CJREPO_READ_TOKEN" in os.environ,"publishPresent":"CJREPO_PUBLISH_TOKEN" in os.environ})+"\\n")\n'
            'if sys.argv[1:]==["repo","supports","source-baseline-v1"]: print("source-baseline-v1")\n')
        fake.chmod(0o700)
        binary = moved / 'target/release/bin/main'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
            'Path("app-environment.json").write_text(json.dumps({'
            '"readPresent":"CJREPO_READ_TOKEN" in os.environ,'
            '"publishPresent":"CJREPO_PUBLISH_TOKEN" in os.environ,'
            '"ca":os.getenv("SSL_CERT_FILE"),"dir":os.getenv("SSL_CERT_DIR"),'
            '"applicationSetting":os.getenv("TEAM_APPLICATION_SETTING")=="keep"}))\n'
            'print("synthetic app")\n'
            f'sys.exit({app_exit})\n')
        binary.chmod(0o700)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('CJREPO_', 'CJREPOMESH_'))}
        env.update(CJREPOMESH_CJPM=str(fake), CJREPO_READ_TOKEN='synthetic-read',
            CJREPO_PUBLISH_TOKEN='synthetic-publish', SSL_CERT_FILE='/inherited/wrong-ca',
            SSL_CERT_DIR='/inherited/wrong-dir', TEAM_APPLICATION_SETTING='keep')
        if protected:
            env['CJREPOMESH_SOURCE_BASELINE'] = str(moved / 'independent-approval.json')
        result = subprocess.run(['bash', 'run.sh'], cwd=moved, env=env, capture_output=True, text=True, timeout=15)
        return result, moved / 'calls.jsonl'

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_application_does_not_inherit_repository_credentials(self):
        for trust in (False, True):
            with self.subTest(trust=trust):
                self.output = Path(self.temporary.name) / str(trust)
                result, calls = self.run_prepared(trust=trust, protected=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                rows = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual([row['args'] for row in rows], [
                    ['repo', 'supports', 'source-baseline-v1'], ['build'],
                    ['repo', 'explain', 'company::teamhello', '--recorded']])
                self.assertTrue(all(row['readPresent'] and not row['publishPresent'] for row in rows))
                app = json.loads((self.output / 'app-environment.json').read_text())
                self.assertFalse(app['readPresent'])
                self.assertFalse(app['publishPresent'])
                self.assertTrue(app['applicationSetting'])
                self.assertEqual((app['ca'], app['dir']), (rows[1]['ca'], rows[1]['dir']))
                self.assertNotIn('synthetic-read', result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_application_failure_preserves_status_and_stops_explanation(self):
        result, calls = self.run_prepared(app_exit=7)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        rows = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertEqual([row['args'] for row in rows], [['build']])
        app = json.loads((self.output / 'app-environment.json').read_text())
        self.assertFalse(app['readPresent'])
        self.assertFalse(app['publishPresent'])

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_moved_https_jobs_pin_process_trust_for_both_roles(self):
        for role in ('consumer', 'publisher'):
            with self.subTest(role=role):
                self.output = Path(self.temporary.name) / role
                result, calls = self.run_prepared(role=role)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                rows = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertTrue(rows)
                self.assertTrue(all(row['ca'] == str(self.output / 'trust/ca.pem') and row['dir'] == str(self.output / 'trust/empty') for row in rows))

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_modified_ca_fails_before_client(self):
        result, calls = self.run_prepared(tamper='modified')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists())

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_missing_ca_fails_before_client(self):
        result, calls = self.run_prepared(tamper='missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists())

    @unittest.skipUnless(os.name == 'posix', 'Bash job execution is Linux-only')
    def test_extra_trust_root_fails_before_client(self):
        result, calls = self.run_prepared(tamper='extra-root')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists())


if __name__ == "__main__":
    unittest.main()
