"""A Maple child must never receive or write the caller's profile directory."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maple_smoke


class MapleIsolationTests(unittest.TestCase):
    def test_default_case_uses_owned_home_and_profile(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            protected = root / "caller-profile"
            protected.mkdir()
            sentinel = protected / "keep.txt"
            sentinel.write_text("caller-owned", encoding="utf-8")
            executable = root / "cjpm-identity"
            executable.write_bytes(b"only hashed, never executed")
            worker = root / "profile_probe.py"
            worker.write_text(
                'import os\nfrom pathlib import Path\n'
                'for key in ("HOME", "USERPROFILE"):\n'
                '    (Path(os.environ[key]) / (key + "-child-write")).write_text("probe")\n'
                'print("Total: 1, PASS: 1, FAIL: 0")\n', encoding="utf-8")
            with patch.dict(os.environ, HOME=str(protected), USERPROFILE=str(protected)), \
                    patch.object(maple_smoke, "wait_for_port_release"):
                maple_smoke.run_case("probe", "default", executable, worker, root / "test.cfg",
                                     root / "case.info", 1, root, root)
            self.assertEqual(sorted(path.name for path in protected.iterdir()), ["keep.txt"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "caller-owned")
            owned_home = root / "probe-default-home"
            self.assertTrue((owned_home / "HOME-child-write").is_file())
            self.assertTrue((owned_home / "USERPROFILE-child-write").is_file())


if __name__ == "__main__":
    unittest.main()
