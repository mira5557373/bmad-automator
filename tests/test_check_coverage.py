from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class CoverageCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, data: dict) -> None:
        path = os.path.join(self.tmpdir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_pytest_cov_above_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 95.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_pytest_cov_below_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 50.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_pytest_cov_exact_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 80.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_istanbul_format(self) -> None:
        from story_automator.core.checks.coverage_check import main

        data = {"total": {"lines": {"pct": 92.5}}}
        self._write_json("coverage/coverage-summary.json", data)
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_istanbul_below_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        data = {"total": {"lines": {"pct": 40.0}}}
        self._write_json("coverage/coverage-summary.json", data)
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_no_coverage_data_returns_one(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_unparseable_data_returns_one(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"unknown": "format"})
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([]), 2)

    def test_invalid_threshold_returns_two(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([self.tmpdir, "abc"]), 2)
