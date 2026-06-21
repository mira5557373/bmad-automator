"""Progressive-delivery system-altitude collector (§10).

PASS rule: Argo Rollouts blue-green/canary completed successfully.
Collector: argo-progressive-delivery.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _argo_rollouts_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "argo", "rollouts", "list", "rollouts",
        "-n", ns,
        "-o", "json",
    ]


ARGO_ROLLOUTS = CollectorConfig(
    collector_id="argo-progressive-delivery",
    tool="argo-rollouts",
    category="progressive_delivery",
    build_cmd=_argo_rollouts_cmd,
    tool_version_cmd=("kubectl", "argo", "rollouts", "version"),
)

COLLECTORS: list[CollectorConfig] = [ARGO_ROLLOUTS]
