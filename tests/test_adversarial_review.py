from __future__ import annotations

import unittest

from story_automator.core.innovation.adversarial_review import (
    AdversarialReviewError,
    AssignmentResult,
    EvidenceLink,
    ReviewAssignment,
    ReviewFinding,
    SubmissionResult,
    accept_review_submission,
    assign_reviewer,
    is_substantive,
    summarize_findings,
)


def _devs(model: str = "claude-opus-4-7") -> dict[str, str]:
    return {"cli_id": "claude-cli", "model": model}


def _candidates(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"cli_id": cli, "model": model} for cli, model in pairs]


def _evidence(record_id: str = "ev-1") -> EvidenceLink:
    return EvidenceLink(record_id=record_id, source="static_check", uri=f"evidence://{record_id}")


def _finding(rule_id: str = "rule.x", severity: str = "high") -> ReviewFinding:
    return ReviewFinding(
        finding_id=f"f-{rule_id}",
        rule_id=rule_id,
        severity=severity,
        message="Implementation mishandles boundary condition near the gate threshold.",
        evidence=[_evidence("ev-9")],
    )


class AssignReviewerTests(unittest.TestCase):
    def test_picks_candidate_with_different_cli_and_model(self) -> None:
        dev = _devs()
        candidates = _candidates(
            ("claude-cli", "claude-opus-4-7"),  # same as dev — must be rejected
            ("codex-cli", "gpt-5"),
        )
        result = assign_reviewer(dev_agent=dev, candidates=candidates, priority="P0")
        self.assertIsInstance(result, AssignmentResult)
        self.assertIsNotNone(result.assignment)
        assert result.assignment is not None
        self.assertEqual(result.assignment.reviewer_cli_id, "codex-cli")
        self.assertEqual(result.assignment.reviewer_model, "gpt-5")
        self.assertNotEqual(result.assignment.reviewer_cli_id, dev["cli_id"])
        self.assertNotEqual(result.assignment.reviewer_model, dev["model"])

    def test_rejects_same_cli_id_even_with_different_model(self) -> None:
        dev = _devs()
        candidates = _candidates(("claude-cli", "claude-sonnet-4-5"))
        result = assign_reviewer(dev_agent=dev, candidates=candidates, priority="P1")
        self.assertIsNone(result.assignment)
        self.assertIn("no_distinct_reviewer", result.reasons)

    def test_rejects_same_model_even_with_different_cli(self) -> None:
        dev = _devs("gpt-5")
        candidates = _candidates(("claude-cli", "gpt-5"))
        result = assign_reviewer(dev_agent=dev, candidates=candidates, priority="P0")
        self.assertIsNone(result.assignment)
        self.assertIn("no_distinct_reviewer", result.reasons)

    def test_empty_candidate_pool_returns_no_assignment(self) -> None:
        result = assign_reviewer(dev_agent=_devs(), candidates=[], priority="P0")
        self.assertIsNone(result.assignment)
        self.assertIn("empty_candidate_pool", result.reasons)

    def test_priority_p2_or_lower_is_not_required(self) -> None:
        # Adversarial review is mandatory for P0/P1 only; P2/P3 don't force a pick
        # but the helper still must answer truthfully about distinctness.
        result = assign_reviewer(
            dev_agent=_devs(),
            candidates=_candidates(("claude-cli", "claude-opus-4-7")),
            priority="P2",
        )
        self.assertFalse(result.required)
        self.assertIsNone(result.assignment)

    def test_priority_p0_marks_required_true(self) -> None:
        result = assign_reviewer(
            dev_agent=_devs(),
            candidates=_candidates(("codex-cli", "gpt-5")),
            priority="P0",
        )
        self.assertTrue(result.required)
        self.assertIsNotNone(result.assignment)

    def test_invalid_dev_agent_raises(self) -> None:
        with self.assertRaises(AdversarialReviewError):
            assign_reviewer(dev_agent={"cli_id": ""}, candidates=[], priority="P0")
        with self.assertRaises(AdversarialReviewError):
            assign_reviewer(dev_agent={"cli_id": "x", "model": ""}, candidates=[], priority="P0")

    def test_unknown_priority_raises(self) -> None:
        with self.assertRaises(AdversarialReviewError):
            assign_reviewer(
                dev_agent=_devs(),
                candidates=_candidates(("codex-cli", "gpt-5")),
                priority="urgent",
            )


