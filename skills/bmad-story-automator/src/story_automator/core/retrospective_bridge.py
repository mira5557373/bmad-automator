"""Retrospective bridge — format gate data for BMAD retrospective.

Produces structured summaries and markdown-formatted sections that
the BMAD retrospective skill can consume for data-driven insights.
"""
from __future__ import annotations

from typing import Any


def build_retrospective_summary(
    metrics: dict[str, Any],
    calibrations_applied: list[Any],
    *,
    calibrations_deferred: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a structured retrospective summary from metrics and calibrations."""
    per_cat = metrics.get("per_category", {})
    top_failing = sorted(
        ((cat, info.get("fail_count", 0)) for cat, info in per_cat.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    return {
        "total_gates": metrics.get("total_gates", 0),
        "pass_rate": metrics.get("pass_rate", 0.0),
        "fail_rate": metrics.get("fail_rate", 0.0),
        "concerns_rate": metrics.get("concerns_rate", 0.0),
        "waived_rate": metrics.get("waived_rate", 0.0),
        "flaky_categories": metrics.get("flaky_categories", []),
        "timeout_categories": metrics.get("timeout_categories", []),
        "calibrations_applied": len(calibrations_applied),
        "calibrations_deferred": len(calibrations_deferred or []),
        "top_failing_categories": top_failing,
    }


def format_retrospective_markdown(summary: dict[str, Any]) -> str:
    """Format a retrospective summary as markdown."""
    total = summary.get("total_gates", 0)
    if total == 0:
        return (
            "## Gate Quality Summary\n\n"
            "No gate evaluations recorded in this period.\n"
        )

    lines = [
        "## Gate Quality Summary",
        "",
        f"**Total gate evaluations:** {total}",
        f"- Pass rate: {summary['pass_rate'] * 100:.1f}%",
        f"- Fail rate: {summary['fail_rate'] * 100:.1f}%",
        f"- Concerns rate: {summary['concerns_rate'] * 100:.1f}%",
        f"- Waived rate: {summary['waived_rate'] * 100:.1f}%",
        "",
    ]
    flaky = summary.get("flaky_categories", [])
    if flaky:
        lines.append(f"**Flaky categories:** {', '.join(flaky)}")
        lines.append("")

    timeout = summary.get("timeout_categories", [])
    if timeout:
        lines.append(f"**Timeout-prone categories:** {', '.join(timeout)}")
        lines.append("")

    top_failing = summary.get("top_failing_categories", [])
    if top_failing:
        lines.append("**Top failing categories:**")
        for cat, count in top_failing:
            if count > 0:
                lines.append(f"- {cat}: {count} failures")
        lines.append("")

    applied = summary.get("calibrations_applied", 0)
    deferred = summary.get("calibrations_deferred", 0)
    if applied or deferred:
        lines.append(
            f"**Calibrations:** {applied} applied, {deferred} deferred (breaking)"
        )
        lines.append("")

    return "\n".join(lines) + "\n"
