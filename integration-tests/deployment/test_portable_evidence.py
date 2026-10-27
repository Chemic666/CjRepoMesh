"""Preserve failed synthetic job output without echoing command secrets."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class PortableEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.functions = runpy.run_path(str(ROOT/'integration-tests/deployment/portable.py'))
        self.assertTrue('run_with_evidence' in self.functions, 'timeout evidence helper is missing')
        parent = ROOT/'integration-tests/.tmp'; parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='portable-evidence-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.log = Path(self.temporary.name)/'job.log'

    def test_timeout_retains_real_partial_output_and_hides_secret_argument(self):
        secret = 'synthetic-timeout-private'
        command = [sys.executable, '-c',
                   'import sys,time;print(sys.argv[1],flush=True);print("stderr-before-timeout",file=sys.stderr,flush=True);time.sleep(30)', secret]
        with self.assertRaisesRegex(AssertionError, 'job: command timed out') as caught:
            self.functions['run_with_evidence']('job', command, cwd=self.log.parent,
                environment=None, secret_values=[secret], log_path=self.log, timeout=1)
        output = self.log.read_text()
        self.assertIn('[REDACTED]', output); self.assertIn('stderr-before-timeout', output)
        self.assertNotIn(secret, output); self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn('sys.argv', str(caught.exception))

    def test_success_keeps_raw_result_for_parsing_but_only_redacted_log(self):
        function = self.functions['run_with_evidence']
        result = subprocess.CompletedProcess(['synthetic'], 0, 'synthetic-private', 'diagnostic')
        with patch.dict(function.__globals__, subprocess=type('Process', (), {'run': staticmethod(lambda *a, **k: result), 'TimeoutExpired': subprocess.TimeoutExpired})):
            actual = function('job', ['synthetic'], cwd=self.log.parent, environment=None,
                secret_values=['synthetic-private'], log_path=self.log, timeout=1)
        self.assertIs(actual, result)
        self.assertEqual(self.log.read_text(), '[REDACTED]diagnostic')

    def test_container_snapshot_does_not_copy_environment_or_health_log(self):
        item = dict(Id='owned', Image='image', Config=dict(Env=['TOKEN=synthetic-private']),
                    State=dict(Status='running', Running=True, OOMKilled=False, ExitCode=0,
                               Health=dict(Log=[dict(Output='synthetic-private')]), Error=''))
        snapshot = self.functions['container_failure_snapshot'](item)
        self.assertFalse(snapshot['state']['OOMKilled'])
        self.assertNotIn('synthetic-private', str(snapshot))
        self.assertNotIn('Config', snapshot); self.assertNotIn('Health', snapshot['state'])

    def test_diagnostic_disk_failure_cannot_block_following_cleanup(self):
        calls, errors = [], []
        def run(label, command, **options): calls.append(command[1])
        with patch.object(Path, 'write_text', side_effect=OSError('synthetic disk full')):
            self.functions['retain_container_failure'](dict(Id='owned', State={}), self.log.parent, [], run, errors)
            run('remove', ('docker', 'rm', 'owned'))
            run('down', ('docker', 'compose', 'down'))
        self.assertEqual(calls, ['logs', 'stats', 'top', 'rm', 'compose'])
        self.assertEqual(errors, ['state: owned container diagnostics unavailable'])


if __name__ == '__main__': unittest.main()
