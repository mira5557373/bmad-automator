from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.epic_parser import epic_complete, parse_epic_file, parse_story


class EpicParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.epic_file = self.project_root / "epic-multi-leg.md"
        self.rules_file = self.project_root / "rules.json"
        self.rules_file.write_text('{"rules": [], "structural_rules": {}, "thresholds": {"low_max": 0, "medium_max": 5}}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_epic_file_accepts_non_numeric_story_ids(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg.3: Quantity precision
### Story multi-leg.4: Next step
""",
            encoding="utf-8",
        )
        payload = parse_epic_file(self.epic_file)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual([story["storyId"] for story in payload["stories"]], ["multi-leg.3", "multi-leg.4"])
        self.assertEqual(payload["stories"][0]["epicNum"], "multi-leg")
        self.assertEqual(payload["stories"][0]["storyNum"], "3")

    def test_parse_story_accepts_non_numeric_story_id(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg.3: Quantity precision
Acceptance Criteria
- Works
""",
            encoding="utf-8",
        )
        payload = parse_story(self.epic_file, "multi-leg.3", self.rules_file)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["storyId"], "multi-leg.3")
        self.assertEqual(payload["title"], "Quantity precision")

    def test_parse_epic_file_accepts_full_key_story_headers(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg-3-old: Old
""",
            encoding="utf-8",
        )
        payload = parse_epic_file(self.epic_file)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["stories"][0]["storyId"], "multi-leg.3")

    def test_parse_story_accepts_canonical_id_for_full_key_header(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg-3-old: Old
Acceptance Criteria
- Works
""",
            encoding="utf-8",
        )
        payload = parse_story(self.epic_file, "multi-leg.3", self.rules_file)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["storyId"], "multi-leg.3")
        self.assertEqual(payload["title"], "Old")

    def test_epic_complete_accepts_non_numeric_story_ids(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg.3: Quantity precision
### Story multi-leg.4: Next step
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "multi-leg.3,multi-leg.4")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "multi-leg.4")

    def test_epic_complete_accepts_non_numeric_full_story_keys(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg.3: Quantity precision
### Story multi-leg.4: Next step
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "multi-leg-3-quantity-precision,multi-leg-4-next-step")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "multi-leg.4")

    def test_epic_complete_rejects_missing_explicit_full_key_sibling(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg-3-old: Old
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "multi-leg-3-new")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "multi-leg.3")

    def test_epic_complete_accepts_exact_full_key_header(self) -> None:
        self.epic_file.write_text(
            """# Epic Multi Leg
## Epic multi-leg: Multi Leg
### Story multi-leg-3-old: Old
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "multi-leg-3-old")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "multi-leg.3")

    def test_epic_complete_sorts_story_numbers_numerically(self) -> None:
        # Within one epic, story 1.10 must sort after 1.9 numerically (not
        # lexically, where "1.10" < "1.9").
        self.epic_file.write_text(
            """# Epic Numeric
## Epic 1: Numeric
### Story 1.9: Old
### Story 1.10: New
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "1.9")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "1.10")
        complete = epic_complete(self.epic_file, "1.9,1.10")
        self.assertTrue(complete["epicComplete"])

    def test_epic_complete_scopes_to_requested_epic(self) -> None:
        # R09: a later epic's higher story id must not mask completion of the
        # epic the range covers, in a multi-epic file.
        self.epic_file.write_text(
            """# Epics
## Epic 1: First
### Story 1.1: A
### Story 1.2: B
## Epic 2: Second
### Story 2.1: C
""",
            encoding="utf-8",
        )
        payload = epic_complete(self.epic_file, "1.1,1.2")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["epicComplete"])
        self.assertEqual(payload["maxEpicStory"], "1.2")
        # And epic 2 is judged on its own stories, not epic 1's.
        second = epic_complete(self.epic_file, "2.1")
        self.assertTrue(second["epicComplete"])
        self.assertEqual(second["maxEpicStory"], "2.1")


if __name__ == "__main__":
    unittest.main()
