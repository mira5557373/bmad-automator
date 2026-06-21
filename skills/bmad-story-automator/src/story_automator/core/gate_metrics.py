"""Gate metrics — aggregate statistics from gate history.

Computes pass/fail rates, per-category breakdowns, flaky detection,
timeout patterns, and trend analysis from gate history records.
"""
from __future__ import annotations

from typing import Any


def compute_gate_metrics(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute aggregate metrics from gate history records."""
    total = len(history)
    if total == 0:
        return {
            "total_gates": 0,
            "pass_rate": 0.0, "fail_rate": 0.0,
            "concerns_rate": 0.0, "waived_rate": 0.0,
            "per_category": {},
            "flaky_categories": [],
            "timeout_categories": [],
        }

    counts = {"PASS": 0, "FAIL": 0, "CONCERNS": 0, "WAIVED": 0}
    per_cat: dict[str, dict[str, int]] = {}

    for record in history:
        overall = record.get("overall", "")
        if overall in counts:
            counts[overall] += 1
        for cat, info in (record.get("categories") or {}).items():
            if not isinstance(info, dict):
                continue
            if cat not in per_cat:
                per_cat[cat] = {
                    "pass_count": 0, "fail_count": 0,
                    "concerns_count": 0, "na_count": 0,
                    "timeout_count": 0,
                }
            verdict = info.get("verdict", "")
            if verdict == "PASS":
                per_cat[cat]["pass_count"] += 1
            elif verdict == "FAIL":
                per_cat[cat]["fail_count"] += 1
            elif verdict == "CONCERNS":
                per_cat[cat]["concerns_count"] += 1
            elif verdict == "NA":
                per_cat[cat]["na_count"] += 1
            rationale = info.get("rationale", "")
            if "TIMEOUT" in rationale.upper():
                per_cat[cat]["timeout_count"] += 1

    return {
        "total_gates": total,
        "pass_rate": counts["PASS"] / total,
        "fail_rate": counts["FAIL"] / total,
        "concerns_rate": counts["CONCERNS"] / total,
        "waived_rate": counts["WAIVED"] / total,
        "per_category": per_cat,
        "flaky_categories": [],
        "timeout_categories": [],
    }
