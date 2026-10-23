"""Contracts for preparing standalone publisher and CI workspaces."""
from pathlib import Path
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
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

    def run_prepared(self, *, tamper=None, role='consumer'):
        self.prepare_ca(role)
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
        moved = self.output.with_name('moved ' + role)
        self.output.rename(moved)
        self.output = moved
        fake = Path(self.temporary.name) / 'client.py'
        fake.write_text('#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
            'with Path("calls.jsonl").open("a") as f: f.write(json.dumps({"args":sys.argv[1:],"ca":os.getenv("SSL_CERT_FILE"),"dir":os.getenv("SSL_CERT_DIR")})+"\\n")\n'
            'if sys.argv[1:]==["repo","supports","source-baseline-v1"]: print("source-baseline-v1")\n')
        fake.chmod(0o700)
        binary = moved / 'target/release/bin/main'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "synthetic app\\n"\n')
        binary.chmod(0o700)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('CJREPO_', 'CJREPOMESH_'))}
        env.update(CJREPOMESH_CJPM=str(fake), CJREPO_READ_TOKEN='synthetic-read',
            CJREPO_PUBLISH_TOKEN='synthetic-publish', SSL_CERT_FILE='/inherited/wrong-ca', SSL_CERT_DIR='/inherited/wrong-dir')
        result = subprocess.run(['bash', 'run.sh'], cwd=moved, env=env, capture_output=True, text=True, timeout=15)
        return result, moved / 'calls.jsonl'

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
