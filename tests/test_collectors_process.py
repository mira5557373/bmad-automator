from __future__ import annotations

import sys
import unittest
from pathlib import Path


class AdrCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.process import ADR

        self.assertEqual(ADR.collector_id, "adr-process")
        self.assertEqual(ADR.tool, "python3")
        self.assertEqual(ADR.category, "process")
        self.assertIn("*.md", ADR.file_patterns)

    def test_build_cmd_invokes_adr_script(self) -> None:
        from story_automator.core.collectors.process import ADR

        cmd = ADR.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("adr_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file())
        self.assertEqual(cmd[2], "/tmp/checkout")


class ProcessCollectorListTests(unittest.TestCase):
    def test_adr_present(self) -> None:
        from story_automator.core.collectors.process import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("adr-process", ids)

    def test_all_process_category(self) -> None:
        from story_automator.core.collectors.process import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "process")
