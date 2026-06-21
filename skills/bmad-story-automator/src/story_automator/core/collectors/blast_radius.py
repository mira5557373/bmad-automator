"""Blast-radius-category system-altitude collector (§10/HR6(d)).

PASS rule: loading tenant A does not breach tenant B's SLO.
Collector: k6-blast-radius.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _k6_blast_radius_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    rules = (profile.get("rules") or {}).get("blast_radius") or {}
    script = rules.get("k6_script", "k6/blast-radius.js")
    return [
        "k6", "run",
        "--env", f"NAMESPACE={ns}",
        "--out", "json=blast-radius-results.json",
        script,
    ]


K6_BLAST_RADIUS = CollectorConfig(
    collector_id="k6-blast-radius",
    tool="k6",
    category="blast_radius",
    build_cmd=_k6_blast_radius_cmd,
    tool_version_cmd=("k6", "version"),
)

COLLECTORS: list[CollectorConfig] = [K6_BLAST_RADIUS]
