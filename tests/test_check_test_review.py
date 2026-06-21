from __future__ import annotations

import json
import os
import tempfile
import unittest


class TestReviewUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_non_numeric_score_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main(["/tmp", "abc"]), 2)


class ReadTeaReviewTests(unittest.TestCase):
    def test_reads_valid_review(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump({
                "overall_score": 85,
                "dimensions": {
                    "assertion_quality": 90,
                    "isolation": 80,
                    "coverage_depth": 85,
                },
            }, f)
            path = f.name
        try:
            review = read_tea_review(path)
            self.assertEqual(review["overall_score"], 85)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        review = read_tea_review("/nonexistent/path.json")
        self.assertEqual(review, {})

    def test_invalid_json_returns_empty(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            f.write("not json")
            path = f.name
        try:
            review = read_tea_review(path)
            self.assertEqual(review, {})
        finally:
            os.unlink(path)


class CheckScoreTests(unittest.TestCase):
    def test_above_threshold_passes(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 85}
        ok, issues = check_score(review, 70)
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_below_threshold_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 50}
        ok, issues = check_score(review, 70)
        self.assertFalse(ok)
        self.assertTrue(any("50" in i for i in issues))

    def test_equal_threshold_passes(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 70}
        ok, issues = check_score(review, 70)
        self.assertTrue(ok)

    def test_missing_score_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {}
        ok, issues = check_score(review, 70)
        self.assertFalse(ok)

    def test_empty_review_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        ok, issues = check_score({}, 70)
        self.assertFalse(ok)


class MainIntegrationTests(unittest.TestCase):
    def test_review_above_threshold_exits_0(self) -> None:
        from story_automator.core.checks.test_review_check import main

        checkout = tempfile.mkdtemp()
        try:
            tea_dir = os.path.join(checkout, "_bmad", "gate", "tea")
            os.makedirs(tea_dir)
            with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
                json.dump({"overall_score": 85}, f)
            self.assertEqual(main([checkout, "70"]), 0)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_review_file_exits_0(self) -> None:
        from story_automator.core.checks.test_review_check import main

        checkout = tempfile.mkdtemp()
        try:
            self.assertEqual(main([checkout, "70"]), 0)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
