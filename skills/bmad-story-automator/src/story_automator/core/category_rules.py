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


def _bool_any(values: list[Any]) -> bool:
    """Worst-case reducer for booleans where True == bad."""
    return any(bool(v) for v in values)


def _bool_all(values: list[Any]) -> bool:
    """Worst-case reducer for booleans where False == bad (e.g. signal_survived)."""
    return all(bool(v) for v in values)


def _first(values: list[Any]) -> Any:
    """Reducer for non-numeric labels (e.g. rollout strategy name)."""
    return values[0]


# Per-metric worst-case reducer table. Multi-collector categories MUST use
# the most conservative aggregation so a clean record cannot mask a violating
# one (production-ready gate: worst-of across collectors).
_METRIC_REDUCERS: dict[str, Callable[[list[Any]], Any]] = {
    # Counts of bad things -> sum (more bad spread across tools is still more bad).
    "sast_high_count": sum,
    "deps_critical_count": sum,
    "secrets_count": sum,
    "regressions": sum,
    "flaky_count": sum,
    "hard_wait_count": sum,
    "forbidden_count": sum,
    "boundary_violations": sum,
    "mutants_survived": sum,
    "mutants_total": sum,
    "mutants_killed": sum,
    # Percentages / scores where lower is worse -> min (worst tier wins).
    "coverage_pct": min,
    "mutation_score": min,
    "mutation_score_pct": min,
    "test_review_score": min,
    "scenarios_passed": min,
    # Totals / maxima where higher is worse -> max.
    "rto_seconds": max,
    "rpo_seconds": max,
    "pod_cost_per_tenant": max,
    "scenarios_total": max,
    # Booleans where True == bad (any failing collector poisons the verdict).
    "slo_breached": _bool_any,
    # Booleans where True == good / required (any failing collector fails the gate).
    "signal_survived": _bool_all,
    "rollout_completed": _bool_all,
    # Non-numeric labels: keep the first record's value (informational only).
    "strategy": _first,
}


def _aggregate_metrics(
    evidence: list[dict[str, Any]], key: str, default: Any = 0,
) -> Any:
    """Worst-of aggregation of ``key`` across every evidence record.

    Multi-collector categories (security/correctness/test_quality/license/...)
    fan out to several tools whose evidence records are appended in arbitrary
    order. A clean record from tool A must never mask a violating record from
    tool B, so we reduce *all* records that carry ``key`` through a per-metric
    worst-case reducer (see ``_METRIC_REDUCERS``). Unknown keys default to
    ``max`` which is the most conservative reduction for numeric counts.
    """
    values: list[Any] = []
    for record in evidence:
        metrics = record.get("metrics") or {}
        if key in metrics:
            values.append(metrics[key])
    if not values:
        return default
    reducer = _METRIC_REDUCERS.get(key, max)
    return reducer(values)


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


def test_quality_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: TEA test-review >= band; 0 flaky over burn-in; no hard-waits."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "test_quality")
    max_flaky = int(rules.get("max_flaky", 0))
    min_score = float(rules.get("min_score", 70))

    flaky_count = int(_aggregate_metrics(evidence, "flaky_count", 0))
    hard_wait_count = int(_aggregate_metrics(evidence, "hard_wait_count", 0))
    test_review_score = _aggregate_metrics(evidence, "test_review_score", None)

    actual = {
        "flaky_count": flaky_count,
        "hard_wait_count": hard_wait_count,
        "test_review_score": test_review_score,
        "status": status,
    }
    req = {"max_flaky": max_flaky, "min_score": min_score, "hard_wait_count": 0}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")

    violations: list[str] = []
    if flaky_count > max_flaky:
        violations.append(f"flaky tests: {flaky_count} > {max_flaky}")
    if hard_wait_count > 0:
        violations.append(f"hard-wait(s): {hard_wait_count}")
    if test_review_score is not None and float(test_review_score) < min_score:
        violations.append(f"test-review score: {test_review_score} < {min_score}")
    if status == "violation":
        violations.append("collector reported violation")

    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    return _make_category_result("PASS", req, actual, "all test-quality checks passed")


def mutation_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: mutation score >= threshold on changed code."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "mutation")
    min_score = float(rules.get("min_score", 60))

    mutation_score = float(_aggregate_metrics(evidence, "mutation_score", 0))
    mutants_total = int(_aggregate_metrics(evidence, "mutants_total", 0))
    mutants_killed = int(_aggregate_metrics(evidence, "mutants_killed", 0))
    mutants_survived = int(_aggregate_metrics(evidence, "mutants_survived", 0))

    actual = {
        "mutation_score": mutation_score,
        "mutants_total": mutants_total,
        "mutants_killed": mutants_killed,
        "mutants_survived": mutants_survived,
        "status": status,
    }
    req = {"min_score": min_score}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if mutants_total == 0 and status != "ok":
        return _make_category_result("FAIL", req, actual, "mutation tool did not produce results")
    if mutation_score < min_score:
        return _make_category_result(
            "FAIL", req, actual,
            f"mutation score {mutation_score:.1f}% < {min_score}%",
        )
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "mutation testing passed")


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


def cost_to_serve_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(f): cost_to_serve with DG-2 degradation path."""
    from .gate_rules import verdict_for_cost_tier

    status = worst_evidence_status(evidence)
    cost_tier = profile.get("cost_tier")
    forbidden = profile.get("forbidden_until")
    pod_cost = float(_aggregate_metrics(evidence, "pod_cost_per_tenant", 0))
    max_cost = float((cost_tier or {}).get("max_pod_cost_per_tenant", 0))
    actual = {"pod_cost_per_tenant": pod_cost, "status": status}
    req = {"max_pod_cost_per_tenant": max_cost}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    tier_verdict = verdict_for_cost_tier(cost_tier, forbidden)
    if tier_verdict == "CONCERNS":
        return _make_category_result("CONCERNS", req, actual, "cost_to_serve degraded: DG-2/SKU undefined")
    if max_cost > 0 and pod_cost > max_cost:
        return _make_category_result("FAIL", req, actual, f"pod cost {pod_cost} > max {max_cost}")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "cost-to-serve check passed")


def progressive_delivery_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10: progressive-delivery rollout evidence (Argo Rollouts)."""
    status = worst_evidence_status(evidence)
    completed = bool(_aggregate_metrics(evidence, "rollout_completed", False))
    strategy = str(_aggregate_metrics(evidence, "strategy", ""))
    actual = {"rollout_completed": completed, "strategy": strategy, "status": status}
    req = {"rollout_completed": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if not completed:
        return _make_category_result("FAIL", req, actual, "progressive delivery rollout did not complete")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "progressive delivery check passed")


def cert_cadence_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§13/HR6(e): cert-cadence is a human/release gate checkpoint."""
    status = worst_evidence_status(evidence)
    actual = {"status": status}
    req = {"human_review": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if status == "ok" and evidence:
        return _make_category_result("PASS", req, actual, "cert-cadence human review completed")
    return _make_category_result(
        "CONCERNS", req, actual,
        "cert-cadence requires human/release gate review",
    )


CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
    "test_quality": test_quality_rule,
    "mutation": mutation_rule,
    "reliability": reliability_rule,
    "resilience": resilience_rule,
    "blast_radius": blast_radius_rule,
    "durable_hitl": durable_hitl_rule,
    "cost_to_serve": cost_to_serve_rule,
    "progressive_delivery": progressive_delivery_rule,
    "cert_cadence": cert_cadence_rule,
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
