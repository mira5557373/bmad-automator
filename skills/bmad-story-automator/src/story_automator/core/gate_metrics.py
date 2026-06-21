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
        "flaky_categories": detect_flaky_categories(history),
        "timeout_categories": detect_timeout_categories(history),
        "category_trends": compute_category_trends(history),
    }


def detect_flaky_categories(
    history: list[dict[str, Any]],
    *,
    min_flips: int = 3,
) -> list[str]:
    """Detect categories that flip between PASS and FAIL."""
    sequences: dict[str, list[str]] = {}
    for record in history:
        for cat, info in (record.get("categories") or {}).items():
            if not isinstance(info, dict):
                continue
            verdict = info.get("verdict", "")
            if verdict in ("PASS", "FAIL"):
                sequences.setdefault(cat, []).append(verdict)

    flaky: list[str] = []
    for cat, seq in sorted(sequences.items()):
        flips = sum(
            1 for i in range(1, len(seq)) if seq[i] != seq[i - 1]
        )
        if flips >= min_flips:
            flaky.append(cat)
    return flaky


def detect_timeout_categories(
    history: list[dict[str, Any]],
    *,
    min_rate: float = 0.3,
) -> list[str]:
    """Detect categories with recurring timeout rationale."""
    cat_counts: dict[str, dict[str, int]] = {}
    for record in history:
        for cat, info in (record.get("categories") or {}).items():
            if not isinstance(info, dict):
                continue
            if cat not in cat_counts:
                cat_counts[cat] = {"total": 0, "timeout": 0}
            cat_counts[cat]["total"] += 1
            rationale = info.get("rationale", "")
            if "TIMEOUT" in rationale.upper():
                cat_counts[cat]["timeout"] += 1

    timeout_cats: list[str] = []
    for cat, counts in sorted(cat_counts.items()):
        if counts["total"] > 0 and counts["timeout"] / counts["total"] >= min_rate:
            timeout_cats.append(cat)
    return timeout_cats


def compute_category_trends(
    history: list[dict[str, Any]],
    *,
    window: int = 10,
) -> dict[str, str]:
    """Compute per-category trend direction over a sliding window.

    Compares pass rate in the first half vs second half of the window.
    Returns: "improving" (second-half pass rate higher), "degrading"
    (second-half lower), or "stable" (within 10% tolerance).
    """
    sequences: dict[str, list[str]] = {}
    for record in history:
        for cat, info in (record.get("categories") or {}).items():
            if not isinstance(info, dict):
                continue
            verdict = info.get("verdict", "")
            if verdict in ("PASS", "FAIL", "CONCERNS"):
                sequences.setdefault(cat, []).append(verdict)

    trends: dict[str, str] = {}
    for cat, seq in sorted(sequences.items()):
        recent = seq[-window:] if len(seq) > window else seq
        if len(recent) < 2:
            trends[cat] = "stable"
            continue
        mid = len(recent) // 2
        first_half = recent[:mid]
        second_half = recent[mid:]
        first_pass = (
            sum(1 for v in first_half if v == "PASS") / len(first_half)
            if first_half else 0
        )
        second_pass = (
            sum(1 for v in second_half if v == "PASS") / len(second_half)
            if second_half else 0
        )
        diff = second_pass - first_pass
        if diff > 0.1:
            trends[cat] = "improving"
        elif diff < -0.1:
            trends[cat] = "degrading"
        else:
            trends[cat] = "stable"
    return trends
