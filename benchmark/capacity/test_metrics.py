"""Check benchmark measurement contracts without Docker or Cangjie execution."""
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys
import threading
import unittest

sys.dont_write_bytecode = True
import run


class MetricsTests(unittest.TestCase):
    def test_nearest_rank_percentiles(self):
        result = run.distribution(list(range(100, 0, -1)))
        self.assertEqual((result["p50Ms"], result["p95Ms"], result["p99Ms"]), (50, 95, 99))
        with self.assertRaises(ValueError):
            run.distribution([])

    def test_all_packages_visited_before_next_version(self):
        selections = [run.select_item(list(range(256)), n) for n in range(128)]
        self.assertEqual({n // 4 for n in selections}, set(range(64)))
        self.assertTrue(all(sum(n // 4 == package for n in selections) == 2 for package in range(64)))
        self.assertEqual({run.select_item(list(range(256)), n) for n in range(256)}, set(range(256)))

    def test_truncated_response_is_a_recordable_failure(self):
        received = threading.Event()
        class Truncated(BaseHTTPRequestHandler):
            def do_GET(self):
                received.set()
                self.send_response(200)
                self.send_header("Content-Length", "32")
                self.end_headers()
                self.wfile.write(b"short")
                self.close_connection = True

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Truncated) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
            thread.start()
            try:
                try:
                    run.http_request("GET", f"http://127.0.0.1:{server.server_port}/index", timeout=2)
                except run.TestFailure as error:
                    self.assertIn("incomplete HTTP response", str(error))
                except Exception as error:
                    self.fail("HTTP failure bypassed sample recording: " + type(error).__name__)
                else:
                    self.fail("truncated body unexpectedly succeeded")
                self.assertTrue(received.is_set(), "the truncated-response fixture was not reached")
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_complete_index_identity_and_dependencies_checked(self):
        self.assertTrue(hasattr(run, "validate_index"), "complete index validation is missing")
        item = run.fixture(0, 0)
        rows = [run.fixture(0, n)["metadata"]["index"] for n in range(4)]
        def encoded(values):
            return b"\n".join(json.dumps(value).encode() for value in values)
        run.validate_index(encoded(rows), item)
        for field, value in (("name", "wrong_name"), ("dependencies", [dict(name="injected", version="1.0.0")])):
            with self.subTest(field=field):
                wrong = copy.deepcopy(rows)
                wrong[0][field] = value
                with self.assertRaises(run.TestFailure):
                    run.validate_index(encoded(wrong), item)

    def test_wrong_json_row_shape_is_a_recordable_failure(self):
        item = run.fixture(0, 0)
        for wrong in (None, [], {"version": []}):
            with self.subTest(row=wrong):
                try:
                    run.validate_index(json.dumps(wrong).encode(), item)
                except run.TestFailure:
                    pass
                except Exception as error:
                    self.fail("index shape bypassed sample recording: " + type(error).__name__)
                else:
                    self.fail("invalid index row unexpectedly succeeded")


if __name__ == "__main__":
    unittest.main()
