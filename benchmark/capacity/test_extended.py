"""Contracts for bounded soak scheduling and large immutable index fixtures."""
import copy
import json
import unittest

import run
import extended


class ExtendedTests(unittest.TestCase):
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
