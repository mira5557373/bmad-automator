"""Resilience-category system-altitude collectors (§10/HR6(b)).

PASS rule: all Chaos Mesh scenarios passed.
Collectors: chaos-mesh pod-kill, net-loss, io-fault.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _chaos_pod_kill_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/pod-kill.yaml", "--dry-run=server"]


def _chaos_net_loss_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/net-loss.yaml", "--dry-run=server"]


def _chaos_io_fault_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/io-fault.yaml", "--dry-run=server"]


CHAOS_POD_KILL = CollectorConfig(
    collector_id="chaos-pod-kill-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_pod_kill_cmd,
)

CHAOS_NET_LOSS = CollectorConfig(
    collector_id="chaos-net-loss-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_net_loss_cmd,
)

CHAOS_IO_FAULT = CollectorConfig(
    collector_id="chaos-io-fault-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_io_fault_cmd,
)

COLLECTORS: list[CollectorConfig] = [CHAOS_POD_KILL, CHAOS_NET_LOSS, CHAOS_IO_FAULT]
