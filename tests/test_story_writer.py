from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.story_writer import (
    VALID_INITIAL_STATUSES,
    seed_status_sentinel,
    write_story_header,
    write_story_skeleton,
)


class WriteStoryHeaderTests(unittest.TestCase):
    def test_writes_h1_as_first_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            result = write_story_header(path, epic=1, story=2, title="My Title")
            self.assertEqual(result, path)
            content = path.read_text(encoding="utf-8")
            first_line = content.splitlines()[0]
            self.assertEqual(first_line, "# Story 1.2: My Title")

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "story.md"
            write_story_header(path, epic=3, story=14, title="Deep")
            self.assertTrue(path.exists())
            self.assertIn("# Story 3.14: Deep", path.read_text(encoding="utf-8"))


class SeedStatusSentinelTests(unittest.TestCase):
    def test_appends_default_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            path.write_text("# Story 1.1: Hello\n", encoding="utf-8")
            seed_status_sentinel(path)
            content = path.read_text(encoding="utf-8")
            self.assertIn("Status: ready-for-dev", content)

    def test_idempotent_reseed_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            path.write_text("# Story 1.1: Hello\n", encoding="utf-8")
            seed_status_sentinel(path)
            seed_status_sentinel(path)
            seed_status_sentinel(path)
            content = path.read_text(encoding="utf-8")
            occurrences = sum(
                1
                for line in content.splitlines()
                if line.strip().startswith("Status:")
            )
            self.assertEqual(occurrences, 1)

    def test_invalid_status_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            path.write_text("# Story 1.1: Hello\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                seed_status_sentinel(path, status="done")
            with self.assertRaises(ValueError):
                seed_status_sentinel(path, status="ready_for_dev")

    def test_accepts_backlog_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            path.write_text("# Story 1.1: Hello\n", encoding="utf-8")
            seed_status_sentinel(path, status="backlog")
            self.assertIn("Status: backlog", path.read_text(encoding="utf-8"))


class WriteStorySkeletonTests(unittest.TestCase):
    def test_combines_header_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            result = write_story_skeleton(
                path, epic=2, story=5, title="Feature X"
            )
            self.assertEqual(result, path)
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# Story 2.5: Feature X"))
            self.assertIn("Status: ready-for-dev", content)

    def test_skeleton_uses_atomic_write(self) -> None:
        # If write is atomic, no .tmp file should be left behind in parent dir.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            write_story_skeleton(path, epic=1, story=1, title="Atom")
            leftover = [
                p
                for p in Path(tmp).iterdir()
                if p.name.endswith(".tmp") or ".tmp" in p.name
            ]
            self.assertEqual(leftover, [])

    def test_skeleton_round_trips_through_simple_parse(self) -> None:
        # Integration: produced file should be parseable as a story header line.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "story.md"
            write_story_skeleton(path, epic=7, story=11, title="Compat Title")
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            # H1 is first line.
            self.assertTrue(lines[0].startswith("# Story 7.11:"))
            # Status sentinel exists somewhere after the header.
            status_lines = [ln for ln in lines if ln.strip().startswith("Status:")]
            self.assertEqual(len(status_lines), 1)


class ValidStatusesTests(unittest.TestCase):
    def test_valid_initial_statuses_are_frozen(self) -> None:
        self.assertIsInstance(VALID_INITIAL_STATUSES, frozenset)
        self.assertIn("backlog", VALID_INITIAL_STATUSES)
        self.assertIn("ready-for-dev", VALID_INITIAL_STATUSES)


if __name__ == "__main__":
    unittest.main()
