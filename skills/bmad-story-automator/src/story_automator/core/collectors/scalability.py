"""Scalability-category evidence collectors — TEA fourth NFR domain.

TEA's NFR contract has four domains: performance, reliability, security,
and scalability.  Performance, reliability, and security each ship their
own collectors module (``performance.py``, ``reliability.py``,
``security.py``).  This module closes the set with the scalability
domain.

PASS rule
---------
A change PASSes scalability if **all** of the following hold:

1.  ``k6-scalability`` — a k6 run on the scalability capacity-ramp
    profile finishes within budget and the run's per-iteration error
    rate stays below the profile's ``error_budget_pct``.
2.  ``scale-lint-scalability`` — the static lint finds zero unbounded
    fan-out / unbounded-queue / N+1 patterns in the changed source.
3.  ``capacity-plan-scalability`` — a capacity-plan doc exists in the
    checkout, declares a ``headroom_pct`` value, and that headroom is
    at least the profile's ``min_headroom_pct`` floor (default 30%).

Each sub-collector returns its evidence to the collector runner via the
shared ``CollectorConfig`` contract; the adjudicator combines the three
verdicts under the ``scalability`` category.

Profile keys (under ``rules.scalability``)
------------------------------------------

* ``k6_script`` (str, default ``"k6/scalability.js"``) — relative path
  to the k6 capacity-ramp script inside the checkout.
* ``lint_extensions`` (list[str], optional) — restrict the static
  scanner to these file extensions; default is the union of common
  backend + frontend source extensions.
* ``capacity_plan_path`` (str, default ``"docs/capacity-plan.md"``) —
  path to the capacity-plan markdown.
* ``min_headroom_pct`` (int, default ``30``) — minimum required
  headroom percentage declared in the capacity-plan doc.

The runtime env ``_runtime_env.namespace`` is threaded into the k6
command as ``NAMESPACE=…`` so the load profile can target the right
cluster, mirroring ``cost_to_serve`` and ``blast_radius``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

__all__ = [
    "K6_SCALABILITY",
    "SCALE_LINT",
    "CAPACITY_PLAN",
    "COLLECTORS",
]

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

# ---- defaults --------------------------------------------------------------
_DEFAULT_K6_SCRIPT = "k6/scalability.js"
_DEFAULT_K6_RESULTS = "scalability-results.json"
_DEFAULT_CAPACITY_PLAN_PATH = "docs/capacity-plan.md"
_DEFAULT_MIN_HEADROOM_PCT = 30
_DEFAULT_LINT_EXTENSIONS: tuple[str, ...] = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
)


# ---- helpers ---------------------------------------------------------------
def _scalability_rules(profile: dict[str, Any]) -> dict[str, Any]:
    rules = (profile.get("rules") or {}).get("scalability") or {}
    if not isinstance(rules, dict):  # defensive: ignore malformed
        return {}
    return rules


def _runtime_namespace(profile: dict[str, Any]) -> str:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return str(ns) if ns is not None else "default"


# ---- k6 capacity-ramp ------------------------------------------------------
def _k6_scalability_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Build the k6 invocation for the scalability capacity-ramp scenario.

    The k6 script writes a deterministic JSON artifact so the
    adjudicator can compute the error-rate verdict without re-running
    the load test.
    """
    rules = _scalability_rules(profile)
    script = str(rules.get("k6_script") or _DEFAULT_K6_SCRIPT)
    namespace = _runtime_namespace(profile)
    return [
        "k6", "run",
        "--env", f"NAMESPACE={namespace}",
        "--out", f"json={_DEFAULT_K6_RESULTS}",
        script,
    ]


# ---- scale-lint static check ----------------------------------------------
def _scale_lint_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Build the static-lint invocation for unbounded fan-out / queues.

    Mirrors the ``perf-lint-performance`` command shape: the checkout
    path is positional, optional extension overrides are JSON-encoded
    as a trailing argument so the check script can parse them with a
    single ``json.loads(sys.argv[-1])`` call.
    """
    rules = _scalability_rules(profile)
    cmd: list[str] = [
        sys.executable,
        str(_CHECKS_DIR / "scale_lint_check.py"),
        checkout,
    ]
    extensions = rules.get("lint_extensions")
    if extensions:
        # Stable ordering and explicit list typing for the wire format.
        cmd.append(json.dumps(list(extensions)))
    return cmd


# ---- capacity-plan doc presence + headroom --------------------------------
def _capacity_plan_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Build the capacity-plan reader invocation.

    The doc path is profile-overridable so different products can pin
    their plan under different markdown locations.  ``min_headroom_pct``
    is threaded as an explicit flag so the check script does not need
    to parse the full profile.
    """
    rules = _scalability_rules(profile)
    doc_path = str(rules.get("capacity_plan_path") or _DEFAULT_CAPACITY_PLAN_PATH)
    raw_floor = rules.get("min_headroom_pct", _DEFAULT_MIN_HEADROOM_PCT)
    try:
        min_headroom = int(raw_floor)
    except (TypeError, ValueError):
        min_headroom = _DEFAULT_MIN_HEADROOM_PCT
    return [
        sys.executable,
        str(_CHECKS_DIR / "capacity_plan_check.py"),
        checkout,
        doc_path,
        "--min-headroom-pct",
        str(min_headroom),
    ]


# ---- CollectorConfig declarations -----------------------------------------
K6_SCALABILITY = CollectorConfig(
    collector_id="k6-scalability",
    tool="k6",
    category="scalability",
    build_cmd=_k6_scalability_cmd,
    tool_version_cmd=("k6", "version"),
)

SCALE_LINT = CollectorConfig(
    collector_id="scale-lint-scalability",
    tool="python3",
    category="scalability",
    build_cmd=_scale_lint_cmd,
    file_patterns=frozenset({f"*{ext}" for ext in _DEFAULT_LINT_EXTENSIONS}),
)

CAPACITY_PLAN = CollectorConfig(
    collector_id="capacity-plan-scalability",
    tool="python3",
    category="scalability",
    build_cmd=_capacity_plan_cmd,
    file_patterns=frozenset({"*.md"}),
)

COLLECTORS: list[CollectorConfig] = [
    K6_SCALABILITY,
    SCALE_LINT,
    CAPACITY_PLAN,
]
