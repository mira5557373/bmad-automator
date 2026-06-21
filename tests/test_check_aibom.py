from __future__ import annotations

import json
import os
import tempfile
import unittest


class AibomUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.aibom_check import main

        self.assertEqual(main([]), 2)


class LoadAibomTests(unittest.TestCase):
    def test_loads_valid_aibom(self) -> None:
        from story_automator.core.checks.aibom_check import load_aibom

        aibom = {
            "components": [
                {"name": "search_tool", "type": "machine-learning-model"},
                {"name": "classify_tool", "type": "machine-learning-model"},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(aibom, f)
            path = f.name
        try:
            data = load_aibom(path)
            self.assertEqual(len(data.get("components", [])), 2)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.aibom_check import load_aibom

        data = load_aibom("/nonexistent/path.json")
        self.assertEqual(data, {})


class FindToolNamesTests(unittest.TestCase):
    def test_finds_tool_json_files(self) -> None:
        from story_automator.core.checks.aibom_check import find_tool_names

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            with open(os.path.join(tools_dir, "search.tool.json"), "w") as f:
                json.dump({"name": "search_tool"}, f)
            names = find_tool_names(checkout)
            self.assertIn("search_tool", names)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_tools_returns_empty(self) -> None:
        from story_automator.core.checks.aibom_check import find_tool_names

        checkout = tempfile.mkdtemp()
        try:
            names = find_tool_names(checkout)
            self.assertEqual(names, set())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class CheckAibomCoverageTests(unittest.TestCase):
    def test_all_covered_passes(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        tools = {"search_tool", "classify_tool"}
        aibom = {
            "components": [
                {"name": "search_tool"},
                {"name": "classify_tool"},
            ],
        }
        issues = check_aibom_coverage(tools, aibom)
        self.assertEqual(issues, [])

    def test_missing_tool_fails(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        tools = {"search_tool", "classify_tool"}
        aibom = {"components": [{"name": "search_tool"}]}
        issues = check_aibom_coverage(tools, aibom)
        self.assertEqual(len(issues), 1)
        self.assertIn("classify_tool", issues[0])

    def test_empty_tools_passes(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        issues = check_aibom_coverage(set(), {})
        self.assertEqual(issues, [])

    def test_empty_aibom_with_tools_fails(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        issues = check_aibom_coverage({"tool_a"}, {})
        self.assertEqual(len(issues), 1)
