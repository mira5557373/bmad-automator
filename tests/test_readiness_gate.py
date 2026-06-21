from __future__ import annotations

import unittest

from story_automator.core.readiness_gate import (
    format_blocker_summary,
    resolve_story_blockers,
)


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


if __name__ == "__main__":
    unittest.main()
