from __future__ import annotations

import unittest


class BurnInUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main([]), 2)

    def test_too_few_args_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main(["/tmp", "5", "0"]), 2)

    def test_non_numeric_runs_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main(["/tmp", "abc", "0", '["pytest"]']), 2)


class DetectFlakyTests(unittest.TestCase):
    def test_consistent_pass_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [True, True, True],
            "test_b": [True, True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_consistent_fail_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [False, False, False],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_mixed_results_is_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [True, False, True],
            "test_b": [True, True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, ["test_a"])

    def test_single_run_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {"test_a": [True]}
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_empty_results(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        flaky = detect_flaky({})
        self.assertEqual(flaky, [])

    def test_multiple_flaky_sorted(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_c": [True, False],
            "test_a": [False, True],
            "test_b": [True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, ["test_a", "test_c"])


class ParseTestOutputTests(unittest.TestCase):
    def test_parses_pytest_output(self) -> None:
        from story_automator.core.checks.burn_in_check import parse_test_names

        output = (
            "tests/test_a.py::test_one PASSED\n"
            "tests/test_a.py::test_two FAILED\n"
            "tests/test_b.py::test_three PASSED\n"
        )
        results = parse_test_names(output)
        self.assertIn("tests/test_a.py::test_one", results)
        self.assertTrue(results["tests/test_a.py::test_one"])
        self.assertIn("tests/test_a.py::test_two", results)
        self.assertFalse(results["tests/test_a.py::test_two"])

    def test_empty_output(self) -> None:
        from story_automator.core.checks.burn_in_check import parse_test_names

        results = parse_test_names("")
        self.assertEqual(results, {})
