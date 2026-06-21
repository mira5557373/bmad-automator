import unittest

from story_automator.core.gate_metrics import compute_gate_metrics


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


if __name__ == "__main__":
    unittest.main()
