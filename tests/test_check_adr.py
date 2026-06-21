from __future__ import annotations

import os
import shutil
import tempfile
import unittest


class AdrCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.adr_dir = os.path.join(
            self.tmpdir, "docs", "architecture", "decisions",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_adr(self, name: str, content: str) -> None:
        os.makedirs(self.adr_dir, exist_ok=True)
        with open(os.path.join(self.adr_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_all_adrs_have_section(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Production-Readiness\nok\n")
        self._write_adr("ADR-002.md", "# ADR\n## Production Readiness\nok\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_missing_section_returns_one(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Context\nstuff\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_mixed_adrs(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Production-Readiness\nok\n")
        self._write_adr("ADR-002.md", "# ADR\n## Context\nmissing\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_no_adr_dir_returns_zero(self) -> None:
        from story_automator.core.checks.adr_check import main

        self.assertEqual(main([self.tmpdir]), 0)

    def test_empty_adr_dir_returns_zero(self) -> None:
        from story_automator.core.checks.adr_check import main

        os.makedirs(self.adr_dir)
        self.assertEqual(main([self.tmpdir]), 0)

    def test_case_insensitive_heading(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n### production-readiness\nok\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.adr_check import main

        self.assertEqual(main([]), 2)
