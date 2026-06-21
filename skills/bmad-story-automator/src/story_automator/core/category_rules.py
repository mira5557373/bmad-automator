"""Per-category rule functions for verdict engine (section 6.2, section 12).

Each rule interprets evidence metrics against profile thresholds and
returns a CategoryResult dict: {verdict, required, actual, rationale}.
Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any, Callable

from .product_profile import VALID_PRIORITIES, required_for_priority, rule_for

_P1_CONCERNS_FLOOR = 80
_DEFAULT_PRIORITY = "P1"


def coverage_verdict(actual_pct: float, target_pct: int, priority: str) -> str:
    """Section 12 TEA coverage thresholds.

    P0: must hit target exactly (100%); below = FAIL.
    P1: >= target = PASS; >= 80% = CONCERNS; < 80% = FAIL.
    P2/P3: >= target = PASS; below = FAIL.
    """
    if target_pct == 0:
        return "PASS"
    if actual_pct >= target_pct:
        return "PASS"
    if priority == "P1" and actual_pct >= _P1_CONCERNS_FLOOR:
        return "CONCERNS"
    return "FAIL"


def risk_to_requirements(
    priority: str, profile: dict[str, Any],
) -> dict[str, Any]:
    """Map risk priority to coverage/level requirements from profile.matrix."""
    if priority not in VALID_PRIORITIES:
        priority = _DEFAULT_PRIORITY
    req = required_for_priority(profile, priority)
    req["priority"] = priority
    return req


_STATUS_SEVERITY = {"ok": 0, "violation": 1, "timeout": 2, "error": 3}


def worst_evidence_status(records: list[dict[str, Any]]) -> str:
    """Find worst status across records. Empty = error (fail-closed)."""
    if not records:
        return "error"
    worst = "ok"
    worst_sev = 0
    for record in records:
        status = record.get("status", "error")
        sev = _STATUS_SEVERITY.get(status, 3)
        if sev > worst_sev:
            worst_sev = sev
            worst = status
    return worst


def _aggregate_metrics(
    evidence: list[dict[str, Any]], key: str, default: Any = 0,
) -> Any:
    """Extract a metric from the first evidence record that has it."""
    for record in evidence:
        metrics = record.get("metrics") or {}
        if key in metrics:
            return metrics[key]
    return default


def _make_category_result(
    verdict: str, required: dict[str, Any], actual: dict[str, Any], rationale: str,
) -> dict[str, Any]:
    return {"verdict": verdict, "required": required, "actual": actual, "rationale": rationale}


def correctness_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: all tiers green, 0 regressions, coverage >= risk-required."""
    status = worst_evidence_status(evidence)
    actual_coverage = float(_aggregate_metrics(evidence, "coverage_pct", 0))
    regressions = int(_aggregate_metrics(evidence, "regressions", 0))
    target = int(required.get("coverage_pct", 0))
    priority = str(required.get("priority", "P1"))

    actual = {"coverage_pct": actual_coverage, "regressions": regressions, "status": status}
    req = {"coverage_pct": target, "regressions": 0}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "test failures detected")
    if regressions > 0:
        return _make_category_result("FAIL", req, actual, f"{regressions} regression(s)")

    cov_verdict = coverage_verdict(actual_coverage, target, priority)
    if cov_verdict != "PASS":
        rationale = f"coverage {actual_coverage}% vs required {target}%"
        return _make_category_result(cov_verdict, req, actual, rationale)

    return _make_category_result("PASS", req, actual, "all checks passed")


def security_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: SAST 0 high+, deps 0 critical-unwaived, 0 secrets."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "security")
    max_sast = int(rules.get("sast_max_high", 0))
    max_deps = int(rules.get("deps_max_critical", 0))
    max_secrets = int(rules.get("secrets_max", 0))

    sast = int(_aggregate_metrics(evidence, "sast_high_count", 0))
    deps = int(_aggregate_metrics(evidence, "deps_critical_count", 0))
    secrets = int(_aggregate_metrics(evidence, "secrets_count", 0))

    actual = {"sast_high_count": sast, "deps_critical_count": deps,
              "secrets_count": secrets, "status": status}
    req = {"sast_max_high": max_sast, "deps_max_critical": max_deps,
           "secrets_max": max_secrets}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")

    violations: list[str] = []
    if sast > max_sast:
        violations.append(f"SAST high: {sast} > {max_sast}")
    if deps > max_deps:
        violations.append(f"deps critical: {deps} > {max_deps}")
    if secrets > max_secrets:
        violations.append(f"secrets: {secrets} > {max_secrets}")

    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "all security checks passed")


