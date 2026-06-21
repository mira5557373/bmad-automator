"""Cost-to-serve-category system-altitude collectors (§10/HR6(f)).

PASS rule: pod cost per tenant <= max_pod_cost_per_tenant.
CONCERNS if DG-2/SKU undefined (§6.4 degradation path).
Collectors: k6-cost-to-serve (load generation), kubectl-resources (resource measurement).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _k6_cost_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    rules = (profile.get("rules") or {}).get("cost_to_serve") or {}
    script = rules.get("k6_script", "k6/cost-to-serve.js")
    return [
        "k6", "run",
        "--env", f"NAMESPACE={ns}",
        "--out", "json=cost-results.json",
        script,
    ]


def _kubectl_resources_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "top", "pods",
        "-n", ns,
        "--no-headers",
    ]


K6_COST = CollectorConfig(
    collector_id="k6-cost-to-serve",
    tool="k6",
    category="cost_to_serve",
    build_cmd=_k6_cost_cmd,
    tool_version_cmd=("k6", "version"),
)

KUBECTL_RESOURCES = CollectorConfig(
    collector_id="kubectl-resources-cost-to-serve",
    tool="kubectl",
    category="cost_to_serve",
    build_cmd=_kubectl_resources_cmd,
    tool_version_cmd=("kubectl", "version", "--client"),
)

COLLECTORS: list[CollectorConfig] = [K6_COST, KUBECTL_RESOURCES]
