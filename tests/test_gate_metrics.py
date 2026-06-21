import unittest

from story_automator.core.gate_metrics import (
    compute_gate_metrics,
    detect_flaky_categories,
    detect_timeout_categories,
)


def _hist(
    gate_id="g-001",
    overall="PASS",
    categories=None,
    profile_id="default",
    story_key="E1-001",
):
    return {
        "gate_id": gate_id,
        "story_key": story_key,
        "overall": overall,
        "categories": categories or {},
        "profile_id": profile_id,
        "profile_hash": "aabb",
        "factory_version": "1.15.0",
        "recorded_at": "2026-06-20T12:00:00Z",
        "remediation_cycle": 0,
        "evidence_bundle_hash": "eebb",
        "commit_sha": "abc123",
    }


class ComputeGateMetricsTests(unittest.TestCase):
    def test_empty_history(self) -> None:
        m = compute_gate_metrics([])
        self.assertEqual(m["total_gates"], 0)
        self.assertEqual(m["pass_rate"], 0.0)

    def test_all_pass(self) -> None:
        history = [_hist(gate_id=f"g-{i}", overall="PASS") for i in range(5)]
        m = compute_gate_metrics(history)
        self.assertEqual(m["total_gates"], 5)
        self.assertAlmostEqual(m["pass_rate"], 1.0)
        self.assertAlmostEqual(m["fail_rate"], 0.0)

    def test_mixed_verdicts(self) -> None:
        history = [
            _hist(gate_id="g-0", overall="PASS"),
            _hist(gate_id="g-1", overall="FAIL"),
            _hist(gate_id="g-2", overall="CONCERNS"),
            _hist(gate_id="g-3", overall="WAIVED"),
        ]
        m = compute_gate_metrics(history)
        self.assertEqual(m["total_gates"], 4)
        self.assertAlmostEqual(m["pass_rate"], 0.25)
        self.assertAlmostEqual(m["fail_rate"], 0.25)
        self.assertAlmostEqual(m["concerns_rate"], 0.25)
        self.assertAlmostEqual(m["waived_rate"], 0.25)

    def test_per_category_counts(self) -> None:
        history = [
            _hist(gate_id="g-0", categories={
                "security": {"verdict": "PASS", "rationale": ""},
            }),
            _hist(gate_id="g-1", categories={
                "security": {"verdict": "FAIL", "rationale": "vuln"},
            }),
        ]
        m = compute_gate_metrics(history)
        self.assertEqual(m["per_category"]["security"]["pass_count"], 1)
        self.assertEqual(m["per_category"]["security"]["fail_count"], 1)


    def test_metrics_includes_flaky_from_detector(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        m = compute_gate_metrics(history)
        self.assertIn("correctness", m["flaky_categories"])

    def test_metrics_includes_timeout_from_detector(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            })
            for i in range(4)
        ]
        m = compute_gate_metrics(history)
        self.assertIn("performance", m["timeout_categories"])


class DetectFlakyCategoriesTests(unittest.TestCase):
    def test_no_flaky_when_all_pass(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": "PASS", "rationale": ""},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_flaky_categories(history), [])

    def test_detects_alternating_pass_fail(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        result = detect_flaky_categories(history, min_flips=3)
        self.assertIn("correctness", result)

    def test_below_min_flips_not_flagged(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        result = detect_flaky_categories(history, min_flips=3)
        self.assertEqual(result, [])

    def test_ignores_na_categories(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "accessibility": {"verdict": "NA", "rationale": ""},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_flaky_categories(history), [])


class DetectTimeoutCategoriesTests(unittest.TestCase):
    def test_no_timeouts(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "PASS", "rationale": "clean"},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_timeout_categories(history), [])

    def test_high_timeout_rate_detected(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            })
            for i in range(4)
        ] + [
            _hist(gate_id="g-4", categories={
                "performance": {"verdict": "PASS", "rationale": "ok"},
            })
        ]
        result = detect_timeout_categories(history, min_rate=0.3)
        self.assertIn("performance", result)

    def test_low_timeout_rate_not_flagged(self) -> None:
        history = [
            _hist(gate_id="g-0", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            }),
        ] + [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {"verdict": "PASS", "rationale": "ok"},
            })
            for i in range(1, 10)
        ]
        result = detect_timeout_categories(history, min_rate=0.3)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
