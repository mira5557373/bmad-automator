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

CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
    "test_quality": test_quality_rule,
    "mutation": mutation_rule,
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
