from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.deferred_work import (
    DEFERRED_WORK_PATH_RELATIVE,
    VALID_SEVERITIES,
    append_entry,
    list_entries,
)


class DeferredWorkConstantsTests(unittest.TestCase):
    def test_relative_path_constant(self) -> None:
        self.assertEqual(DEFERRED_WORK_PATH_RELATIVE, "_bmad/bmm/deferred-work.md")

    def test_valid_severities(self) -> None:
        self.assertEqual(VALID_SEVERITIES, frozenset({"CRITICAL", "PREFERENCE"}))


class DeferredWorkAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_entry_creates_file_and_returns_path(self) -> None:
        path = append_entry(
            self.project_root,
            title="Wire up gate readiness",
            reason="blocked on upstream profile drift",
            owner_story="story-1.2.3",
        )
        self.assertEqual(path, self.project_root / DEFERRED_WORK_PATH_RELATIVE)
        self.assertTrue(path.exists())
        contents = path.read_text(encoding="utf-8")
        self.assertIn("Wire up gate readiness", contents)
        self.assertIn("blocked on upstream profile drift", contents)
        self.assertIn("story-1.2.3", contents)
        # Default severity is PREFERENCE
        self.assertIn("PREFERENCE", contents)

    def test_append_entry_default_severity_is_preference(self) -> None:
        append_entry(
            self.project_root,
            title="t",
            reason="r",
            owner_story="s",
        )
        entries = list_entries(self.project_root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["severity"], "PREFERENCE")

    def test_append_entry_rejects_unknown_severity(self) -> None:
        with self.assertRaises(ValueError):
            append_entry(
                self.project_root,
                title="t",
                reason="r",
                owner_story="s",
                severity="WHATEVER",
            )

    def test_append_entry_appends_without_clobbering(self) -> None:
        append_entry(
            self.project_root,
            title="first",
            reason="r1",
            owner_story="s1",
            severity="CRITICAL",
        )
        append_entry(
            self.project_root,
            title="second",
            reason="r2",
            owner_story="s2",
            severity="PREFERENCE",
        )
        entries = list_entries(self.project_root)
        self.assertEqual(len(entries), 2)
        titles = [e["title"] for e in entries]
        self.assertEqual(titles, ["first", "second"])
        self.assertEqual(entries[0]["severity"], "CRITICAL")
        self.assertEqual(entries[1]["severity"], "PREFERENCE")

    def test_list_entries_returns_empty_when_no_file(self) -> None:
        entries = list_entries(self.project_root)
        self.assertEqual(entries, [])

    def test_list_entries_round_trip_fields(self) -> None:
        append_entry(
            self.project_root,
            title="Tighten profile validation",
            reason="evidence drift discovered late",
            owner_story="story-7.7.7",
            severity="CRITICAL",
        )
        entries = list_entries(self.project_root)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["title"], "Tighten profile validation")
        self.assertEqual(e["reason"], "evidence drift discovered late")
        self.assertEqual(e["owner_story"], "story-7.7.7")
        self.assertEqual(e["severity"], "CRITICAL")

    def test_append_entry_uses_utf8(self) -> None:
        append_entry(
            self.project_root,
            title="日本語タイトル",
            reason="reason",
            owner_story="story-0",
        )
        path = self.project_root / DEFERRED_WORK_PATH_RELATIVE
        contents = path.read_text(encoding="utf-8")
        self.assertIn("日本語タイトル", contents)

    def test_append_entry_creates_parent_directory(self) -> None:
        # Ensure the _bmad/bmm directory is created automatically.
        self.assertFalse((self.project_root / "_bmad" / "bmm").exists())
        append_entry(
            self.project_root,
            title="t",
            reason="r",
            owner_story="s",
        )
        self.assertTrue((self.project_root / "_bmad" / "bmm").is_dir())


if __name__ == "__main__":
    unittest.main()
