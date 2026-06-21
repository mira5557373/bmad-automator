from __future__ import annotations

import json
import os
import tempfile
import unittest


class PackSchemaUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.pack_schema_check import main

        self.assertEqual(main([]), 2)


class ValidatePackSchemaTests(unittest.TestCase):
    def test_valid_tool_passes(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "search_tool",
            "risk_tier": "low",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(issues, [])

    def test_missing_risk_tier_fails(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "search_tool",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 1)
        self.assertIn("risk_tier", issues[0])

    def test_missing_multiple_fields_reports_all(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {"name": "tool"}
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 4)

    def test_empty_field_fails(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "tool",
            "risk_tier": "",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 1)
        self.assertIn("risk_tier", issues[0])


class FindToolDefinitionsTests(unittest.TestCase):
    def test_finds_json_tool_files(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            tool = {
                "name": "search",
                "risk_tier": "low",
                "reversibility_class": "reversible",
                "time_lock": "none",
                "autonomy": "supervised",
            }
            with open(os.path.join(tools_dir, "search.tool.json"), "w") as f:
                json.dump(tool, f)
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(len(defs), 1)
            self.assertEqual(defs[0]["name"], "search")
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_tools_dir_returns_empty(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(defs, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_invalid_json_skipped(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            with open(os.path.join(tools_dir, "bad.tool.json"), "w") as f:
                f.write("not json")
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(defs, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
