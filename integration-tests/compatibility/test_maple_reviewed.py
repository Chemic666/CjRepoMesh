"""Fail-closed selection and truthful result accounting for reviewed Maple runs."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch


class ReviewedMapleTests(unittest.TestCase):
    def setUp(self):
        try:
            self.runner = importlib.import_module("maple_reviewed")
        except ModuleNotFoundError:
            self.fail("Reviewed Maple preflight and result accounting are not implemented")
        parent = Path(__file__).resolve().parents[1] / ".tmp"
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.suite = self.root / "upstream"
        self.suite.mkdir()
        self.case = self.suite / "local"
        self.case.mkdir()
        (self.case / "local.info").write_text("// EXEC: true\n")
        (self.case / "cjpm.toml").write_text('[package]\nname="local"\n')
        self.framework = self.root / "framework"
        self.framework.mkdir()
        (self.framework / "main.py").write_text("pass\n")
        (self.suite / "test.cfg").write_text("[suffix]\ninfo = //\n")
        self.client = self.root / "cjpm"
        self.client.write_bytes(b"synthetic binary identity, never executed")
        self.manifest = {
            "schema": 1,
            "clientSha256": self.runner.file_sha256(self.client),
            "frameworkFiles": self.runner.snapshot_tree(self.framework),
            "config": "test.cfg",
            "configSha256": self.runner.file_sha256(self.suite / "test.cfg"),
            "cases": [{"path": "local/local.info", "reason": "Reviewed local no-op",
                       "files": self.runner.snapshot_tree(self.case)}],
        }

    def test_explicit_reviewed_case_is_accepted(self):
        cases = self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        self.assertEqual([str(case.relative_to(self.suite)) for case in cases], [str(Path("local/local.info"))])

    def test_added_helper_cannot_run_without_review(self):
        (self.case / "helper.sh").write_text("echo unexpected\n")
        with self.assertRaisesRegex(ValueError, "fixture changed"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_manifest_cannot_escape_snapshot(self):
        self.manifest["cases"][0]["path"] = "../cjpm"
        with self.assertRaisesRegex(ValueError, "relative.*info"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_empty_selection_does_not_mean_run_everything(self):
        self.manifest["cases"] = []
        with self.assertRaisesRegex(ValueError, "nonempty explicit"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_indirect_dependency_requires_its_own_frozen_review(self):
        shared = self.suite / "shared"
        shared.mkdir()
        (shared / "helper.sh").write_text("echo reviewed\n")
        (self.case / "local.info").write_text("// DEPENDENCE: ../shared\n// EXEC: true\n")
        self.manifest["cases"][0]["files"] = self.runner.snapshot_tree(self.case)
        with self.assertRaisesRegex(ValueError, "dependency"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        self.manifest["cases"][0]["dependencies"] = {"shared": self.runner.snapshot_tree(shared)}
        self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        (shared / "helper.sh").write_text("echo changed\n")
        with self.assertRaisesRegex(ValueError, "dependency"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_multiple_dependencies_are_independently_frozen_and_staged(self):
        first, second = self.suite / "first", self.suite / "second"
        first.mkdir()
        second.mkdir()
        (first / "value").write_bytes(b"first input")
        (second / "value").write_bytes(b"second input")
        (self.case / "local.info").write_text("// DEPENDENCE: ../%n ../first ../second\n// EXEC: true\n")
        row = self.manifest["cases"][0]
        row["files"] = self.runner.snapshot_tree(self.case)
        row["dependencies"] = {"first": self.runner.snapshot_tree(first),
                               "second": self.runner.snapshot_tree(second)}
        try:
            selected = self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        except ValueError as error:
            self.fail(f"Independently frozen local dependencies must be accepted: {error}")
        owned = self.root / "owned"
        owned.mkdir()
        fixture, _ = self.runner.stage_inputs(selected[0], row, owned)
        self.assertEqual((fixture.parent / "first/value").read_bytes(), b"first input")
        self.assertEqual((fixture.parent / "second/value").read_bytes(), b"second input")
        for directory in (first, second):
            original = (directory / "value").read_bytes()
            (directory / "value").write_bytes(b"unreviewed change")
            with self.assertRaisesRegex(ValueError, "dependency"):
                self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
            (directory / "value").write_bytes(original)
        row["dependencies"].pop("second")
        with self.assertRaisesRegex(ValueError, "dependency"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_multiple_dependencies_reject_escaping_and_ambiguous_destinations(self):
        shared = self.suite / "nested/local"
        shared.mkdir(parents=True)
        (shared / "helper").write_text("reviewed")
        row = self.manifest["cases"][0]
        for directive, message in (
                ("../%n ../../outside", "escaping"),
                ("../%n ../nested/local", "destination"),
                ("../%n; ../nested/local", "Unsupported dependency")):
            with self.subTest(directive=directive):
                (self.case / "local.info").write_text(f"// DEPENDENCE: {directive}\n")
                row["files"] = self.runner.snapshot_tree(self.case)
                row["dependencies"] = {"nested/local": self.runner.snapshot_tree(shared)}
                with self.assertRaisesRegex(ValueError, message):
                    self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_explicit_shell_normalization_changes_only_owned_copy(self):
        (self.case / "cjpm.toml").write_bytes(b'[package]\nname="local"\n')
        helper = self.case / "fake/cjc"
        helper.parent.mkdir()
        helper.write_bytes(b'#!/bin/sh\r\necho "synthetic compiler"\r\n')
        unlisted = self.case / "keep"
        unlisted.write_bytes(b"unlisted\r\n")
        row = self.manifest["cases"][0]
        row["files"] = self.runner.snapshot_tree(self.case)
        row["normalizeLineEndings"] = ["local/fake/cjc"]
        self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        self.assertTrue(callable(getattr(self.runner, "stage_inputs", None)),
                        "Owned-input staging must apply explicit reviewed shell normalization")
        owned = self.root / "owned"
        owned.mkdir()
        fixture, changes = self.runner.stage_inputs(self.case / "local.info", row, owned)
        self.assertEqual((fixture / "fake/cjc").read_bytes(), b'#!/bin/sh\necho "synthetic compiler"\n')
        self.assertEqual((fixture / "keep").read_bytes(), b"unlisted\r\n")
        self.assertEqual(helper.read_bytes(), b'#!/bin/sh\r\necho "synthetic compiler"\r\n')
        self.assertEqual(changes, ["local/fake/cjc"])

    def test_explicit_normalization_requires_frozen_extensionless_shell(self):
        external = self.suite / "not-copied"
        external.mkdir()
        (external / "cjc").write_bytes(b"#!/bin/sh\r\necho outside\r\n")
        helper = self.case / "cjc"
        helper.write_bytes(b"#!/bin/sh\r\necho reviewed\r\n")
        row = self.manifest["cases"][0]
        row["files"] = self.runner.snapshot_tree(self.case)
        for paths in (["../not-copied/cjc"], ["not-copied/cjc"],
                      ["local/cjpm.toml"], ["local/cjc", "local/cjc"], "local/cjc"):
            with self.subTest(paths=paths):
                row["normalizeLineEndings"] = paths
                with self.assertRaises(ValueError):
                    self.runner.preflight(self.manifest, self.suite, self.framework, self.client)
        helper.write_bytes(b"ordinary non-shell text\r\n")
        row["files"] = self.runner.snapshot_tree(self.case)
        row["normalizeLineEndings"] = ["local/cjc"]
        with self.assertRaisesRegex(ValueError, "extensionless /bin/sh"):
            self.runner.preflight(self.manifest, self.suite, self.framework, self.client)

    def test_skip_and_missing_summary_never_count_as_pass(self):
        self.assertEqual(self.runner.result_status(0, "Total: 1, PASS: 1, FAIL: 0"), "PASS")
        self.assertEqual(self.runner.result_status(0, "Total: 1, PASS: 0, FAIL: 0, NOT_RUN: 1"), "SKIP")
        self.assertEqual(self.runner.result_status(0, "no tests discovered"), "FAIL")
        self.assertEqual(self.runner.result_status(1, "Total: 1, PASS: 1, FAIL: 0"), "FAIL")

    @unittest.skipUnless(os.name == "posix", "Linux-owned process group execution")
    def test_execution_isolates_profile_and_preserves_failure_log(self):
        caller = self.root / "caller"
        caller.mkdir()
        (caller / "keep").write_text("preserved")
        (self.framework / "main.py").write_text(
            'import os\nfrom pathlib import Path\n'
            'assert "CJPM_CONFIG" not in os.environ\n'
            'Path(os.environ["HOME"], "owned-write").write_text("synthetic")\n'
            'print("synthetic failure detail", flush=True)\n'
            'print("Total: 1, PASS: 0, FAIL: 1", flush=True)\n'
            'raise SystemExit(1)\n')
        stage, results = self.root / "stage", self.root / "results"
        stage.mkdir()
        results.mkdir()
        with patch.dict(os.environ, HOME=str(caller), USERPROFILE=str(caller), CJPM_CONFIG=str(caller)):
            result = self.runner.execute_one(self.case / "local.info", self.manifest["cases"][0],
                self.client, self.framework, self.suite / "test.cfg", stage, results, 1, 5)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("synthetic failure detail", (results / result["log"]).read_text())
        self.assertEqual([path.name for path in caller.iterdir()], ["keep"])
        self.assertTrue((stage / "case-0001/home/owned-write").is_file())

    @unittest.skipUnless(os.name == "posix", "Linux-owned process group execution")
    def test_random_stage_name_does_not_add_debug_flag_matches(self):
        # Reproduce the official scan-2 -g hazard with a deterministic random
        # suffix. The child prints a real owned cwd and one real debug option.
        (self.framework / "main.py").write_text(
            'import os\nprint("cjc -p " + os.getcwd() + " -g")\n'
            'print("Total: 1, PASS: 1, FAIL: 0")\n')
        self.manifest["frameworkFiles"] = self.runner.snapshot_tree(self.framework)
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        scratch = self.root / "scratch"
        scratch.mkdir()
        results = self.root / "results"
        argv = ["maple_reviewed.py", "--manifest", str(manifest), "--upstream", str(self.suite),
                "--framework", str(self.framework), "--client", str(self.client),
                "--stage-parent", str(scratch), "--results", str(results), "--execute"]
        with patch.object(sys, "argv", argv), \
                patch.object(tempfile, "_get_candidate_names", return_value=iter(["gprobe"])):
            self.assertEqual(self.runner.main(), 0)
        output = (results / "case-0001/runner.log").read_text()
        self.assertEqual(output.count("-g"), 1,
                         "Random temporary directory name must not create an extra -g assertion match")


if __name__ == "__main__":
    unittest.main()
