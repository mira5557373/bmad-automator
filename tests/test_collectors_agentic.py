from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class PackSchemaCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        self.assertEqual(PACK_SCHEMA.collector_id, "pack-schema-agentic")
        self.assertEqual(PACK_SCHEMA.tool, "python3")
        self.assertEqual(PACK_SCHEMA.category, "agentic")
        self.assertTrue(PACK_SCHEMA.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("pack_schema_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_tools_dir(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        profile = {"rules": {"agentic": {"tools_dir": "agent_tools"}}}
        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "agent_tools")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class AibomDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        self.assertEqual(AIBOM_DIFF.collector_id, "aibom-diff-agentic")
        self.assertEqual(AIBOM_DIFF.tool, "python3")
        self.assertEqual(AIBOM_DIFF.category, "agentic")
        self.assertTrue(AIBOM_DIFF.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        cmd = AIBOM_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("aibom_check.py", cmd[1])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        cmd = AIBOM_DIFF.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class OpaCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        self.assertEqual(OPA.collector_id, "opa-agentic")
        self.assertEqual(OPA.tool, "python3")
        self.assertEqual(OPA.category, "agentic")
        self.assertTrue(OPA.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        cmd = OPA.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("opa_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_policy_dir(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        profile = {"rules": {"agentic": {"policy_dir": "opa_policies"}}}
        cmd = OPA.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "opa_policies")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        cmd = OPA.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class EvalsCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        self.assertEqual(EVALS.collector_id, "evals-agentic")
        self.assertEqual(EVALS.tool, "deepeval")
        self.assertEqual(EVALS.category, "agentic")
        self.assertFalse(EVALS.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        cmd = EVALS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "deepeval")
        self.assertIn("test", cmd)
        self.assertIn("run", cmd)

    def test_build_cmd_custom_tool(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        profile = {
            "rules": {"agentic": {
                "eval_tool": "promptfoo",
                "eval_cmd": ["npx", "promptfoo", "eval"],
            }},
        }
        cmd = EVALS.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd, ["npx", "promptfoo", "eval"])


class GuardrailCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        self.assertEqual(GUARDRAIL.collector_id, "guardrail-agentic")
        self.assertEqual(GUARDRAIL.tool, "python3")
        self.assertEqual(GUARDRAIL.category, "agentic")
        self.assertTrue(GUARDRAIL.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        cmd = GUARDRAIL.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        files = json.loads(cmd[3])
        self.assertIn("guardrails.yaml", files)

    def test_build_cmd_custom_files(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        profile = {
            "rules": {"agentic": {
                "guardrail_files": ["config/guardrails.json", "config/safety.yaml"],
            }},
        }
        cmd = GUARDRAIL.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["config/guardrails.json", "config/safety.yaml"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        cmd = GUARDRAIL.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class AgenticCollectorListTests(unittest.TestCase):
    def test_five_collectors(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        self.assertEqual(len(COLLECTORS), 5)

    def test_all_agentic_category(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "agentic")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "pack-schema-agentic",
            "aibom-diff-agentic",
            "opa-agentic",
            "evals-agentic",
            "guardrail-agentic",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
