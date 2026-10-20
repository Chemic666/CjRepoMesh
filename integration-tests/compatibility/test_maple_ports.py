"""Regression for a previous Maple fixture's transient listener teardown."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import maple_smoke


class MaplePortTests(unittest.TestCase):
    def test_transient_listener_release_does_not_abort_next_case(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            executable = root / "fixture"
            executable.write_bytes(b"fixture executable identity")
            passed = subprocess.CompletedProcess([], 0, "Total: 1, PASS: 1, FAIL: 0")
            with patch.object(maple_smoke, "occupied_ports", side_effect=[[39138], [], []]), \
                    patch.object(maple_smoke.time, "sleep"), \
                    patch.object(maple_smoke.subprocess, "run", return_value=passed) as run:
                maple_smoke.run_case("fixture", "transient", executable, root / "main.py",
                                     root / "test.cfg", root / "case.info", 1, root, root)
                run.assert_called_once()

    def test_persistent_listener_is_not_ignored_or_terminated(self):
        with patch.object(maple_smoke, "occupied_ports", return_value=[39138]), \
                patch.object(maple_smoke.time, "sleep"), \
                patch.object(maple_smoke.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "still listening"):
                maple_smoke.run_case("fixture", "occupied", Path("fixture"), Path("main.py"),
                                     Path("test.cfg"), Path("case.info"), 1, Path("."), Path("."))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
