"""Tests for M46 risk-to-story-dar — write risk priorities to Dev Agent Record."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.integration.risk_to_story import (
    RiskToStoryError,
    build_dar_block,
    priorities_from_risk_profile,
    write_priorities_to_dar,
)


class PrioritiesFromRiskProfileTests(unittest.TestCase):
    def test_aggregates_priorities_by_category(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "TECH", "probability": 2, "impact": 3, "score": 6},
            {"category": "PERF", "probability": 1, "impact": 3, "score": 3},
            {"category": "DATA", "probability": 1, "impact": 1, "score": 1},
        ]
        result = priorities_from_risk_profile(entries)
        self.assertEqual(result["SEC"], "P0")
        self.assertEqual(result["TECH"], "P1")
        self.assertEqual(result["PERF"], "P2")
        self.assertEqual(result["DATA"], "P3")

    def test_invalid_profile_raises(self) -> None:
        with self.assertRaises(RiskToStoryError):
            priorities_from_risk_profile([])


class BuildDarBlockTests(unittest.TestCase):
    def test_block_lists_each_priority_sorted(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "TECH", "probability": 2, "impact": 3, "score": 6},
        ]
        block = build_dar_block(entries, target_id="story-1.1")
        # Should contain target id and per-category priority lines.
        self.assertIn("story-1.1", block)
        self.assertIn("- SEC: P0", block)
        self.assertIn("- TECH: P1", block)
        # Should include overall worst-case priority.
        self.assertIn("worst", block.lower())

    def test_block_idempotent_marker(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
        ]
        block = build_dar_block(entries, target_id="story-1.1")
        # Must include a sentinel that allows replacement on re-run.
        self.assertIn("<!-- risk-priorities", block)
        self.assertIn("<!-- /risk-priorities -->", block)


class WritePrioritiesToDarTests(unittest.TestCase):
    def _story_with_dar(self, tmp: Path) -> Path:
        story = tmp / "story-1.1.md"
        story.write_text(
            "# Story 1.1\n\n## Status\n\nDraft\n\n## Tasks\n\n- [ ] task A\n\n"
            "## Dev Agent Record\n\nExisting devagent notes.\n\n"
            "## File List\n\nfoo.py\n",
            encoding="utf-8",
        )
        return story

    def test_appends_block_inside_dev_agent_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            story = self._story_with_dar(tmp)
            entries = [
                {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
                {"category": "TECH", "probability": 1, "impact": 1, "score": 1},
            ]
            write_priorities_to_dar(story, entries, target_id="story-1.1")
            content = story.read_text(encoding="utf-8")
            # DAR section must still exist.
            self.assertIn("## Dev Agent Record", content)
            # Risk lines must be within DAR (not after File List).
            dar_idx = content.index("## Dev Agent Record")
            file_idx = content.index("## File List")
            block_idx = content.index("<!-- risk-priorities")
            self.assertGreater(block_idx, dar_idx)
            self.assertLess(block_idx, file_idx)
            # Existing devagent notes preserved.
            self.assertIn("Existing devagent notes.", content)

    def test_idempotent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            story = self._story_with_dar(tmp)
            entries1 = [
                {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            ]
            entries2 = [
                {"category": "TECH", "probability": 1, "impact": 1, "score": 1},
            ]
            write_priorities_to_dar(story, entries1, target_id="story-1.1")
            write_priorities_to_dar(story, entries2, target_id="story-1.1")
            content = story.read_text(encoding="utf-8")
            # Only one block remains (idempotent).
            self.assertEqual(content.count("<!-- risk-priorities"), 1)
            self.assertEqual(content.count("<!-- /risk-priorities -->"), 1)
            # Second-write entries are present; first-write entries gone.
            self.assertIn("- TECH: P3", content)
            self.assertNotIn("- SEC: P0", content)

    def test_creates_dar_section_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            story = tmp / "story-1.2.md"
            story.write_text(
                "# Story 1.2\n\n## Status\n\nDraft\n\n## File List\n\nbar.py\n",
                encoding="utf-8",
            )
            entries = [
                {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            ]
            write_priorities_to_dar(story, entries, target_id="story-1.2")
            content = story.read_text(encoding="utf-8")
            self.assertIn("## Dev Agent Record", content)
            self.assertIn("<!-- risk-priorities", content)
            # New DAR section appears before File List per BMAD canonical order.
            dar_idx = content.index("## Dev Agent Record")
            file_idx = content.index("## File List")
            self.assertLess(dar_idx, file_idx)

    def test_missing_story_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            missing = tmp / "nope.md"
            entries = [
                {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            ]
            with self.assertRaises(RiskToStoryError):
                write_priorities_to_dar(missing, entries, target_id="x")

    def test_empty_entries_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            story = self._story_with_dar(tmp)
            with self.assertRaises(RiskToStoryError):
                write_priorities_to_dar(story, [], target_id="story-1.1")


if __name__ == "__main__":
    unittest.main()
