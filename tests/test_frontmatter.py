# tests/test_frontmatter.py
"""Coverage for the hand-rolled YAML-subset frontmatter parser."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.frontmatter import (
    extract_frontmatter,
    extract_json_block,
    find_frontmatter_value,
    find_frontmatter_value_case,
    parse_simple_frontmatter,
    read_story_range_from_state,
    split_frontmatter,
    update_simple_frontmatter,
)

_DOC = """---
status: active
epic: "1"
storyRange: ["1.1", "1.2"]
labels:
  - alpha
  - beta
# a comment line
emptyKey:
malformed line without colon
---
# Body Heading

body text
"""


class ExtractSplitTests(unittest.TestCase):
    def test_extract_frontmatter_returns_block(self) -> None:
        self.assertIn("status: active", extract_frontmatter(_DOC))

    def test_extract_frontmatter_without_leading_marker(self) -> None:
        self.assertEqual(extract_frontmatter("no frontmatter here"), "")

    def test_extract_frontmatter_unterminated(self) -> None:
        self.assertEqual(extract_frontmatter("---\nstatus: active\n"), "")

    def test_split_frontmatter_returns_front_and_body(self) -> None:
        front, body = split_frontmatter(_DOC)
        self.assertIn("status: active", front)
        self.assertIn("Body Heading", body)

    def test_split_frontmatter_without_marker_returns_whole_body(self) -> None:
        front, body = split_frontmatter("plain text")
        self.assertEqual(front, "")
        self.assertEqual(body, "plain text")


class ParseSimpleFrontmatterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fields = parse_simple_frontmatter(_DOC)

    def test_scalar_value(self) -> None:
        self.assertEqual(self.fields["status"], "active")
        self.assertEqual(self.fields["epic"], "1")  # quotes stripped

    def test_inline_list_literal(self) -> None:
        self.assertEqual(self.fields["storyRange"], ["1.1", "1.2"])

    def test_multiline_list(self) -> None:
        self.assertEqual(self.fields["labels"], ["alpha", "beta"])

    def test_empty_value_key_becomes_empty_list(self) -> None:
        self.assertEqual(self.fields["emptyKey"], [])

    def test_comment_and_malformed_lines_skipped(self) -> None:
        self.assertNotIn("# a comment line", self.fields)
        self.assertNotIn("malformed line without colon", self.fields)

    def test_no_frontmatter_returns_empty(self) -> None:
        self.assertEqual(parse_simple_frontmatter("no fm"), {})


class FindValueTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Path(tmp.name)

    def test_find_scalar_value(self) -> None:
        path = self._write(_DOC)
        self.assertEqual(find_frontmatter_value(path, "status"), "active")

    def test_find_list_value_returns_empty_string(self) -> None:
        path = self._write(_DOC)
        self.assertEqual(find_frontmatter_value(path, "labels"), "")

    def test_find_value_case_insensitive(self) -> None:
        path = self._write("---\nStatusField: Ready\n---\n")
        self.assertEqual(find_frontmatter_value_case(path, "statusfield"), "Ready")


class StoryRangeTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Path(tmp.name)

    def test_inline_story_range(self) -> None:
        path = self._write('---\nstoryRange: ["1.1", "1.2"]\n---\n')
        self.assertEqual(read_story_range_from_state(path), ["1.1", "1.2"])

    def test_multiline_story_range(self) -> None:
        path = self._write("---\nstoryRange:\n  - 2.1\n  - 2.2\nstatus: x\n---\n")
        self.assertEqual(read_story_range_from_state(path), ["2.1", "2.2"])

    def test_missing_story_range(self) -> None:
        path = self._write("---\nstatus: active\n---\n")
        self.assertEqual(read_story_range_from_state(path), [])


class UpdateFrontmatterTests(unittest.TestCase):
    def test_update_existing_key_persists_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.md"
            path.write_text("status: active\nepic: 1\n", encoding="utf-8")
            updated = update_simple_frontmatter(path, {"status": "done"})
            self.assertEqual(updated, ["status"])
            self.assertIn("status: done", path.read_text(encoding="utf-8"))

    def test_update_absent_key_reports_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.md"
            path.write_text("status: active\n", encoding="utf-8")
            self.assertEqual(update_simple_frontmatter(path, {"missing": "x"}), [])


class JsonBlockTests(unittest.TestCase):
    def test_fenced_json_block(self) -> None:
        self.assertEqual(extract_json_block('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_bare_json_object(self) -> None:
        self.assertEqual(extract_json_block('{"a": 1}'), '{"a": 1}')

    def test_no_json_block(self) -> None:
        self.assertEqual(extract_json_block("no json here"), "")


if __name__ == "__main__":
    unittest.main()
