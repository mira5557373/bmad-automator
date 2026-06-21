from __future__ import annotations

import unittest


class MutationCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main([]), 2)

    def test_two_args_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "mutmut"]), 2)

    def test_unsupported_tool_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "unknown", "80"]), 2)

    def test_non_numeric_threshold_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "mutmut", "abc"]), 2)


class ParseMutmutResultsTests(unittest.TestCase):
    def test_parses_summary_line(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        output = (
            "Legend for output:\n"
            "Killed 85 out of 100 mutants\n"
            "Survived: 15\n"
        )
        result = parse_mutmut_results(output)
        self.assertEqual(result["killed"], 85)
        self.assertEqual(result["total"], 100)
        self.assertAlmostEqual(result["score"], 85.0)

    def test_zero_mutants(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        output = "No mutants generated\n"
        result = parse_mutmut_results(output)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["score"], 100.0)

    def test_empty_output(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        result = parse_mutmut_results("")
        self.assertEqual(result["score"], -1)


class ParseStrykerResultsTests(unittest.TestCase):
    def test_parses_summary(self) -> None:
        from story_automator.core.checks.mutation_check import parse_stryker_results

        output = (
            "All tests\n"
            "Mutation score: 92.50\n"
            "Killed: 37, Survived: 3, Timeout: 0, No coverage: 0\n"
        )
        result = parse_stryker_results(output)
        self.assertAlmostEqual(result["score"], 92.5)

    def test_empty_output(self) -> None:
        from story_automator.core.checks.mutation_check import parse_stryker_results

        result = parse_stryker_results("")
        self.assertEqual(result["score"], -1)


class CheckThresholdTests(unittest.TestCase):
    def test_above_threshold_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(85.0, 80)
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_below_threshold_fails(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(60.0, 80)
        self.assertFalse(ok)
        self.assertTrue(any("60" in i for i in issues))

    def test_equal_threshold_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(80.0, 80)
        self.assertTrue(ok)

    def test_negative_score_fails(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(-1, 80)
        self.assertFalse(ok)

    def test_zero_total_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(100.0, 80)
        self.assertTrue(ok)
