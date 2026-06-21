# tests/test_check_traceability.py
from __future__ import annotations

import json
import os
import tempfile
import unittest


class TraceabilityCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_invalid_thresholds_json_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main(["/tmp", "not-json"]), 2)


class ReadTeaTraceTests(unittest.TestCase):
    def test_reads_valid_trace(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "traces": [
                    {"ac_id": "AC-1", "priority": "P0", "test_file": "test_a.py", "status": "mapped"},
                    {"ac_id": "AC-2", "priority": "P1", "test_file": "test_b.py", "status": "mapped"},
                    {"ac_id": "AC-3", "priority": "P1", "test_file": "", "status": "unmapped"},
                ],
            }, f)
            path = f.name
        try:
            traces = read_tea_trace(path)
            self.assertEqual(len(traces), 3)
            self.assertEqual(traces[0]["ac_id"], "AC-1")
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        traces = read_tea_trace("/nonexistent/path.json")
        self.assertEqual(traces, [])

    def test_invalid_json_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            traces = read_tea_trace(path)
            self.assertEqual(traces, [])
        finally:
            os.unlink(path)


class GwtFallbackTests(unittest.TestCase):
    def test_maps_matching_acs_only(self) -> None:
        from story_automator.core.checks.traceability_check import gwt_fallback

        checkout = tempfile.mkdtemp()
        try:
            story_dir = os.path.join(checkout, "_bmad", "stories")
            os.makedirs(story_dir)
            with open(os.path.join(story_dir, "story-1.md"), "w") as f:
                f.write(
                    "# Story 1\n"
                    "## Acceptance Criteria\n"
                    "- AC-1 [P0]: User login authentication\n"
                    "- AC-2 [P1]: Admin dashboard display\n"
                )
            test_dir = os.path.join(checkout, "tests")
            os.makedirs(test_dir)
            with open(os.path.join(test_dir, "test_login.py"), "w") as f:
                f.write("def test_given_user_when_login_then_authenticated(): pass\n")
            traces = gwt_fallback(checkout)
            self.assertEqual(len(traces), 2)
            by_id = {t["ac_id"]: t for t in traces}
            self.assertEqual(by_id["AC-1"]["status"], "mapped")
            self.assertEqual(by_id["AC-2"]["status"], "unmapped")
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_story_dir_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import gwt_fallback

        checkout = tempfile.mkdtemp()
        try:
            traces = gwt_fallback(checkout)
            self.assertEqual(traces, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class ComputeCoverageTests(unittest.TestCase):
    def test_full_coverage_passes(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P0", "status": "mapped"},
            {"ac_id": "AC-2", "priority": "P1", "status": "mapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_p0_below_threshold_fails(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P0", "status": "mapped"},
            {"ac_id": "AC-2", "priority": "P0", "status": "unmapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertFalse(ok)
        self.assertTrue(any("P0" in i for i in issues))

    def test_p1_below_threshold_fails(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": f"AC-{i}", "priority": "P1", "status": "unmapped"}
            for i in range(10)
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertFalse(ok)
        self.assertTrue(any("P1" in i for i in issues))

    def test_empty_traces_passes(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        ok, issues = compute_coverage([], {"P0": 100, "P1": 90})
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_unknown_priority_ignored(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P99", "status": "unmapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertTrue(ok)