def _status_based_rule(category: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Generic rule: verdict follows worst evidence status."""
    status = worst_evidence_status(evidence)
    actual = {"status": status}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", {}, actual, f"fail-closed: collector {status}")
    if status == "violation":
        findings = []
        for r in evidence:
            if r.get("status") == "violation":
                findings.extend(r.get("findings", []))
        rationale = "; ".join(findings[:5]) if findings else "violations detected"
        return _make_category_result("FAIL", {}, actual, rationale)
    return _make_category_result("PASS", {}, actual, f"all {category} checks passed")


def static_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: tsc=0, mypy=0, ruff/Biome=0, deadcode <= budget."""
    return _status_based_rule("static", evidence)


def license_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: 0 forbidden licenses + boundary-aware (AGPL only in Odoo pod)."""
    status = worst_evidence_status(evidence)
    forbidden = int(_aggregate_metrics(evidence, "forbidden_count", 0))
    boundary = int(_aggregate_metrics(evidence, "boundary_violations", 0))
    rules = rule_for(profile, "license")

    actual = {"forbidden_count": forbidden, "boundary_violations": boundary, "status": status}
    req = {"forbidden_count": 0, "boundary_violations": 0,
           "forbidden_licenses": rules.get("forbidden", []),
           "boundary_rules": rules.get("boundary", {})}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")

    violations: list[str] = []
    if forbidden > 0:
        violations.append(f"forbidden licenses: {forbidden}")
    if boundary > 0:
        violations.append(f"boundary violations: {boundary}")
    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "all license checks passed")


def generic_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Fallback rule: verdict follows worst evidence status."""
    return _status_based_rule("category", evidence)


CategoryRuleFn = Callable[[list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]]

def reliability_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(a): RTO/RPO within profile limits."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "reliability")
    max_rto = int(rules.get("max_rto_seconds", 300))
    max_rpo = int(rules.get("max_rpo_seconds", 60))
    rto = float(_aggregate_metrics(evidence, "rto_seconds", 0))
    rpo = float(_aggregate_metrics(evidence, "rpo_seconds", 0))
    actual = {"rto_seconds": rto, "rpo_seconds": rpo, "status": status}
    req = {"max_rto_seconds": max_rto, "max_rpo_seconds": max_rpo}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    violations: list[str] = []
    if rto > max_rto:
        violations.append(f"RTO {rto}s > max {max_rto}s")
    if rpo > max_rpo:
        violations.append(f"RPO {rpo}s > max {max_rpo}s")
    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "reliability checks passed")


def resilience_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(b): all chaos scenarios passed."""
    status = worst_evidence_status(evidence)
    total = int(_aggregate_metrics(evidence, "scenarios_total", 0))
    passed = int(_aggregate_metrics(evidence, "scenarios_passed", 0))
    actual = {"scenarios_total": total, "scenarios_passed": passed, "status": status}
    req = {"all_scenarios_pass": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if total == 0:
        return _make_category_result("FAIL", req, actual, "no resilience scenarios executed")
    if passed < total:
        failed = total - passed
        return _make_category_result("FAIL", req, actual, f"{failed} scenario(s) failed out of {total}")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "all resilience scenarios passed")


def blast_radius_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(d): tenant SLO isolation under load."""
    status = worst_evidence_status(evidence)
    slo_breached = bool(_aggregate_metrics(evidence, "slo_breached", False))
    actual = {"slo_breached": slo_breached, "status": status}
    req = {"slo_breached": False}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if slo_breached:
        return _make_category_result("FAIL", req, actual, "tenant SLO breached during load test")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "blast radius check passed")


def durable_hitl_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(c): Temporal signal survived pod kill."""
    status = worst_evidence_status(evidence)
    survived = bool(_aggregate_metrics(evidence, "signal_survived", False))
    actual = {"signal_survived": survived, "status": status}
    req = {"signal_survived": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if not survived:
        return _make_category_result("FAIL", req, actual, "Temporal signal lost after pod kill")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "durable HITL check passed")


CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
    "reliability": reliability_rule,
    "resilience": resilience_rule,
    "blast_radius": blast_radius_rule,
    "durable_hitl": durable_hitl_rule,
}


def apply_category_rule(
    category: str,
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch to the right rule function for a category."""
    rule_fn = CATEGORY_RULES.get(category)
    if rule_fn is not None:
        return rule_fn(evidence, profile, required)
    return _status_based_rule(category, evidence)
