from __future__ import annotations

import json
import tempfile
import unittest

from story_automator.core.readiness_gate import (
    READINESS_VERDICTS,
    check_readiness,
    format_blocker_summary,
    load_readiness_result,
    persist_readiness_result,
    resolve_story_blockers,
)
from story_automator.core.risk_profile import make_risk_entry


class ResolveStoryBlockersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "id": "msme-erp", "version": 1,
            "forbidden_until": {
                "ADR-0083": ["E*.envelope-*"],
                "DG-2": ["*.cost-to-serve"],
                "DG-3": ["E*.ca-channel-*"],
            },
        }

    def test_blocked_by_adr(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1.envelope-auth")
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["adr_id"], "ADR-0083")

    def test_blocked_by_multiple_adrs(self) -> None:
        profile = {
            "id": "test", "version": 1,
            "forbidden_until": {
                "ADR-1": ["E1-*"],
                "ADR-2": ["E1-*"],
            },
        }
        blockers = resolve_story_blockers(profile, "E1-story")
        self.assertEqual(len(blockers), 2)

    def test_not_blocked(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1-safe-story")
        self.assertEqual(blockers, [])

    def test_no_forbidden_until(self) -> None:
        profile = {"id": "test", "version": 1}
        blockers = resolve_story_blockers(profile, "any-story")
        self.assertEqual(blockers, [])

    def test_cost_to_serve_blocked(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1.cost-to-serve")
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["adr_id"], "DG-2")


class FormatBlockerSummaryTests(unittest.TestCase):
    def test_empty_blockers(self) -> None:
        self.assertEqual(format_blocker_summary([]), "no blockers")

    def test_single_blocker(self) -> None:
        blockers = [{"adr_id": "ADR-0083", "patterns": ["E*.envelope-*"], "story_id": "E1.envelope-auth"}]
        summary = format_blocker_summary(blockers)
        self.assertIn("ADR-0083", summary)

    def test_multiple_blockers(self) -> None:
        blockers = [
            {"adr_id": "ADR-1", "patterns": ["E1-*"], "story_id": "E1-x"},
            {"adr_id": "ADR-2", "patterns": ["E1-*"], "story_id": "E1-x"},
        ]
        summary = format_blocker_summary(blockers)
        self.assertIn("ADR-1", summary)
        self.assertIn("ADR-2", summary)


class ReadinessVerdictsTests(unittest.TestCase):
    def test_three_verdicts(self) -> None:
        self.assertEqual(
            READINESS_VERDICTS,
            frozenset({"READY", "BLOCKED", "NEEDS_RISK"}),
        )


class CheckReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_ready_with_risk(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P2")
        self.assertIsInstance(result["requirements"], dict)
        self.assertIn("coverage_pct", result["requirements"])

    def test_needs_risk_when_no_entries(self) -> None:
        result = check_readiness("E1-001", profile=self.profile)
        self.assertEqual(result["verdict"], "NEEDS_RISK")
        self.assertIn("no risk", result["reason"].lower())

    def test_blocked_by_forbidden_until(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-0083": ["E1-*"]}
        entries = [make_risk_entry("SEC", 2, 2)]
        result = check_readiness(
            "E1-001", profile=profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(len(result["blockers"]), 1)

    def test_blocked_takes_precedence_over_needs_risk(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        result = check_readiness("E1-001", profile=profile)
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_high_risk_sets_p0(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P0")
        self.assertEqual(result["requirements"]["coverage_pct"], 100)

    def test_low_risk_sets_p3(self) -> None:
        entries = [make_risk_entry("OPS", 1, 1)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P3")
        self.assertEqual(result["requirements"]["coverage_pct"], 20)

    def test_risk_summary_included(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 2),
            make_risk_entry("TECH", 1, 1),
        ]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["risk_summary"]["max_score"], 6)
        self.assertEqual(result["risk_summary"]["entry_count"], 2)

    def test_unmitigated_risk_9_flagged(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertTrue(result["risk_summary"]["unmitigated_risk_9"])

    def test_custom_thresholds(self) -> None:
        custom = {7: "P0", 4: "P1", 2: "P2", 1: "P3"}
        entries = [make_risk_entry("TECH", 2, 2)]  # score=4
        result = check_readiness(
            "E1-001", profile=self.profile,
            risk_entries=entries, thresholds=custom,
        )
        self.assertEqual(result["priority"], "P1")


class PersistReadinessResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
        }

    def test_persist_creates_file(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = check_readiness("E1-001", profile=self.profile, risk_entries=entries)
        path = persist_readiness_result(self.tmp, "E1-001", result)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["story_id"], "E1-001")
        self.assertEqual(data["verdict"], "READY")

    def test_persist_path_under_readiness(self) -> None:
        result = check_readiness("E1-001", profile=self.profile)
        path = persist_readiness_result(self.tmp, "E1-001", result)
        self.assertIn("_bmad/gate/readiness", path.as_posix())

    def test_load_returns_persisted(self) -> None:
        entries = [make_risk_entry("SEC", 3, 2)]
        result = check_readiness("E1-001", profile=self.profile, risk_entries=entries)
        persist_readiness_result(self.tmp, "E1-001", result)
        loaded = load_readiness_result(self.tmp, "E1-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["verdict"], "READY")

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(load_readiness_result(self.tmp, "no-such"))


if __name__ == "__main__":
    unittest.main()
