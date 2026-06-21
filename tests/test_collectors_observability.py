from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class OtelWiringCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        self.assertEqual(OTEL_WIRING.collector_id, "otel-wiring-observability")
        self.assertEqual(OTEL_WIRING.tool, "python3")
        self.assertEqual(OTEL_WIRING.category, "observability")
        self.assertTrue(OTEL_WIRING.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("otel_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        signals = json.loads(cmd[3])
        self.assertEqual(signals, ["traces", "metrics", "logs"])

    def test_build_cmd_custom_signals(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        profile = {"rules": {"observability": {"required_signals": ["traces"]}}}
        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", profile)
        signals = json.loads(cmd[3])
        self.assertEqual(signals, ["traces"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class HealthProbeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        self.assertEqual(HEALTH_PROBE.collector_id, "health-probe-observability")
        self.assertEqual(HEALTH_PROBE.tool, "python3")
        self.assertEqual(HEALTH_PROBE.category, "observability")
        self.assertTrue(HEALTH_PROBE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("health_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        endpoints = json.loads(cmd[3])
        self.assertEqual(endpoints, ["/healthz", "/readyz"])

    def test_build_cmd_custom_endpoints(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        profile = {"rules": {"observability": {"health_endpoints": ["/health", "/ready"]}}}
        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", profile)
        endpoints = json.loads(cmd[3])
        self.assertEqual(endpoints, ["/health", "/ready"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class SloCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import SLO

        self.assertEqual(SLO.collector_id, "slo-observability")
        self.assertEqual(SLO.tool, "python3")
        self.assertEqual(SLO.category, "observability")
        self.assertTrue(SLO.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import SLO

        cmd = SLO.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIsInstance(files, list)
        self.assertTrue(len(files) > 0)

    def test_build_cmd_custom_slo_files(self) -> None:
        from story_automator.core.collectors.observability import SLO

        profile = {"rules": {"observability": {"slo_files": ["slo/custom.yaml"]}}}
        cmd = SLO.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["slo/custom.yaml"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import SLO

        cmd = SLO.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class ObservabilityCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_observability_category(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "observability")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "otel-wiring-observability", "health-probe-observability",
            "slo-observability",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
