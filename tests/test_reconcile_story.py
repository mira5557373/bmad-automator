from __future__ import annotations

import io
import json
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.basic import cmd_reconcile_story


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class ReconcileStoryTests(unittest.TestCase):
    """reconcile-story rewrites the story File List from git ground truth so
    doc-drift cannot survive the dev step (the recurring AI-1/AI-2.1/AI-3.1
    finding). The File List is computed, never transcribed by an LLM."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.artifacts = self.repo / "_bmad-output" / "implementation-artifacts"
        self.artifacts.mkdir(parents=True)
        _git(self.repo, "init")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "Test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_story(self, body: str) -> Path:
        story = self.artifacts / "1-2-example.md"
        story.write_text(body, encoding="utf-8")
        return story

    def _run(self, *extra: str) -> dict:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_reconcile_story(["--repo", str(self.repo), "--story", "1-2", *extra])
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())

    def test_drift_detected_without_write(self) -> None:
        # Story claims one stale file; git actually has two different ones.
        self._write_story(
            textwrap.dedent(
                """\
                # Story 1.2

                ### File List

                - src/old.py
                """
            )
        )
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        (self.repo / "src" / "b.py").write_text("b\n", encoding="utf-8")

        payload = self._run()
        self.assertFalse(payload["wrote"])
        self.assertFalse(payload["in_sync"])
        self.assertEqual(payload["git_files"], ["src/a.py", "src/b.py"])
        self.assertEqual(payload["missing_from_story"], ["src/a.py", "src/b.py"])
        self.assertEqual(payload["stale_in_story"], ["src/old.py"])

    def test_write_makes_file_list_match_git(self) -> None:
        story = self._write_story(
            textwrap.dedent(
                """\
                # Story 1.2

                ### File List

                - src/old.py

                ### Change Log

                - did stuff
                """
            )
        )
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        (self.repo / "src" / "b.py").write_text("b\n", encoding="utf-8")

        payload = self._run("--write")
        self.assertTrue(payload["wrote"])

        text = story.read_text(encoding="utf-8")
        self.assertIn("- src/a.py", text)
        self.assertIn("- src/b.py", text)
        self.assertNotIn("- src/old.py", text)
        # Other sections must be left untouched.
        self.assertIn("### Change Log", text)
        self.assertIn("- did stuff", text)

        # Second pass is a no-op: the section now matches git exactly.
        after = self._run("--write")
        self.assertTrue(after["in_sync"])
        self.assertFalse(after["wrote"])

    def test_tooling_paths_excluded(self) -> None:
        self._write_story("# Story 1.2\n\n### File List\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        # _bmad-output already exists (the story itself lives there) and must
        # never leak into the application File List.
        payload = self._run("--write")
        self.assertEqual(payload["git_files"], ["src/a.py"])
        self.assertTrue(all(not f.startswith("_bmad-output/") for f in payload["git_files"]))

    def test_missing_section_is_appended(self) -> None:
        story = self._write_story("# Story 1.2\n\nNo file list section here.\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        payload = self._run("--write")
        self.assertTrue(payload["wrote"])
        text = story.read_text(encoding="utf-8")
        self.assertIn("### File List", text)
        self.assertIn("- src/a.py", text)

    def test_configured_artifacts_dir_excluded(self) -> None:
        # When artifacts live under docs/bmad/... (not _bmad-output/), the story file
        # and its siblings must still be excluded from the reconciled File List.
        bmm = self.repo / "_bmad" / "bmm"
        bmm.mkdir(parents=True)
        (bmm / "config.yaml").write_text(
            "implementation_artifacts: docs/bmad/implementation-artifacts\n", encoding="utf-8"
        )
        art = self.repo / "docs" / "bmad" / "implementation-artifacts"
        art.mkdir(parents=True)
        (art / "1-2-example.md").write_text("# Story 1.2\n\n### File List\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")

        payload = self._run("--write")
        self.assertEqual(payload["git_files"], ["src/a.py"])
        self.assertTrue(payload["story_file"].endswith("docs/bmad/implementation-artifacts/1-2-example.md"))

    def test_non_ascii_path_captured_verbatim(self) -> None:
        self._write_story("# Story 1.2\n\n### File List\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "café.py").write_text("x\n", encoding="utf-8")
        payload = self._run("--write")
        self.assertIn("src/café.py", payload["git_files"])

    def test_filename_with_parens_not_mangled(self) -> None:
        self._write_story("# Story 1.2\n\n### File List\n\n- src/foo(bar).py\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "foo(bar).py").write_text("x\n", encoding="utf-8")
        payload = self._run()
        self.assertEqual(payload["git_files"], ["src/foo(bar).py"])
        self.assertEqual(payload["stale_in_story"], [])
        self.assertEqual(payload["missing_from_story"], [])
        self.assertTrue(payload["in_sync"])

    def test_disambiguates_by_resolved_key(self) -> None:
        for name in ("1-2-foo.md", "1-2-bar.md"):
            (self.artifacts / name).write_text("# s\n\n### File List\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_reconcile_story(["--repo", str(self.repo), "--story", "1-2-foo", "--write"])
        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["story_file"].endswith("1-2-foo.md"))

    def test_file_list_last_section_idempotent(self) -> None:
        story = self._write_story("# Story 1.2\n\n### File List\n\n- src/old.py\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("a\n", encoding="utf-8")
        self.assertTrue(self._run("--write")["wrote"])
        text = story.read_text(encoding="utf-8")
        self.assertFalse(text.endswith("\n\n"))  # no extra trailing blank when File List is last
        second = self._run("--write")
        self.assertFalse(second["wrote"])  # already in sync, no churn
        self.assertEqual(story.read_text(encoding="utf-8"), text)

    def test_rename_keeps_destination_path(self) -> None:
        (self.repo / "src").mkdir()
        (self.repo / "src" / "old.py").write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "seed")
        _git(self.repo, "mv", "src/old.py", "src/new.py")
        self._write_story("# Story 1.2\n\n### File List\n")
        payload = self._run("--write")
        self.assertIn("src/new.py", payload["git_files"])
        self.assertNotIn("src/old.py", payload["git_files"])


if __name__ == "__main__":
    unittest.main()
