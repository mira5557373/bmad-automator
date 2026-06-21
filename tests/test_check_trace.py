from __future__ import annotations

import os
import shutil
import tempfile
import unittest


class TraceCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.story_dir = os.path.join(self.tmpdir, "_bmad", "stories")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_story(self, name: str, content: str) -> None:
        os.makedirs(self.story_dir, exist_ok=True)
        with open(os.path.join(self.story_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_all_stories_have_file_list(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n- a.py\n")
        self._write_story("S002.md", "# Story\n## File List\n- b.py\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_missing_file_list_returns_one(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## Tasks\n- task\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_mixed_stories(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n- a.py\n")
        self._write_story("S002.md", "# Story\n## Tasks\n- task\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_no_story_dir_returns_zero(self) -> None:
        from story_automator.core.checks.trace_check import main

        self.assertEqual(main([self.tmpdir]), 0)

    def test_empty_story_dir_returns_zero(self) -> None:
        from story_automator.core.checks.trace_check import main

        os.makedirs(self.story_dir)
        self.assertEqual(main([self.tmpdir]), 0)

    def test_case_insensitive_heading(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n### file list\n- a.py\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.trace_check import main

        self.assertEqual(main([]), 2)

    def test_empty_file_list_returns_one(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n\n## Tasks\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_non_md_files_ignored(self) -> None:
        from story_automator.core.checks.trace_check import main

        os.makedirs(self.story_dir, exist_ok=True)
        with open(os.path.join(self.story_dir, "notes.txt"), "w") as f:
            f.write("no file list here")
        self.assertEqual(main([self.tmpdir]), 0)
