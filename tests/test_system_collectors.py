"""Tests for system-altitude evidence collectors."""
from __future__ import annotations

import unittest

from story_automator.core.collectors.reliability import (
    CNPG_FAILOVER,
    PGBACKREST_RESTORE,
    COLLECTORS as RELIABILITY_COLLECTORS,
)
from story_automator.core.collectors.resilience import (
    CHAOS_POD_KILL,
    CHAOS_NET_LOSS,
    CHAOS_IO_FAULT,
    COLLECTORS as RESILIENCE_COLLECTORS,
)
from story_automator.core.collectors.durable_hitl import (
    TEMPORAL_SIGNAL,
    COLLECTORS as DURABLE_HITL_COLLECTORS,
)
from story_automator.core.collectors.blast_radius import (
    K6_BLAST_RADIUS,
    COLLECTORS as BLAST_RADIUS_COLLECTORS,
)
from story_automator.core.collectors.cost_to_serve import (
    K6_COST,
    KUBECTL_RESOURCES,
    COLLECTORS as COST_COLLECTORS,
)
from story_automator.core.collectors.progressive_delivery import (
    ARGO_ROLLOUTS,
    COLLECTORS as PROGRESSIVE_COLLECTORS,
)


def _sys_profile(**extras: object) -> dict:
    return {
        "version": 1, "id": "test",
        "rules": {"reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60}},
        "_runtime_env": {"namespace": "gate-test-abc12345", "tier": "full"},
        **extras,
    }


class ReliabilityCollectorTests(unittest.TestCase):
    def test_cnpg_failover_config(self) -> None:
        self.assertEqual(CNPG_FAILOVER.category, "reliability")
        self.assertEqual(CNPG_FAILOVER.tool, "cnpg")
        self.assertEqual(CNPG_FAILOVER.collector_id, "cnpg-reliability")

    def test_pgbackrest_config(self) -> None:
        self.assertEqual(PGBACKREST_RESTORE.category, "reliability")
        self.assertEqual(PGBACKREST_RESTORE.tool, "pgbackrest")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(RELIABILITY_COLLECTORS), 2)
        self.assertIn(CNPG_FAILOVER, RELIABILITY_COLLECTORS)
        self.assertIn(PGBACKREST_RESTORE, RELIABILITY_COLLECTORS)

    def test_cnpg_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = CNPG_FAILOVER.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))

    def test_pgbackrest_cmd(self) -> None:
        profile = _sys_profile()
        cmd = PGBACKREST_RESTORE.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(len(cmd) > 0)


class ResilienceCollectorTests(unittest.TestCase):
    def test_pod_kill_config(self) -> None:
        self.assertEqual(CHAOS_POD_KILL.category, "resilience")
        self.assertEqual(CHAOS_POD_KILL.tool, "chaos-mesh")

    def test_net_loss_config(self) -> None:
        self.assertEqual(CHAOS_NET_LOSS.category, "resilience")

    def test_io_fault_config(self) -> None:
        self.assertEqual(CHAOS_IO_FAULT.category, "resilience")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(RESILIENCE_COLLECTORS), 3)

    def test_pod_kill_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = CHAOS_POD_KILL.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))


class DurableHitlCollectorTests(unittest.TestCase):
    def test_temporal_signal_config(self) -> None:
        self.assertEqual(TEMPORAL_SIGNAL.category, "durable_hitl")
        self.assertEqual(TEMPORAL_SIGNAL.tool, "temporal")
        self.assertEqual(TEMPORAL_SIGNAL.collector_id, "temporal-durable-hitl")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(DURABLE_HITL_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = TEMPORAL_SIGNAL.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)


class BlastRadiusCollectorTests(unittest.TestCase):
    def test_k6_config(self) -> None:
        self.assertEqual(K6_BLAST_RADIUS.category, "blast_radius")
        self.assertEqual(K6_BLAST_RADIUS.tool, "k6")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(BLAST_RADIUS_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = K6_BLAST_RADIUS.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("k6" in arg for arg in cmd))


class CostToServeCollectorTests(unittest.TestCase):
    def test_k6_cost_config(self) -> None:
        self.assertEqual(K6_COST.category, "cost_to_serve")
        self.assertEqual(K6_COST.tool, "k6")

    def test_kubectl_resources_config(self) -> None:
        self.assertEqual(KUBECTL_RESOURCES.category, "cost_to_serve")
        self.assertEqual(KUBECTL_RESOURCES.tool, "kubectl")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(COST_COLLECTORS), 2)

    def test_k6_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = K6_COST.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)


class ProgressiveDeliveryCollectorTests(unittest.TestCase):
    def test_argo_config(self) -> None:
        self.assertEqual(ARGO_ROLLOUTS.category, "progressive_delivery")
        self.assertEqual(ARGO_ROLLOUTS.tool, "argo-rollouts")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(PROGRESSIVE_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = ARGO_ROLLOUTS.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))


if __name__ == "__main__":
    unittest.main()
