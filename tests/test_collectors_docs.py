from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class DocPresenceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        self.assertEqual(DOC_PRESENCE.collector_id, "doc-presence-docs")
        self.assertEqual(DOC_PRESENCE.tool, "python3")
        self.assertEqual(DOC_PRESENCE.category, "docs")
        self.assertTrue(DOC_PRESENCE.deterministic)
        self.assertIn("*.md", DOC_PRESENCE.file_patterns)

    def test_build_cmd_invokes_presence_script(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        cmd = DOC_PRESENCE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file(), f"script not found: {cmd[1]}")
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIn("docs/operations/gate-troubleshooting.md", files)

    def test_build_cmd_returns_list_of_strings(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        cmd = DOC_PRESENCE.build_cmd("/tmp/co", {"rules": {}})
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(s, str) for s in cmd))


class DocusaurusCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        self.assertEqual(DOCUSAURUS.collector_id, "docusaurus-docs")
        self.assertEqual(DOCUSAURUS.tool, "docusaurus")
        self.assertEqual(DOCUSAURUS.category, "docs")
        self.assertIsNotNone(DOCUSAURUS.tool_version_cmd)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        cmd = DOCUSAURUS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "docusaurus", "build"])

    def test_file_patterns_include_markdown(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        self.assertTrue(
            DOCUSAURUS.file_patterns & {"*.md", "*.mdx"},
            "should match markdown files",
        )


class DocsCollectorListTests(unittest.TestCase):
    def test_collectors_count(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_docs_category(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "docs")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
