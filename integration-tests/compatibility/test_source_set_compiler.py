"""Synthetic process management regressions; never invokes Cangjie."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import source_set_compiler as runner


@unittest.skipUnless(sys.platform == 'linux', 'Linux process groups')
class ProcessCleanupTests(unittest.TestCase):
    def run_synthetic(self, sleeping):
        parent = Path(__file__).resolve().parent.parent / '.tmp'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='source_set_process_', dir=parent) as raw:
            root = Path(raw)
            fixture = root / 'fixture'
            fixture.mkdir()
            (fixture / 'always_enabled_check.info').write_text('// synthetic fixture identity\n')
            compiler = root / 'cjc'
            compiler.write_text('synthetic, never executed\n')
            pids = root / 'owned-pids'
            client = root / 'cjpm'
            client.write_text('#!/usr/bin/python3\nimport os, subprocess, sys, time\n'
                f'pids={str(pids)!r}\n'
                'with open(pids,"a") as stream: stream.write(str(os.getpid())+"\\n")\n'
                + ('depth=int(sys.argv[1]) if sys.argv[1] != "run" else 0\n'
                   'if depth < 2: subprocess.Popen([sys.executable,__file__,str(depth+1)])\n'
                   'print("ordinary-ok",flush=True)\ntime.sleep(60)\n'
                   if sleeping else 'print("ordinary-ok",flush=True)\n'))
            client.chmod(0o755)
            results = root / 'results'
            argv = ['source_set_compiler', '--cjpm', str(client), '--cjc', str(compiler),
                    '--fixture', str(fixture), '--results', str(results),
                    '--stage-parent', str(root), '--case', 'ordinary-no-probe']
            real_run = subprocess.run

            def bounded_old_run(*args, **kwargs):
                # Bound the real pre-fix subprocess.run for the RED experiment.
                kwargs['timeout'] = 0.6
                return real_run(*args, **kwargs)

            begin = time.monotonic()
            caught = None
            code = None
            try:
                with mock.patch.object(sys, 'argv', argv), \
                     mock.patch.object(runner, 'CASE_TIMEOUT_SECONDS', 0.6, create=True), \
                     mock.patch.object(runner.subprocess, 'run', bounded_old_run):
                    try:
                        code = runner.main()
                    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
                        caught = type(error).__name__
                self.assertTrue((results / 'summary.json').is_file(),
                                f'Failure bypassed summary: {caught}')
                summary = json.loads((results / 'summary.json').read_text())
                self.assertEqual(code, 1)
                self.assertEqual(summary['passed'], 0)
                self.assertEqual(summary['total'], 1)
                case = summary['cases'][0]
                self.assertFalse(case['passed'])
                self.assertEqual(case['timedOut'], sleeping)
                self.assertIn('calls', case['error'])
                self.assertTrue(summary['ownedStageRemoved'])
                self.assertLess(time.monotonic() - begin, 5)
                recorded = [int(line) for line in pids.read_text().splitlines()]
                self.assertEqual(len(recorded), 3 if sleeping else 1)
                for pid in recorded:
                    stat = Path(f'/proc/{pid}/stat')
                    if stat.exists():
                        self.assertEqual(stat.read_text().split(') ')[1][0], 'Z',
                                         f'Owned process still running: {pid}')
                self.assertIn('ordinary-ok', (results / 'ordinary-no-probe.log').read_text())
            finally:
                # The RED intentionally exposes leaked descendants; clean only
                # explicit PIDs written by this synthetic tree, never our group.
                if pids.exists():
                    for pid in map(int, pids.read_text().splitlines()):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_timeout_kills_descendants_releases_pipes_and_records_failure(self):
        self.run_synthetic(sleeping=True)

    def test_missing_compiler_calls_records_failure(self):
        self.run_synthetic(sleeping=False)


if __name__ == '__main__':
    unittest.main()
