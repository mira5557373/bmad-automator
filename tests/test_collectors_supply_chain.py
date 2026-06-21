from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class SbomCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        self.assertEqual(SBOM.collector_id, "sbom-supply_chain")
        self.assertEqual(SBOM.tool, "python3")
        self.assertEqual(SBOM.category, "supply_chain")
        self.assertTrue(SBOM.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        cmd = SBOM.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("sbom_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_format(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        profile = {"rules": {"supply_chain": {"sbom_format": "cyclonedx-json"}}}
        cmd = SBOM.build_cmd("/tmp/checkout", profile)
        self.assertIn("cyclonedx-json", cmd)

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        cmd = SBOM.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class CosignCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        self.assertEqual(COSIGN.collector_id, "cosign-supply_chain")
        self.assertEqual(COSIGN.tool, "cosign")
        self.assertEqual(COSIGN.category, "supply_chain")
        self.assertTrue(COSIGN.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        cmd = COSIGN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "cosign")
        self.assertIn("verify-blob", cmd)

    def test_build_cmd_custom_bundle(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        profile = {"rules": {"supply_chain": {"cosign_bundle": "my.bundle"}}}
        cmd = COSIGN.build_cmd("/tmp/checkout", profile)
        self.assertIn("my.bundle", cmd)

    def test_build_cmd_custom_artifact(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        profile = {"rules": {"supply_chain": {"cosign_artifact": "my-sbom.spdx.json"}}}
        cmd = COSIGN.build_cmd("/tmp/checkout", profile)
        self.assertIn("my-sbom.spdx.json", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        self.assertIsNotNone(COSIGN.tool_version_cmd)
        self.assertIn("cosign", COSIGN.tool_version_cmd)


class ProvenanceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        self.assertEqual(PROVENANCE.collector_id, "provenance-supply_chain")
        self.assertEqual(PROVENANCE.tool, "python3")
        self.assertEqual(PROVENANCE.category, "supply_chain")
        self.assertTrue(PROVENANCE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        cmd = PROVENANCE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIsInstance(files, list)
        self.assertTrue(len(files) > 0)

    def test_build_cmd_custom_files(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        profile = {"rules": {"supply_chain": {"provenance_files": ["custom.jsonl"]}}}
        cmd = PROVENANCE.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["custom.jsonl"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        cmd = PROVENANCE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TrivySbomCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        self.assertEqual(TRIVY_SBOM.collector_id, "trivy-sbom-supply_chain")
        self.assertEqual(TRIVY_SBOM.tool, "trivy")
        self.assertEqual(TRIVY_SBOM.category, "supply_chain")
        self.assertTrue(TRIVY_SBOM.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        cmd = TRIVY_SBOM.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "trivy")
        self.assertIn("sbom", cmd)
        self.assertIn("--exit-code", cmd)
        self.assertIn("1", cmd)

    def test_build_cmd_custom_severity(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        profile = {"rules": {"supply_chain": {"trivy_severity": "CRITICAL"}}}
        cmd = TRIVY_SBOM.build_cmd("/tmp/checkout", profile)
        self.assertIn("CRITICAL", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        self.assertIsNotNone(TRIVY_SBOM.tool_version_cmd)
        self.assertIn("trivy", TRIVY_SBOM.tool_version_cmd)


class SupplyChainCollectorListTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "sbom-supply_chain", "cosign-supply_chain",
            "provenance-supply_chain", "trivy-sbom-supply_chain",
        })

    def test_all_supply_chain_category(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "supply_chain")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
