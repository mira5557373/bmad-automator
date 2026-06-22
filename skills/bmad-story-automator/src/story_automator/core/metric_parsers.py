"""Stdlib-only metric parsers that convert collector stdout into the metric
keys that ``category_rules`` reads (A-01).

Each parser is a pure function ``(stdout: str) -> dict[str, bool|int|float|str]``
and is **fail-safe**: on empty / malformed / unexpected input it returns ``{}``
rather than raising. The adjudicator additionally wraps every parser in
``try/except`` for defence-in-depth — a misbehaving custom parser must never
crash the gate.

Why parsers and not a richer JSON contract from the checks themselves: the
checks already emit ``MUTATION_RESULT: {…}`` / ``BURN_IN_RESULT: {…}`` /
``coverage: X.X%`` summary lines, and we deliberately preserve the existing
stdout format so the human-facing CLI output is unchanged. We just stop
throwing the structured payload away on its way to the evidence record.

Parser output keys are the same names ``category_rules._aggregate_metrics``
looks for:

- correctness:  ``coverage_pct``
- mutation:     ``mutation_score``, ``mutants_total``, ``mutants_killed``,
                ``mutants_survived``
- security:     ``sast_high_count``, ``deps_critical_count``, ``secrets_count``
- test_quality: ``flaky_count``

Only those numeric keys are extracted — see
``_MUTATION_KEYS`` / ``_BURN_IN_KEYS`` whitelists. Arbitrary JSON-payload
keys are dropped so a misbehaving collector cannot smuggle non-scalar values
that would later be rejected by ``validate_evidence_record``.
"""
from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "parse_mutation_metrics",
    "parse_coverage_metrics",
    "parse_burn_in_metrics",
    "parse_semgrep_metrics",
    "parse_trivy_metrics",
    "parse_osv_metrics",
    "parse_gitleaks_metrics",
]

# Whitelisted numeric keys per parser. Matches the names that
# ``category_rules._aggregate_metrics`` looks for.
_MUTATION_KEYS = frozenset({
    "mutation_score",
    "mutants_total",
    "mutants_killed",
    "mutants_survived",
})
_BURN_IN_KEYS = frozenset({"flaky_count"})

# Severity strings that semgrep emits for findings we treat as "high".
# semgrep's CLI labels findings ``ERROR``/``WARNING``/``INFO``; semgrep-pro
# also emits ``CRITICAL``/``HIGH``. We count ERROR + CRITICAL + HIGH as "high".
_SEMGREP_HIGH = frozenset({"ERROR", "CRITICAL", "HIGH"})

_COVERAGE_RE = re.compile(r"coverage:\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE)
_MUTATION_LINE_RE = re.compile(r"^MUTATION_RESULT:\s*(\{.*\})\s*$", re.MULTILINE)
_BURN_IN_LINE_RE = re.compile(r"^BURN_IN_RESULT:\s*(\{.*\})\s*$", re.MULTILINE)


def _filter_numeric(raw: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    """Extract only the allowed keys whose values are bool|int|float (not NaN/inf)."""
    out: dict[str, Any] = {}
    for key in allowed:
        if key not in raw:
            continue
        val = raw[key]
        if isinstance(val, bool):
            out[key] = val
            continue
        if isinstance(val, int):
            out[key] = val
            continue
        if isinstance(val, float):
            # Reject NaN/inf — ``validate_evidence_record`` will reject them
            # downstream, but we'd rather not surface broken metrics at all.
            if val != val or val in (float("inf"), float("-inf")):
                continue
            out[key] = val
            continue
        # Drop strings/lists/etc — verdict rules expect numerics.
    return out


def parse_mutation_metrics(stdout: str) -> dict[str, Any]:
    """Parse ``MUTATION_RESULT: {…}`` JSON line from mutation_check.py stdout."""
    if not stdout:
        return {}
    match = _MUTATION_LINE_RE.search(stdout)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return _filter_numeric(payload, _MUTATION_KEYS)


def parse_coverage_metrics(stdout: str) -> dict[str, Any]:
    """Parse ``coverage: 82.7%`` summary line from coverage_check.py stdout."""
    if not stdout:
        return {}
    match = _COVERAGE_RE.search(stdout)
    if not match:
        return {}
    try:
        pct = float(match.group(1))
    except (TypeError, ValueError):
        return {}
    if pct != pct or pct in (float("inf"), float("-inf")):
        return {}
    return {"coverage_pct": pct}


def parse_burn_in_metrics(stdout: str) -> dict[str, Any]:
    """Parse ``BURN_IN_RESULT: {…}`` JSON line from burn_in_check.py stdout."""
    if not stdout:
        return {}
    match = _BURN_IN_LINE_RE.search(stdout)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return _filter_numeric(payload, _BURN_IN_KEYS)


def parse_semgrep_metrics(stdout: str) -> dict[str, Any]:
    """Parse semgrep JSON output and count ERROR/CRITICAL/HIGH findings.

    Semgrep emits findings on stdout when invoked with ``--json``; without
    ``--json`` the output is text. The security collector currently invokes
    ``semgrep scan --config=… --error`` which prints text. If/when the
    collector is upgraded to emit JSON, this parser will pick it up; until
    then we still try to parse so a misconfigured run doesn't silently
    pass the gate.
    """
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    count = 0
    for finding in results:
        if not isinstance(finding, dict):
            continue
        extra = finding.get("extra")
        if not isinstance(extra, dict):
            continue
        severity = extra.get("severity")
        if isinstance(severity, str) and severity.upper() in _SEMGREP_HIGH:
            count += 1
    return {"sast_high_count": count}


def parse_trivy_metrics(stdout: str) -> dict[str, Any]:
    """Parse trivy JSON output and count CRITICAL vulnerabilities."""
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    results = payload.get("Results")
    if not isinstance(results, list):
        return {}
    count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        vulns = result.get("Vulnerabilities")
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            sev = vuln.get("Severity")
            if isinstance(sev, str) and sev.upper() == "CRITICAL":
                count += 1
    return {"deps_critical_count": count}


def parse_osv_metrics(stdout: str) -> dict[str, Any]:
    """Parse osv-scanner JSON output and count CRITICAL vulnerabilities.

    osv-scanner's JSON shape is ``results[].packages[].vulnerabilities[]``
    where severity lives under ``database_specific.severity`` or
    ``severity[].score``. We use the simpler ``database_specific.severity``
    path because that's what osv-scanner v1.x emits for the common case;
    if a vuln has neither, it doesn't count toward the critical tally.
    """
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        for pkg in result.get("packages", []) or []:
            if not isinstance(pkg, dict):
                continue
            for vuln in pkg.get("vulnerabilities", []) or []:
                if not isinstance(vuln, dict):
                    continue
                dbs = vuln.get("database_specific")
                if not isinstance(dbs, dict):
                    continue
                sev = dbs.get("severity")
                if isinstance(sev, str) and sev.upper() == "CRITICAL":
                    count += 1
    return {"deps_critical_count": count}


def parse_gitleaks_metrics(stdout: str) -> dict[str, Any]:
    """Parse gitleaks JSON output and count secret findings.

    Gitleaks emits a JSON array of finding objects on stdout when invoked
    with ``--report-format=json``. The current security collector uses
    ``gitleaks detect --no-banner`` which doesn't request JSON, so the
    parser tolerates non-JSON input and returns ``{}``.
    """
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, list):
        return {}
    return {"secrets_count": len(payload)}
