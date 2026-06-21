from __future__ import annotations

import unittest

from story_automator.core.collectors.mutation import (
    MUTMUT,
    COLLECTORS,
)


class TestMutmutCollector(unittest.TestCase):
    def test_category_is_mutation(self):
        self.assertEqual(MUTMUT.category, "mutation")

    def test_collector_id(self):
        self.assertEqual(MUTMUT.collector_id, "mutmut-mutation")

    def test_tool(self):
        self.assertEqual(MUTMUT.tool, "python3")

    def test_build_cmd_includes_threshold(self):
        profile = {"rules": {"mutation": {"min_score": 60}}}
        cmd = MUTMUT.build_cmd("/checkout", profile)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertIn("mutmut", cmd)
        self.assertIn("60", cmd)

    def test_build_cmd_default_threshold(self):
        profile = {"rules": {}}
        cmd = MUTMUT.build_cmd("/checkout", profile)
        self.assertIn("60", cmd)


class TestCollectorsList(unittest.TestCase):
    def test_all_present(self):
        self.assertEqual(len(COLLECTORS), 1)
        self.assertEqual(COLLECTORS[0].collector_id, "mutmut-mutation")

    def test_all_category_mutation(self):
        for c in COLLECTORS:
            self.assertEqual(c.category, "mutation")

    def test_file_patterns(self):
        self.assertIn("*.py", MUTMUT.file_patterns)


if __name__ == "__main__":
    unittest.main()
