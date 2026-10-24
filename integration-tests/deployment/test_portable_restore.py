"""Recovery must preserve private configuration and reject ambiguous identities."""
import subprocess
import sys
import unittest
from pathlib import Path
import tempfile

import portable_ca


class PortableRestoreTests(unittest.TestCase):
    def test_restore_preflight_requires_maintenance_before_side_effects(self):
        root = Path(__file__).resolve().parents[2]
        parent = root/'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='restore-option-', dir=parent) as temporary:
            work = Path(temporary)
            command = [sys.executable, str(root/'integration-tests/deployment/portable_ca.py')]
            for name in ('bundle', 'package-dir', 'native', 'openssl', 'evidence-dir'):
                command += ['--'+name, str(work/name)]
            result = subprocess.run(command + ['--restore-preflight'], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('restore-preflight requires maintenance', result.stderr)
            self.assertFalse((work/'evidence-dir').exists())

    def test_command_output_uses_utf8_and_survives_invalid_log_bytes(self):
        self.assertTrue(hasattr(portable_ca, 'run_process'), 'portable receiver output has no explicit decoding contract')
        result = portable_ca.run_process((sys.executable, '-c',
            "import sys;sys.stdout.buffer.write(bytes.fromhex('e4b8ade69687ff'));sys.stderr.buffer.write(bytes.fromhex('e697a5e5bf97fe'))"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '\u4e2d\u6587\ufffd')
        self.assertEqual(result.stderr, '\u65e5\u5fd7\ufffd')

    def test_only_project_identity_changes(self):
        before = (b'COMPOSE_PROJECT_NAME=cjrepomesh-1111111111111111\n'
                  b'CJREPO_READ_TOKEN=synthetic-private-value\n'
                  b'CJREPO_HOST_PORT=12345\nCJREPO_CA_SHA256=abc\n')
        result = portable_ca.restore_configuration(before, 'cjrepomesh-2222222222222222')
        self.assertEqual(result, before.replace(b'1111111111111111', b'2222222222222222', 1))
        self.assertIn(b'CJREPO_READ_TOKEN=synthetic-private-value\n', result)

    def test_missing_duplicate_and_malformed_project_are_rejected_without_values(self):
        for before in (b'CJREPO_READ_TOKEN=synthetic-private-value\n',
                       b'COMPOSE_PROJECT_NAME=bad\nCJREPO_READ_TOKEN=synthetic-private-value\n',
                       b'COMPOSE_PROJECT_NAME=cjrepomesh-1111111111111111\n' * 2):
            with self.subTest(before=before):
                with self.assertRaises(ValueError) as caught:
                    portable_ca.restore_configuration(before, 'cjrepomesh-2222222222222222')
                self.assertNotIn('synthetic-private-value', str(caught.exception))

    def test_invalid_or_same_target_project_is_rejected(self):
        before = b'COMPOSE_PROJECT_NAME=cjrepomesh-1111111111111111\n'
        for project in ('cjrepomesh-1111111111111111', 'other', 'new\nCJREPO_READ_TOKEN=value'):
            with self.subTest(project=project), self.assertRaises(ValueError):
                portable_ca.restore_configuration(before, project)


if __name__ == '__main__':
    unittest.main()
