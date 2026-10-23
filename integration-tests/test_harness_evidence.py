"""Synthetic process failures must remain diagnosable after a core test exits."""
import importlib.util
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lib.harness import TestFailure, wait_for_health
from lib.suites import TestContext


class HarnessEvidenceTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent/'.tmp'
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='harness-evidence-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_failed_context_retains_child_log(self):
        self.assertIn('preserve', inspect.signature(TestContext.close).parameters,
                      'failed core context has no evidence retention mode')
        (self.root/'integration-tests').mkdir()
        context = TestContext(self.root, Path(sys.executable), Path(sys.executable), build=False)
        log = context.temp_root/'failed-child.log'
        log.write_text('synthetic failure evidence')
        context.close(preserve=True)
        self.assertEqual(log.read_text(), 'synthetic failure evidence')

    def test_success_context_still_cleans_owned_temporary_root(self):
        (self.root/'integration-tests').mkdir()
        context = TestContext(self.root, Path(sys.executable), Path(sys.executable), build=False)
        target = context.temp_root
        context.close()
        self.assertFalse(target.exists())

    def test_health_failure_reports_early_exit_and_log_without_body(self):
        self.assertIn('process', inspect.signature(wait_for_health).parameters,
                      'health readiness does not observe child process failure')
        log = self.root/'child.log'
        log.write_text('synthetic-private-log-body')
        process = subprocess.Popen((sys.executable, '-c', 'raise SystemExit(7)'))
        process.wait(timeout=10)
        with self.assertRaises(TestFailure) as caught:
            wait_for_health(0, attempts=1, interval=0, process=process, log_path=log)
        message = str(caught.exception)
        self.assertIn('exited with code 7', message)
        self.assertIn('child.log', message)
        self.assertNotIn('synthetic-private-log-body', message)

    def test_core_runner_requests_preservation_on_failure(self):
        spec = importlib.util.spec_from_file_location('core_runner', Path(__file__).with_name('run.py'))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        args = SimpleNamespace(cjpm=Path(sys.executable), server=Path(sys.executable),
                               suite=['synthetic'], skip_server_build=True)
        with patch.object(runner, 'parse_args', return_value=args), patch.object(runner, 'TestContext') as factory:
            with patch.dict(runner.SUITES, {'synthetic': ('Synthetic', lambda ctx: (_ for _ in ()).throw(
                    TestFailure('controlled child failure')))}):
                with self.assertRaises(TestFailure):
                    runner.main()
            factory.return_value.close.assert_called_once_with(preserve=True)


if __name__ == '__main__':
    unittest.main()
