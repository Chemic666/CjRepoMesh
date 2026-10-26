"""Contracts for bounded soak scheduling and large immutable index fixtures."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run
import extended


class ExtendedTests(unittest.TestCase):
    def test_phase_and_sample_timestamps_share_the_run_origin(self):
        # Losing either boundary or using a per-phase origin breaks correlation.
        self.assertTrue(hasattr(extended, 'MeasurementClock'), 'measurement clock is missing')
        now = [100.0]
        utc = [datetime(2026, 10, 26, tzinfo=timezone.utc)]
        clock = extended.MeasurementClock(clock=lambda: now[0], utc_now=lambda: utc[0])
        now[0] = 102.0
        utc[0] += timedelta(seconds=2)
        def action(number):
            now[0] = 102.25
            utc[0] += timedelta(seconds=.25)
            return [200], 1024, dict(name='synthetic', version='1.0.0', organization='')
        with tempfile.TemporaryDirectory() as directory:
            phases = []
            run.measure_batch('read', 1, 1, action, 'receive', phases=phases,
                              report=Path(directory), measurements=clock)
            phase = json.loads((Path(directory) / 'samples.json').read_text())[0]
        self.assertEqual(phase['startedAtUtc'], '2026-10-26T00:00:02+00:00')
        self.assertEqual(phase['endedAtUtc'], '2026-10-26T00:00:02.250000+00:00')
        self.assertEqual((phase['startOffsetSeconds'], phase['endOffsetSeconds'], phase['elapsedSeconds']),
                         (2.0, 2.25, .25))
        sample = phase['samples'][0]
        self.assertEqual((sample['startedAtUtc'], sample['endedAtUtc']),
                         (phase['startedAtUtc'], phase['endedAtUtc']))
        self.assertEqual((sample['startOffsetSeconds'], sample['endOffsetSeconds'], sample['elapsedMs']),
                         (2.0, 2.25, 250.0))

    def test_wall_clock_rollback_does_not_change_soak_budget_or_latency(self):
        # Wall time moving backwards must not control deadlines or elapsed time.
        self.assertTrue(hasattr(extended, 'MeasurementClock'), 'measurement clock is missing')
        now = [10.0]
        utc = [datetime(2026, 10, 26, tzinfo=timezone.utc)]
        clock = extended.MeasurementClock(clock=lambda: now[0], utc_now=lambda: utc[0])
        def sleep(seconds):
            now[0] += seconds
            utc[0] -= timedelta(hours=1)
        with tempfile.TemporaryDirectory() as directory:
            phases = []
            rounds = []
            for number in extended.paced_rounds(12, interval=5, clock=lambda: now[0], sleep=sleep):
                def action(n):
                    now[0] += 1
                    utc[0] -= timedelta(minutes=1)
                    return [200], 1, dict(name='synthetic', version='1.0.0', organization='')
                run.measure_batch(f'soak-{number}', 1, 1, action, 'receive', phases=phases,
                                  report=Path(directory), measurements=clock)
                rounds.append(number)
        self.assertEqual(rounds, [0, 1])
        self.assertEqual(now[0], 22.0)
        self.assertTrue(all(p['elapsedSeconds'] == 1 and p['samples'][0]['elapsedMs'] == 1000
                            and p['endedAtUtc'] < p['startedAtUtc'] for p in phases))

    def test_soak_round_records_success_and_failure_then_propagates(self):
        # A failed batch must retain both sample and round evidence, then escape.
        self.assertTrue(hasattr(extended, 'MeasurementClock'), 'measurement clock is missing')
        now = [100.0]
        utc = [datetime(2026, 10, 26, tzinfo=timezone.utc)]
        clock = extended.MeasurementClock(clock=lambda: now[0], utc_now=lambda: utc[0])
        rounds, phases = [], []
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)
            with extended.record_soak_round(report, rounds, 0, clock) as record:
                record['phaseNames'].append('soak-000-mixed')
                now[0] += 2
                utc[0] += timedelta(seconds=2)
            with self.assertRaises(run.TestFailure):
                with extended.record_soak_round(report, rounds, 1, clock) as record:
                    record['phaseNames'].append('soak-001-publish')
                    def failing_action(n):
                        now[0] += 3
                        utc[0] += timedelta(seconds=3)
                        raise run.TestFailure('synthetic rejected operation')
                    run.measure_batch('soak-001-publish', 1, 1, failing_action, 'send',
                                      phases=phases, report=report, measurements=clock)
            saved = json.loads((report / 'soak-rounds.json').read_text())
            samples = json.loads((report / 'samples.json').read_text())
        self.assertEqual([r['sequence'] for r in saved], [0, 1])
        self.assertEqual([r['valid'] for r in saved], [True, False])
        self.assertEqual(saved[1]['phaseNames'], ['soak-001-publish'])
        self.assertEqual(saved[0]['startedAtUtc'], '2026-10-26T00:00:00+00:00')
        self.assertEqual(saved[1]['endedAtUtc'], '2026-10-26T00:00:05+00:00')
        self.assertEqual((saved[1]['startOffsetSeconds'], saved[1]['endOffsetSeconds'],
                          saved[1]['elapsedSeconds']), (2, 5, 3))
        self.assertFalse(samples[0]['samples'][0]['valid'])
        self.assertEqual(samples[0]['samples'][0]['elapsedMs'], 3000)

    def test_soak_recording_failure_preserves_the_original_workload_exception(self):
        # A secondary clock or disk failure must not replace the load failure.
        for failing_step in ('finish', 'write_text'):
            with self.subTest(failing_step=failing_step):
                measurements = extended.MeasurementClock()
                workload_failure = run.TestFailure('synthetic workload failed')
                evidence_failure = OSError('synthetic evidence failure')
                target = measurements if failing_step == 'finish' else Path
                with patch.object(target, failing_step, side_effect=evidence_failure):
                    with self.assertRaises(Exception) as caught:
                        with extended.record_soak_round(Path('unused'), [], 0, measurements):
                            raise workload_failure
                self.assertIs(caught.exception, workload_failure)
                self.assertIs(caught.exception.__cause__, evidence_failure)

    def test_soak_recording_failure_after_success_is_not_a_successful_round(self):
        # Without a workload error, failure to retain evidence must still escape.
        evidence_failure = OSError('synthetic evidence failure')
        with patch.object(Path, 'write_text', side_effect=evidence_failure):
            with self.assertRaises(OSError) as caught:
                with extended.record_soak_round(Path('unused'), [], 0, extended.MeasurementClock()):
                    pass
        self.assertIs(caught.exception, evidence_failure)

    def test_complete_large_index_checks_every_record(self):
        items = extended.index_fixtures()
        self.assertEqual(len(items), 64)
        self.assertEqual(len(items[0]['metadata']['index']['description'].encode()), 65536)
        rows = [item['metadata']['index'] for item in items[:63]]
        body = b'\n'.join(json.dumps(row, separators=(',', ':')).encode() for row in rows) + b'\n'
        self.assertGreater(len(body), 3.9 * 1048576)
        self.assertLess(len(body), 4 * 1048576)
        self.assertGreater(len(body) + len(json.dumps(items[-1]['metadata']['index']).encode()), 4 * 1048576)
        extended.validate_complete_index(body, items[:63])
        corrupt = copy.deepcopy(rows)
        corrupt[-1]['sha256sum'] = '0' * 64
        with self.assertRaises(run.TestFailure):
            extended.validate_complete_index(json.dumps(corrupt[0]).encode() + b'\n' +
                b'\n'.join(json.dumps(row).encode() for row in corrupt[1:]), items[:63])
        for wrong in (body + body.splitlines()[0] + b'\n', b'[]', b'{"version":[]}'):
            with self.subTest(wrong=wrong[:20]), self.assertRaises(run.TestFailure):
                extended.validate_complete_index(wrong, items[:63])

    def test_large_and_stream_payloads_have_correct_digests(self):
        import hashlib
        large = extended.large_fixtures()
        self.assertEqual(len(large), 4)
        self.assertEqual(len({i['sha256'] for i in large}), 4)
        for item in large + [extended.stream_fixture(119)]:
            self.assertEqual(hashlib.sha256(item['body']).hexdigest(), item['metadata']['index']['sha256sum'])
        self.assertTrue(all(len(item['body']) == 16 * 1048576 for item in large))
        self.assertEqual(len(extended.stream_fixture(119)['body']), 262144)
        self.assertEqual(extended.stream_fixture(119)['version'], '1.0.119')

    def test_pacing_runs_until_deadline_without_post_deadline_round(self):
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        rounds = list(extended.paced_rounds(12, interval=5, clock=lambda: now[0], sleep=sleep))
        self.assertEqual(rounds, [0, 1, 2])
        self.assertEqual(now[0], 12)

    def test_slow_round_counts_against_budget_and_does_not_catch_up(self):
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        iterator = extended.paced_rounds(10, interval=5, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(next(iterator), 0)
        now[0] = 11
        self.assertEqual(list(iterator), [])
        self.assertEqual(now[0], 11)


if __name__ == '__main__':
    unittest.main()
