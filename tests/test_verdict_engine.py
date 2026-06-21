from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from story_automator.core.gate_schema import (
    make_evidence_record,
    make_llm_evidence_record,
)
from story_automator.core.evidence_io import (
    can_reuse_gate_file,
    load_gate_file,
    persist_evidence_record,
)
from story_automator.core.product_profile import compute_profile_hash
from story_automator.core.gate_schema import GATE_SCHEMA_VERSION, make_waiver
from story_automator.core.verdict_engine import (
    adjudicate,
    apply_waivers,
    build_gate_file,
    compute_all_verdicts,
    compute_category_verdict,
    evaluate_gate,
    group_evidence_by_category,
    has_llm_low_confidence,
)


class GroupEvidenceByCategoryTests(unittest.TestCase):
    def test_groups_by_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="correctness", status="ok"),
            make_evidence_record(collector="b", tool="t", category="security", status="ok"),
            make_evidence_record(collector="c", tool="t", category="correctness", status="violation"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertEqual(len(grouped["correctness"]), 2)
        self.assertEqual(len(grouped["security"]), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(group_evidence_by_category([]), {})

    def test_single_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="static", status="ok"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertIn("static", grouped)
        self.assertEqual(len(grouped["static"]), 1)


class HasLlmLowConfidenceTests(unittest.TestCase):
    def test_no_llm_evidence(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_high_confidence_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=8, rationale="good",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_low_confidence_detected(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))

    def test_boundary_5_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=5, rationale="ok",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_mixed_deterministic_and_llm(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=4, rationale="weak",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))


class ComputeCategoryVerdictTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
    }
    REQ = {"coverage_pct": 90, "levels": [], "priority": "P1"}

    def test_pass_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="violation",
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_llm_low_confidence_downgrades_pass_to_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain about edge cases",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "CONCERNS")
        self.assertIn("confidence", result["rationale"].lower())

    def test_llm_low_confidence_does_not_upgrade_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="violation"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_result_includes_evidence_refs(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertIn("evidence_refs", result)
        self.assertIsInstance(result["evidence_refs"], list)


class ComputeAllVerdictsTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {
            "code": ["correctness", "security", "static"],
            "system": [],
        },
        "categories_na": ["accessibility", "performance"],
    }

    def test_na_categories_get_na_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["accessibility"]["verdict"], "NA")
        self.assertEqual(verdicts["performance"]["verdict"], "NA")
        self.assertIn("profile-declared", verdicts["accessibility"]["rationale"])

    def test_na_verdict_has_consistent_shape(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        na_verdict = verdicts["accessibility"]
        self.assertIn("required", na_verdict)
        self.assertIn("actual", na_verdict)
        self.assertIn("evidence_refs", na_verdict)
        self.assertEqual(na_verdict["required"], {})
        self.assertEqual(na_verdict["actual"], {})
        self.assertEqual(na_verdict["evidence_refs"], [])

    def test_evidence_categories_get_computed_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["correctness"]["verdict"], "PASS")
        self.assertEqual(verdicts["security"]["verdict"], "PASS")

    def test_empty_evidence_for_active_category_fails_closed(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": ["correctness", "security"], "system": []}
        profile["categories_na"] = []
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertEqual(verdicts["security"]["verdict"], "FAIL")

    def test_returns_all_active_plus_na_categories(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok"),
            make_evidence_record(collector="c", tool="t", category="static",
                                 status="ok"),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertIn("correctness", verdicts)
        self.assertIn("security", verdicts)
        self.assertIn("static", verdicts)
        self.assertIn("accessibility", verdicts)
        self.assertIn("performance", verdicts)

    def test_extra_evidence_category_not_in_profile_still_evaluated(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="docs",
                                 status="ok"),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": [], "system": []}
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertIn("docs", verdicts)


class AdjudicateTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def test_all_pass_overall_pass(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(result["categories"]["security"]["verdict"], "PASS")

    def test_any_fail_overall_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 3},
                                 findings=["vuln1", "vuln2", "vuln3"]),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")

    def test_concerns_without_fail_overall_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 85, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "CONCERNS")

    def test_unmitigated_risk_9_forces_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 100, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1",
                           has_unmitigated_risk_9=True)
        self.assertEqual(result["overall"], "FAIL")

    def test_result_includes_evidence_bundle_hash(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertIn("evidence_bundle_hash", result)
        self.assertEqual(len(result["evidence_bundle_hash"]), 16)

    def test_result_includes_profile_hash(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertIn("profile_hash", result)
        self.assertTrue(len(result["profile_hash"]) > 0)

    def test_empty_evidence_all_active_fail(self) -> None:
        result = adjudicate([], self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")


class ApplyWaiversTests(unittest.TestCase):
    def _failing_adjudication(self) -> dict:
        return {
            "categories": {
                "security": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "vuln"},
                "correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"},
            },
            "overall": "FAIL",
        }

    def _gate_stub(self) -> dict:
        return {
            "categories": {
                "security": {"verdict": "FAIL"},
                "correctness": {"verdict": "PASS"},
            },
            "profile": {"id": "test", "version": 1, "hash": "aabbccdd"},
        }

    def test_valid_waiver_produces_waived(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="false positive",
            profile_hash="aabbccdd",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "WAIVED")
        self.assertEqual(len(valid), 1)

    def test_expired_waiver_keeps_fail(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-01T00:00:00Z", expires_at="2026-06-15T00:00:00Z",
            failing_categories=["security"], reason="expired",
            profile_hash="aabbccdd",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)
        self.assertIn("expired", rationale)

    def test_no_waivers_keeps_original(self) -> None:
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [], self._gate_stub(),
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)

    def test_pass_verdict_ignores_waivers(self) -> None:
        adj = {"categories": {"correctness": {"verdict": "PASS"}}, "overall": "PASS"}
        stub = {"categories": {"correctness": {"verdict": "PASS"}},
                "profile": {"hash": "aabb"}}
        overall, valid, rationale = apply_waivers(adj, [], stub)
        self.assertEqual(overall, "PASS")

    def test_profile_hash_mismatch_rejects_waiver(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="reason",
            profile_hash="wrong_hash",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)


class BuildGateFileTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def _evidence(self) -> list:
        return [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]

    def test_pass_gate_file(self) -> None:
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g1", target={"kind": "story", "id": "E1.S1"},
            commit_sha="abc123", profile=self.PROFILE,
            factory_version="0.1.0",
        )
        self.assertEqual(gate["gate_id"], "g1")
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["schema_version"], GATE_SCHEMA_VERSION)
        self.assertEqual(gate["commit_sha"], "abc123")
        self.assertIn("hash", gate["profile"])

    def test_fail_gate_file(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="violation"),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok"),
        ]
        adj = adjudicate(evidence, self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g2", target={"kind": "story", "id": "E1.S2"},
            commit_sha="def456", profile=self.PROFILE,
            factory_version="0.1.0",
        )
        self.assertEqual(gate["overall"], "FAIL")

    def test_waived_gate_file(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 1},
                                 findings=["vuln"]),
        ]
        adj = adjudicate(evidence, self.PROFILE, priority="P1")
        profile_hash = adj["profile_hash"]
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="false positive",
            profile_hash=profile_hash,
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        gate = build_gate_file(
            adj, gate_id="g3", target={"kind": "story", "id": "E1.S3"},
            commit_sha="ghi789", profile=self.PROFILE,
            factory_version="0.1.0", waivers=[waiver], now=now,
        )
        self.assertEqual(gate["overall"], "WAIVED")
        self.assertEqual(len(gate["waivers"]), 1)

    def test_gate_file_has_evidence_bundle_hash(self) -> None:
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g4", target={"kind": "story", "id": "E1.S4"},
            commit_sha="abc", profile=self.PROFILE, factory_version="0.1.0",
        )
        self.assertEqual(len(gate["evidence_bundle_hash"]), 16)

    def test_gate_file_validates(self) -> None:
        from story_automator.core.gate_schema import validate_gate_file
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g5", target={"kind": "story", "id": "E1.S5"},
            commit_sha="abc", profile=self.PROFILE, factory_version="0.1.0",
        )
        validate_gate_file(gate)


class EvaluateGateTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def _setup_evidence(self, tmp: str, gate_id: str) -> None:
        persist_evidence_record(tmp, gate_id, make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        ))
        persist_evidence_record(tmp, gate_id, make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="ok", metrics={"sast_high_count": 0},
        ))

    def test_end_to_end_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_evidence(tmp, "eval-g1")
            gate = evaluate_gate(
                tmp, "eval-g1", commit_sha="abc123",
                target={"kind": "story", "id": "E1.S1"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "PASS")
            self.assertEqual(gate["gate_id"], "eval-g1")

    def test_persists_gate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_evidence(tmp, "eval-g2")
            evaluate_gate(
                tmp, "eval-g2", commit_sha="abc123",
                target={"kind": "story", "id": "E1.S2"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            gate_path = Path(tmp) / "_bmad" / "gate" / "verdicts" / "eval-g2.json"
            self.assertTrue(gate_path.is_file())

    def test_end_to_end_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "eval-g3", make_evidence_record(
                collector="runner", tool="pytest", category="correctness",
                status="violation",
            ))
            persist_evidence_record(tmp, "eval-g3", make_evidence_record(
                collector="scanner", tool="semgrep", category="security",
                status="ok",
            ))
            gate = evaluate_gate(
                tmp, "eval-g3", commit_sha="def456",
                target={"kind": "story", "id": "E1.S3"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "FAIL")

    def test_no_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = evaluate_gate(
                tmp, "eval-g4", commit_sha="xyz",
                target={"kind": "story", "id": "E1.S4"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "FAIL")


class VerdictEngineDeterminismTests(unittest.TestCase):
    PROFILE = {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def test_same_input_same_output(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        r1 = adjudicate(evidence, self.PROFILE, priority="P1")
        r2 = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(r1["overall"], r2["overall"])
        self.assertEqual(r1["evidence_bundle_hash"], r2["evidence_bundle_hash"])
        self.assertEqual(r1["profile_hash"], r2["profile_hash"])

    def test_evidence_order_does_not_affect_verdict(self) -> None:
        r1 = make_evidence_record(collector="a", tool="t", category="correctness",
                                  status="ok", metrics={"coverage_pct": 95, "regressions": 0})
        r2 = make_evidence_record(collector="b", tool="t", category="security",
                                  status="ok", metrics={"sast_high_count": 0})
        adj1 = adjudicate([r1, r2], self.PROFILE, priority="P1")
        adj2 = adjudicate([r2, r1], self.PROFILE, priority="P1")
        self.assertEqual(adj1["overall"], adj2["overall"])

    def test_all_na_categories_pass(self) -> None:
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": [], "system": []}
        profile["categories_na"] = ["correctness", "security"]
        result = adjudicate([], profile, priority="P1")
        self.assertEqual(result["overall"], "PASS")

    def test_mixed_na_and_active(self) -> None:
        profile = dict(self.PROFILE)
        profile["categories_na"] = ["security"]
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, profile, priority="P1")
        self.assertEqual(result["categories"]["security"]["verdict"], "NA")
        self.assertEqual(result["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(result["overall"], "PASS")

    def test_fail_takes_precedence_over_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 85, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 1},
                                 findings=["vuln"]),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")


class GateRoundTripTests(unittest.TestCase):
    PROFILE = {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [],
    }

    def test_evaluate_then_reload_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g1", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g1", commit_sha="sha1",
                target={"kind": "story", "id": "E1.S1"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            loaded = load_gate_file(tmp, "rt-g1")
            self.assertEqual(loaded["overall"], gate["overall"])
            self.assertEqual(loaded["gate_id"], gate["gate_id"])

    def test_reuse_validation_passes_for_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g2", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g2", commit_sha="sha2",
                target={"kind": "story", "id": "E1.S2"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            ok, reason = can_reuse_gate_file(
                gate, commit_sha="sha2",
                profile_hash=compute_profile_hash(self.PROFILE),
                factory_version="0.1.0",
            )
            self.assertTrue(ok, reason)

    def test_reuse_fails_on_commit_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g3", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g3", commit_sha="sha3",
                target={"kind": "story", "id": "E1.S3"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            ok, reason = can_reuse_gate_file(
                gate, commit_sha="sha-different",
                profile_hash=compute_profile_hash(self.PROFILE),
                factory_version="0.1.0",
            )
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