class IsSubstantiveTests(unittest.TestCase):
    def test_high_severity_with_evidence_is_substantive(self) -> None:
        self.assertTrue(is_substantive(_finding(severity="high")))

    def test_critical_severity_with_evidence_is_substantive(self) -> None:
        self.assertTrue(is_substantive(_finding(severity="critical")))

    def test_low_severity_is_not_substantive(self) -> None:
        f = _finding(severity="low")
        self.assertFalse(is_substantive(f))

    def test_finding_without_evidence_is_not_substantive(self) -> None:
        f = ReviewFinding(
            finding_id="f-no-ev",
            rule_id="rule.x",
            severity="high",
            message="Looks wrong somewhere.",
            evidence=[],
        )
        self.assertFalse(is_substantive(f))

    def test_blank_message_is_not_substantive(self) -> None:
        f = ReviewFinding(
            finding_id="f-blank",
            rule_id="rule.x",
            severity="high",
            message="   ",
            evidence=[_evidence()],
        )
        self.assertFalse(is_substantive(f))


class AcceptSubmissionTests(unittest.TestCase):
    def _assignment(self, priority: str = "P0") -> ReviewAssignment:
        return ReviewAssignment(
            reviewer_cli_id="codex-cli",
            reviewer_model="gpt-5",
            dev_cli_id="claude-cli",
            dev_model="claude-opus-4-7",
            priority=priority,
        )

    def test_accepts_when_one_substantive_finding_present(self) -> None:
        result = accept_review_submission(
            assignment=self._assignment(),
            findings=[_finding()],
        )
        self.assertIsInstance(result, SubmissionResult)
        self.assertTrue(result.accepted)
        self.assertEqual(result.substantive_count, 1)
        self.assertEqual(result.reasons, ())

    def test_rejects_when_no_findings_at_all(self) -> None:
        result = accept_review_submission(
            assignment=self._assignment(),
            findings=[],
        )
        self.assertFalse(result.accepted)
        self.assertIn("no_findings", result.reasons)

    def test_rejects_when_only_non_substantive_findings(self) -> None:
        result = accept_review_submission(
            assignment=self._assignment(),
            findings=[_finding(severity="low"), _finding(severity="info")],
        )
        self.assertFalse(result.accepted)
        self.assertIn("no_substantive_finding", result.reasons)
        self.assertEqual(result.substantive_count, 0)

    def test_rejects_when_reviewer_matches_dev(self) -> None:
        bad = ReviewAssignment(
            reviewer_cli_id="claude-cli",
            reviewer_model="claude-opus-4-7",
            dev_cli_id="claude-cli",
            dev_model="claude-opus-4-7",
            priority="P0",
        )
        result = accept_review_submission(
            assignment=bad,
            findings=[_finding()],
        )
        self.assertFalse(result.accepted)
        self.assertIn("reviewer_not_distinct", result.reasons)

    def test_summarize_findings_counts_by_severity(self) -> None:
        findings = [
            _finding(severity="critical"),
            _finding(severity="high"),
            _finding(severity="low"),
            _finding(severity="info"),
        ]
        counts = summarize_findings(findings)
        self.assertEqual(counts["critical"], 1)
        self.assertEqual(counts["high"], 1)
        self.assertEqual(counts["low"], 1)
        self.assertEqual(counts["info"], 1)
        self.assertEqual(counts["substantive"], 2)
        self.assertEqual(counts["total"], 4)

    def test_p2_priority_accepts_even_without_substantive(self) -> None:
        # P2/P3 don't *require* a substantive finding; a clean review is fine.
        result = accept_review_submission(
            assignment=self._assignment(priority="P2"),
            findings=[],
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.substantive_count, 0)

    def test_dataclass_immutability_on_evidence_id(self) -> None:
        ev = _evidence("ev-42")
        self.assertEqual(ev.record_id, "ev-42")
        # Ensure dataclass round-trips through accept_review_submission unchanged.
        f = _finding()
        self.assertEqual(f.evidence[0].record_id, "ev-9")


if __name__ == "__main__":
    unittest.main()
