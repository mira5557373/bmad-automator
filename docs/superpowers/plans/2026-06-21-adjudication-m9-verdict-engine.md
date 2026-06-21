# Adjudication M9: Verdict Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure verdict engine that takes collected evidence + product profile + risk priority and produces a deterministic, auditable gate file with per-category verdicts and an aggregated overall verdict. This is the Tier 3 Adjudicator from §6 — "LLM generates; code decides."

**Architecture:** Two new modules fill the gap between "evidence collected" (m4-m7) and "gate file emitted":
- `category_rules.py` (~280 LOC) — per-category rule functions that interpret evidence metrics against profile thresholds, plus evidence status helpers (`worst_evidence_status`, `_STATUS_SEVERITY`). Each rule returns a `CategoryResult` dict with `{verdict, required, actual, rationale}`.
- `verdict_engine.py` (~280 LOC) — the main `adjudicate()` orchestration function: groups evidence by category → applies category rules → handles NA/fail-closed/LLM-confidence → aggregates overall → validates waivers → builds complete gate file. Plus `evaluate_gate()` end-to-end entry point.
- `gate_audit.py` extended (~+30 LOC) — `GateDecisionAudit` and `GateRenderedAudit` events.

**Dependency graph:** `gate_schema.py` ← `gate_rules.py` ← `category_rules.py` ← `verdict_engine.py` (strictly unidirectional — `category_rules.py` NEVER imports from `verdict_engine.py` to avoid circular imports). Existing modules (`evidence_io.py`, `product_profile.py`, `gate_audit.py`, `collector_runner.py`) consumed but NOT modified (except `gate_audit.py` for new events).

**Tech Stack:** Python 3.11+, stdlib only; existing `gate_schema`, `gate_rules`, `evidence_io`, `product_profile` from m1-m7; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT modify existing m1-m7 modules** except `gate_audit.py` (new audit events only).
- **500-LOC soft limit per Python module.** `category_rules.py` target ~250 LOC; `verdict_engine.py` target ~300 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/category_rules.py` — per-category rule functions (~250 LOC)
- `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py` — verdict engine orchestration (~300 LOC)
- `tests/test_category_rules.py` — unit tests for category rules (~350 LOC)
- `tests/test_verdict_engine.py` — unit tests for verdict engine (~400 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — add `GateDecisionAudit`, `GateRenderedAudit` (~+30 LOC)
- `tests/test_gate_audit.py` — add tests for new audit events (~+40 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/product_profile.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`.

---

### Task 1: Coverage Threshold Verdict Helper

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Create: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: None (standalone pure function).
- Produces: `coverage_verdict(actual_pct: float, target_pct: int, priority: str) -> str` — returns `"PASS"` if actual >= target, `"CONCERNS"` if P1 and actual >= 80% but < target, `"FAIL"` otherwise. Implements §12 TEA thresholds.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_category_rules.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.category_rules import coverage_verdict


class CoverageVerdictTests(unittest.TestCase):
    def test_p0_100_passes(self) -> None:
        self.assertEqual(coverage_verdict(100.0, 100, "P0"), "PASS")

    def test_p0_below_100_fails(self) -> None:
        self.assertEqual(coverage_verdict(99.9, 100, "P0"), "FAIL")

    def test_p1_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(90.0, 90, "P1"), "PASS")

    def test_p1_above_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(95.0, 90, "P1"), "PASS")

    def test_p1_between_80_and_target_concerns(self) -> None:
        self.assertEqual(coverage_verdict(85.0, 90, "P1"), "CONCERNS")

    def test_p1_at_80_concerns(self) -> None:
        self.assertEqual(coverage_verdict(80.0, 90, "P1"), "CONCERNS")

    def test_p1_below_80_fails(self) -> None:
        self.assertEqual(coverage_verdict(79.9, 90, "P1"), "FAIL")

    def test_p2_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(50.0, 50, "P2"), "PASS")

    def test_p2_below_target_fails(self) -> None:
        self.assertEqual(coverage_verdict(49.0, 50, "P2"), "FAIL")

    def test_p3_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(20.0, 20, "P3"), "PASS")

    def test_p3_below_target_fails(self) -> None:
        self.assertEqual(coverage_verdict(10.0, 20, "P3"), "FAIL")

    def test_zero_target_always_passes(self) -> None:
        self.assertEqual(coverage_verdict(0.0, 0, "P3"), "PASS")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::CoverageVerdictTests -v`
Expected: ModuleNotFoundError — `category_rules` not found.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/category_rules.py`:

```python
"""Per-category rule functions for verdict engine (section 6.2, section 12).

Each rule interprets evidence metrics against profile thresholds and
returns a CategoryResult dict: {verdict, required, actual, rationale}.
Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any

_P1_CONCERNS_FLOOR = 80


def coverage_verdict(actual_pct: float, target_pct: int, priority: str) -> str:
    """section 12 TEA coverage thresholds.

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add coverage threshold verdict helper per TEA section 12" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Risk-to-Requirements Mapping

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: `product_profile.required_for_priority` (from m1, for matrix lookup).
- Produces: `risk_to_requirements(priority: str, profile: dict[str, Any]) -> dict[str, Any]` — returns `{coverage_pct: int, levels: list[str], priority: str}`. Falls back to P1 for unknown/missing priority.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import risk_to_requirements


class RiskToRequirementsTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
            "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
            "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
    }

    def test_p0_returns_full_requirements(self) -> None:
        req = risk_to_requirements("P0", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])
        self.assertEqual(req["priority"], "P0")

    def test_p1_returns_p1_requirements(self) -> None:
        req = risk_to_requirements("P1", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 90)
        self.assertIn("api", req["levels"])

    def test_p3_returns_minimal_requirements(self) -> None:
        req = risk_to_requirements("P3", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 20)
        self.assertEqual(req["levels"], ["smoke"])

    def test_unknown_priority_defaults_to_p1(self) -> None:
        req = risk_to_requirements("P99", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 90)
        self.assertEqual(req["priority"], "P1")

    def test_empty_priority_defaults_to_p1(self) -> None:
        req = risk_to_requirements("", self.PROFILE)
        self.assertEqual(req["priority"], "P1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::RiskToRequirementsTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py`:

```python
from .product_profile import VALID_PRIORITIES, required_for_priority

_DEFAULT_PRIORITY = "P1"


def risk_to_requirements(
    priority: str, profile: dict[str, Any],
) -> dict[str, Any]:
    """Map risk priority to coverage/level requirements from profile.matrix."""
    if priority not in VALID_PRIORITIES:
        priority = _DEFAULT_PRIORITY
    req = required_for_priority(profile, priority)
    req["priority"] = priority
    return req
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add risk-to-requirements mapping from profile matrix" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Evidence Status Helpers + Evidence Grouping

> **GAP FIX (circular import prevention):** `worst_evidence_status` and `_STATUS_SEVERITY` live in `category_rules.py` (not `verdict_engine.py`) because category rule functions consume them. This keeps the import graph strictly unidirectional: `category_rules.py` ← `verdict_engine.py`. Placing them in `verdict_engine.py` would create a circular import when Task 9 adds `from .category_rules import apply_category_rule`.

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Create: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `gate_schema.make_evidence_record` (for test fixtures).
- Produces:
  - In `category_rules.py`:
    - `worst_evidence_status(records: list[dict]) -> str` — returns the worst status among records: `error > timeout > violation > ok`. Empty list → `"error"` (fail-closed).
  - In `verdict_engine.py`:
    - `group_evidence_by_category(evidence: list[dict]) -> dict[str, list[dict]]` — groups evidence records by `category` field.
    - `has_llm_low_confidence(records: list[dict]) -> bool` — True if any non-deterministic record has confidence < 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import worst_evidence_status
from story_automator.core.gate_schema import make_evidence_record


class WorstEvidenceStatusTests(unittest.TestCase):
    def test_all_ok(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_evidence_record(collector="b", tool="t", category="x", status="ok"),
        ]
        self.assertEqual(worst_evidence_status(records), "ok")

    def test_violation_worse_than_ok(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_evidence_record(collector="b", tool="t", category="x", status="violation"),
        ]
        self.assertEqual(worst_evidence_status(records), "violation")

    def test_timeout_worse_than_violation(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="violation"),
            make_evidence_record(collector="b", tool="t", category="x", status="timeout",
                                 findings=["TIMEOUT: t exceeded 10s"]),
        ]
        self.assertEqual(worst_evidence_status(records), "timeout")

    def test_error_worst(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="timeout",
                                 findings=["TIMEOUT"]),
            make_evidence_record(collector="b", tool="t", category="x", status="error",
                                 findings=["crash"]),
        ]
        self.assertEqual(worst_evidence_status(records), "error")

    def test_empty_list_fail_closed(self) -> None:
        self.assertEqual(worst_evidence_status([]), "error")
```

Create `tests/test_verdict_engine.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.gate_schema import (
    make_evidence_record,
    make_llm_evidence_record,
)
from story_automator.core.verdict_engine import (
    group_evidence_by_category,
    has_llm_low_confidence,
)


class GroupEvidenceByCategoryTests(unittest.TestCase):
    def test_groups_by_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="correctness", status="ok"),
            make_evidence_record(collector="b", tool="t", category="security", status="ok"),
            make_evidence_record(collector="c", tool="t", category="correctness", status="violation"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertEqual(len(grouped["correctness"]), 2)
        self.assertEqual(len(grouped["security"]), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(group_evidence_by_category([]), {})

    def test_single_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="static", status="ok"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertIn("static", grouped)
        self.assertEqual(len(grouped["static"]), 1)


class HasLlmLowConfidenceTests(unittest.TestCase):
    def test_no_llm_evidence(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_high_confidence_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=8, rationale="good",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_low_confidence_detected(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))

    def test_boundary_5_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=5, rationale="ok",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_mixed_deterministic_and_llm(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=4, rationale="weak",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::WorstEvidenceStatusTests tests/test_verdict_engine.py -v`
Expected: ImportError for both.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/category_rules.py`:

```python
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
```

Create `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`:

```python
"""Verdict engine — pure adjudication pipeline (section 6).

Takes collected evidence + profile + risk priority and produces
a deterministic gate file. LLM generates; code decides.

Flow: evidence bundle -> group by category -> per-category rules ->
      aggregate -> waivers -> gate file.
"""
from __future__ import annotations

from typing import Any


def group_evidence_by_category(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group evidence records by their category field."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in evidence:
        cat = record.get("category", "unknown")
        grouped.setdefault(cat, []).append(record)
    return grouped


def has_llm_low_confidence(records: list[dict[str, Any]]) -> bool:
    """True if any non-deterministic evidence has confidence < 5."""
    for record in records:
        if not record.get("deterministic", True):
            confidence = record.get("confidence")
            if isinstance(confidence, int) and confidence < 5:
                return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add evidence grouping and status aggregation helpers" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Correctness Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: `coverage_verdict` (from Task 1), `worst_evidence_status` (from Task 3, same module).
- Produces: `correctness_rule(evidence: list[dict], profile: dict, required: dict) -> dict` — returns `{verdict: str, required: dict, actual: dict, rationale: str}`. Checks: (1) worst evidence status fail-closed; (2) coverage >= risk-required via `coverage_verdict`; (3) 0 regressions. Coverage read from evidence `metrics.coverage_pct`; regressions from `metrics.regressions`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import correctness_rule
from story_automator.core.gate_schema import make_evidence_record


class CorrectnessRuleTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
            "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
    }
    REQUIRED_P1 = {"coverage_pct": 90, "levels": ["unit", "integration", "api"], "priority": "P1"}

    def test_all_green_above_threshold_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "PASS")

    def test_coverage_below_target_above_80_concerns_for_p1(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 85, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "CONCERNS")

    def test_coverage_below_80_fails_for_p1(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 70, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_regressions_cause_fail(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 2},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_status_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="error", findings=["crash"],
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_timeout_status_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="timeout", findings=["TIMEOUT: pytest exceeded 1800s"],
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_no_coverage_metric_uses_zero(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_result_has_required_and_actual(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertIn("required", result)
        self.assertIn("actual", result)
        self.assertIn("rationale", result)
        self.assertEqual(result["actual"]["coverage_pct"], 95)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::CorrectnessRuleTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py` (note: `worst_evidence_status` is already in this module from Task 3 — no cross-module import needed):

```python
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
    """section 6.2: all tiers green, 0 regressions, coverage >= risk-required."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add correctness category rule with coverage thresholds" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Security Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: `worst_evidence_status` (from Task 3, same module), `product_profile.rule_for` (from m1).
- Produces: `security_rule(evidence: list[dict], profile: dict, required: dict) -> dict` — checks evidence metrics against `profile.rules.security`: `sast_high_count <= sast_max_high`, `deps_critical_count <= deps_max_critical`, `secrets_count <= secrets_max`. Any threshold exceeded → FAIL.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import security_rule


class SecurityRuleTests(unittest.TestCase):
    PROFILE = {
        "rules": {
            "security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
        },
    }
    REQ = {"priority": "P1"}

    def test_clean_scan_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="ok", metrics={"sast_high_count": 0, "deps_critical_count": 0, "secrets_count": 0},
        )]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_sast_high_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="violation", metrics={"sast_high_count": 2},
            findings=["SQL injection", "XSS"],
        )]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_deps_critical_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="trivy", category="security",
            status="violation", metrics={"deps_critical_count": 1},
            findings=["CVE-2026-0001"],
        )]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_secrets_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="gitleaks", category="security",
            status="violation", metrics={"secrets_count": 1},
            findings=["API key in config"],
        )]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_status_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="error", findings=["semgrep crashed"],
        )]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_no_rules_in_profile_uses_zero_defaults(self) -> None:
        evidence = [make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="ok", metrics={"sast_high_count": 0},
        )]
        result = security_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_multiple_evidence_worst_wins(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="semgrep", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
            make_evidence_record(collector="b", tool="trivy", category="security",
                                 status="violation", metrics={"deps_critical_count": 3},
                                 findings=["CVE-1", "CVE-2", "CVE-3"]),
        ]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::SecurityRuleTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py`:

```python
from .product_profile import rule_for


def security_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """section 6.2: SAST 0 high+, deps 0 critical-unwaived, 0 secrets."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add security category rule with threshold checking" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Static Analysis Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: `worst_evidence_status`, `_aggregate_metrics`, `_make_category_result`.
- Produces: `static_rule(evidence: list[dict], profile: dict, required: dict) -> dict` — checks evidence status; any violation/error/timeout → FAIL. All ok → PASS. §6.2: "static-analysis + type-checking: tsc=0, mypy=0, ruff/Biome=0, deadcode <= budget."

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import static_rule


class StaticRuleTests(unittest.TestCase):
    REQ = {"priority": "P1"}

    def test_clean_analysis_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="linter", tool="ruff", category="static",
            status="ok", metrics={"errors": 0, "warnings": 0},
        )]
        result = static_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_violation_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="linter", tool="mypy", category="static",
            status="violation", findings=["type error in foo.py"],
        )]
        result = static_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="linter", tool="ruff", category="static",
            status="error", findings=["ruff crashed"],
        )]
        result = static_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_multiple_tools_worst_wins(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="ruff", category="static", status="ok"),
            make_evidence_record(collector="b", tool="mypy", category="static",
                                 status="violation", findings=["type error"]),
        ]
        result = static_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_all_ok_multiple_tools_passes(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="ruff", category="static", status="ok"),
            make_evidence_record(collector="b", tool="mypy", category="static", status="ok"),
            make_evidence_record(collector="c", tool="biome", category="static", status="ok"),
        ]
        result = static_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::StaticRuleTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py`:

```python
def static_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """section 6.2: tsc=0, mypy=0, ruff/Biome=0, deadcode <= budget."""
    return _status_based_rule("static", evidence)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add static analysis category rule" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: License Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: `worst_evidence_status`, `_aggregate_metrics`, `_make_category_result`, `rule_for`.
- Produces: `license_rule(evidence: list[dict], profile: dict, required: dict) -> dict` — checks `metrics.forbidden_count` against 0 and `metrics.boundary_violations` against 0 per `profile.rules.license`. §6.2: "0 forbidden licenses + boundary-aware."

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import license_rule


class LicenseRuleTests(unittest.TestCase):
    PROFILE = {
        "rules": {
            "license": {"forbidden": ["BSL", "SSPL"], "boundary": {"AGPL-3.0": ["odoo-pod"]}},
        },
    }
    REQ = {"priority": "P1"}

    def test_clean_license_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="lic", tool="syft", category="license",
            status="ok", metrics={"forbidden_count": 0, "boundary_violations": 0},
        )]
        result = license_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_forbidden_license_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="lic", tool="syft", category="license",
            status="violation", metrics={"forbidden_count": 1},
            findings=["BSL-1.1 in dependency X"],
        )]
        result = license_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_boundary_violation_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="lic", tool="syft", category="license",
            status="violation", metrics={"forbidden_count": 0, "boundary_violations": 1},
            findings=["AGPL-3.0 outside odoo-pod"],
        )]
        result = license_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="lic", tool="syft", category="license",
            status="error", findings=["syft crashed"],
        )]
        result = license_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::LicenseRuleTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py`:

```python
def license_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """section 6.2: 0 forbidden licenses + boundary-aware (AGPL only in Odoo pod)."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add license category rule with boundary-aware checking" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Generic Fallback Rule + Rule Dispatch

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: All rule functions from Tasks 4-7, `_status_based_rule`.
- Produces:
  - `generic_rule(evidence: list[dict], profile: dict, required: dict) -> dict` — status-based verdict for categories without specific rules (docs, process, compliance, supply_chain, api_compat, migrations, performance, accessibility, observability, traceability, test_quality, mutation, invariants, agentic).
  - `CATEGORY_RULES: dict[str, Callable]` — maps category name to rule function. Unmapped categories fall through to `generic_rule`.
  - `apply_category_rule(category: str, evidence: list[dict], profile: dict, required: dict) -> dict` — dispatches to the right rule function.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_category_rules.py`:

```python
from story_automator.core.category_rules import (
    apply_category_rule,
    generic_rule,
    CATEGORY_RULES,
)


class GenericRuleTests(unittest.TestCase):
    REQ = {"priority": "P1"}

    def test_ok_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="docs", status="ok",
        )]
        result = generic_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_violation_fails(self) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="docs",
            status="violation", findings=["missing runbook"],
        )]
        result = generic_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="process",
            status="error", findings=["tool crashed"],
        )]
        result = generic_rule(evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")


class CategoryRulesDispatchTests(unittest.TestCase):
    REQ = {"coverage_pct": 90, "levels": ["unit"], "priority": "P1"}

    def test_correctness_dispatches_to_correctness_rule(self) -> None:
        self.assertIn("correctness", CATEGORY_RULES)

    def test_security_dispatches_to_security_rule(self) -> None:
        self.assertIn("security", CATEGORY_RULES)

    def test_unknown_category_uses_generic(self) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="unknown_cat", status="ok",
        )]
        result = apply_category_rule("unknown_cat", evidence, {}, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_dispatch_returns_correct_shape(self) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = apply_category_rule("correctness", evidence, {"matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        }}, self.REQ)
        self.assertIn("verdict", result)
        self.assertIn("required", result)
        self.assertIn("actual", result)
        self.assertIn("rationale", result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py::GenericRuleTests tests/test_category_rules.py::CategoryRulesDispatchTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `category_rules.py`:

```python
from typing import Callable

CategoryRuleFn = Callable[[list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]]


def generic_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Fallback rule: verdict follows worst evidence status."""
    return _status_based_rule("category", evidence)


CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
}


def apply_category_rule(
    category: str,
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch to the right rule function for a category."""
    rule_fn = CATEGORY_RULES.get(category, generic_rule)
    return rule_fn(evidence, profile, required)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_category_rules.py
git commit -m "feat(gate): add generic fallback rule and category dispatch" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Compute Single Category Verdict

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `category_rules.apply_category_rule` (from Task 8), `has_llm_low_confidence` (from Task 3, same module).
- Produces: `compute_category_verdict(category: str, evidence: list[dict], profile: dict, required: dict) -> dict[str, Any]` — applies the category rule, then checks for LLM low confidence (downgrades PASS to CONCERNS). Returns `{verdict: str, required: dict, actual: dict, rationale: str, evidence_refs: list[str]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
from story_automator.core.verdict_engine import compute_category_verdict


class ComputeCategoryVerdictTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
    }
    REQ = {"coverage_pct": 90, "levels": [], "priority": "P1"}

    def test_pass_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="violation",
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_llm_low_confidence_downgrades_pass_to_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain about edge cases",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "CONCERNS")
        self.assertIn("confidence", result["rationale"].lower())

    def test_llm_low_confidence_does_not_upgrade_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="violation"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_result_includes_evidence_refs(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertIn("evidence_refs", result)
        self.assertIsInstance(result["evidence_refs"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::ComputeCategoryVerdictTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from .category_rules import apply_category_rule
from .evidence_io import evidence_filename


def compute_category_verdict(
    category: str,
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Compute verdict for a single category.

    Applies category rule, then checks LLM confidence.
    FAIL from rule is never upgraded; PASS may downgrade to CONCERNS.
    """
    result = apply_category_rule(category, evidence, profile, required)
    refs = [evidence_filename(r) for r in evidence]
    result["evidence_refs"] = refs

    if result["verdict"] == "PASS" and has_llm_low_confidence(evidence):
        result["verdict"] = "CONCERNS"
        result["rationale"] = "low LLM confidence (<5) on evidence; " + result.get("rationale", "")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add single category verdict computation with LLM confidence gate" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Compute All Category Verdicts with NA Handling

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `compute_category_verdict` (from Task 9), `group_evidence_by_category` (from Task 3), `gate_rules.verdict_na` (from m2), `category_rules.risk_to_requirements` (from Task 2).
- Produces: `compute_all_verdicts(evidence_bundle: list[dict], profile: dict, priority: str) -> dict[str, dict]` — returns a dict mapping category name to CategoryVerdict. Categories in `profile.categories_na` get `verdict_na()`. Categories with evidence get `compute_category_verdict()`. Categories listed in `profile.categories` but missing evidence get fail-closed verdict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
from story_automator.core.verdict_engine import compute_all_verdicts


class ComputeAllVerdictsTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {
            "code": ["correctness", "security", "static"],
            "system": [],
        },
        "categories_na": ["accessibility", "performance"],
    }

    def test_na_categories_get_na_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["accessibility"]["verdict"], "NA")
        self.assertEqual(verdicts["performance"]["verdict"], "NA")
        self.assertIn("profile-declared", verdicts["accessibility"]["rationale"])

    def test_na_verdict_has_consistent_shape(self) -> None:
        """GAP FIX: verdict_na() returns 2 keys but other verdicts return 5.
        compute_all_verdicts must normalize NA to the full 5-key shape."""
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        na_verdict = verdicts["accessibility"]
        self.assertIn("required", na_verdict)
        self.assertIn("actual", na_verdict)
        self.assertIn("evidence_refs", na_verdict)
        self.assertEqual(na_verdict["required"], {})
        self.assertEqual(na_verdict["actual"], {})
        self.assertEqual(na_verdict["evidence_refs"], [])

    def test_evidence_categories_get_computed_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["correctness"]["verdict"], "PASS")
        self.assertEqual(verdicts["security"]["verdict"], "PASS")

    def test_empty_evidence_for_active_category_fails_closed(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": ["correctness", "security"], "system": []}
        profile["categories_na"] = []
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertEqual(verdicts["security"]["verdict"], "FAIL")

    def test_returns_all_active_plus_na_categories(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok"),
            make_evidence_record(collector="c", tool="t", category="static",
                                 status="ok"),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertIn("correctness", verdicts)
        self.assertIn("security", verdicts)
        self.assertIn("static", verdicts)
        self.assertIn("accessibility", verdicts)
        self.assertIn("performance", verdicts)

    def test_extra_evidence_category_not_in_profile_still_evaluated(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="docs",
                                 status="ok"),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": [], "system": []}
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertIn("docs", verdicts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::ComputeAllVerdictsTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from .category_rules import risk_to_requirements
from .gate_rules import verdict_na


def compute_all_verdicts(
    evidence_bundle: list[dict[str, Any]],
    profile: dict[str, Any],
    priority: str,
) -> dict[str, dict[str, Any]]:
    """Compute verdicts for all categories.

    Categories in categories_na -> NA.
    Categories with evidence -> computed verdict.
    Active categories without evidence -> fail-closed.
    """
    required = risk_to_requirements(priority, profile)
    grouped = group_evidence_by_category(evidence_bundle)
    na_cats = set(profile.get("categories_na") or [])
    active_cats: set[str] = set()
    for tier_cats in (profile.get("categories") or {}).values():
        if isinstance(tier_cats, list):
            active_cats.update(tier_cats)
    all_cats = active_cats | set(grouped.keys()) | na_cats

    verdicts: dict[str, dict[str, Any]] = {}
    for cat in sorted(all_cats):
        if cat in na_cats:
            na_result = verdict_na()
            na_result["required"] = {}
            na_result["actual"] = {}
            na_result["evidence_refs"] = []
            verdicts[cat] = na_result
            continue
        cat_evidence = grouped.get(cat, [])
        if not cat_evidence and cat in active_cats:
            verdicts[cat] = {
                "verdict": "FAIL",
                "required": {},
                "actual": {"status": "missing"},
                "rationale": f"no evidence collected for active category {cat}",
                "evidence_refs": [],
            }
            continue
        if cat_evidence:
            verdicts[cat] = compute_category_verdict(cat, cat_evidence, profile, required)

    return verdicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add compute_all_verdicts with NA handling and fail-closed" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Core adjudicate() Function

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `compute_all_verdicts` (from Task 10), `gate_rules.aggregate_verdicts` (from m2), `evidence_io.compute_evidence_bundle_hash` (from m2), `product_profile.compute_profile_hash` (from m1).
- Produces: `adjudicate(evidence_bundle: list[dict], profile: dict, *, priority: str = "P1", has_unmitigated_risk_9: bool = False) -> dict[str, Any]` — returns `{categories: dict, overall: str, evidence_bundle_hash: str, profile_hash: str}`. §6.3 aggregation: any FAIL → FAIL, any CONCERNS → CONCERNS, else PASS. Unmitigated risk-9 → FAIL.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
from story_automator.core.verdict_engine import adjudicate


class AdjudicateTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def test_all_pass_overall_pass(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(result["categories"]["security"]["verdict"], "PASS")

    def test_any_fail_overall_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 3},
                                 findings=["vuln1", "vuln2", "vuln3"]),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")

    def test_concerns_without_fail_overall_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 85, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "CONCERNS")

    def test_unmitigated_risk_9_forces_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 100, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1",
                           has_unmitigated_risk_9=True)
        self.assertEqual(result["overall"], "FAIL")

    def test_result_includes_evidence_bundle_hash(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertIn("evidence_bundle_hash", result)
        self.assertEqual(len(result["evidence_bundle_hash"]), 16)

    def test_result_includes_profile_hash(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertIn("profile_hash", result)
        self.assertTrue(len(result["profile_hash"]) > 0)

    def test_empty_evidence_all_active_fail(self) -> None:
        result = adjudicate([], self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::AdjudicateTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from .evidence_io import compute_evidence_bundle_hash
from .gate_rules import aggregate_verdicts
from .product_profile import compute_profile_hash


def adjudicate(
    evidence_bundle: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    priority: str = "P1",
    has_unmitigated_risk_9: bool = False,
) -> dict[str, Any]:
    """section 6.3: pure verdict engine.

    evidence -> per-category verdicts -> aggregate -> result.
    Deterministic: same inputs -> same output.
    """
    categories = compute_all_verdicts(evidence_bundle, profile, priority)
    flat_verdicts = {cat: info["verdict"] for cat, info in categories.items()}
    overall = aggregate_verdicts(flat_verdicts, has_unmitigated_risk_9=has_unmitigated_risk_9)

    return {
        "categories": categories,
        "overall": overall,
        "evidence_bundle_hash": compute_evidence_bundle_hash(evidence_bundle),
        "profile_hash": compute_profile_hash(profile),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add core adjudicate() verdict engine with section 6.3 aggregation" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Waiver Application

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `gate_rules.validate_waiver_for_gate` (from m2), `gate_rules.is_waiver_expired` (from m2).
- Produces: `apply_waivers(adjudication: dict, waivers: list[dict], gate_file_stub: dict, *, now: datetime | None = None) -> tuple[str, list[dict], str]` — validates each waiver against the gate file stub. Returns `(overall_verdict, valid_waivers, rationale)`. If all failing categories are covered by valid, unexpired waivers → overall becomes `"WAIVED"`. §6.4: re-checks `expires_at` on every gate-file reuse.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
from datetime import datetime, timezone
from story_automator.core.gate_schema import make_waiver
from story_automator.core.verdict_engine import apply_waivers


class ApplyWaiversTests(unittest.TestCase):
    def _failing_adjudication(self) -> dict:
        return {
            "categories": {
                "security": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "vuln"},
                "correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"},
            },
            "overall": "FAIL",
        }

    def _gate_stub(self) -> dict:
        return {
            "categories": {
                "security": {"verdict": "FAIL"},
                "correctness": {"verdict": "PASS"},
            },
            "profile": {"id": "test", "version": 1, "hash": "aabbccdd"},
        }

    def test_valid_waiver_produces_waived(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="false positive",
            profile_hash="aabbccdd",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "WAIVED")
        self.assertEqual(len(valid), 1)

    def test_expired_waiver_keeps_fail(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-01T00:00:00Z", expires_at="2026-06-15T00:00:00Z",
            failing_categories=["security"], reason="expired",
            profile_hash="aabbccdd",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)
        self.assertIn("expired", rationale)

    def test_no_waivers_keeps_original(self) -> None:
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [], self._gate_stub(),
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)

    def test_pass_verdict_ignores_waivers(self) -> None:
        adj = {"categories": {"correctness": {"verdict": "PASS"}}, "overall": "PASS"}
        stub = {"categories": {"correctness": {"verdict": "PASS"}},
                "profile": {"hash": "aabb"}}
        overall, valid, rationale = apply_waivers(adj, [], stub)
        self.assertEqual(overall, "PASS")

    def test_profile_hash_mismatch_rejects_waiver(self) -> None:
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="reason",
            profile_hash="wrong_hash",
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        overall, valid, rationale = apply_waivers(
            self._failing_adjudication(), [waiver], self._gate_stub(), now=now,
        )
        self.assertEqual(overall, "FAIL")
        self.assertEqual(len(valid), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::ApplyWaiversTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from datetime import datetime
from .gate_rules import validate_waiver_for_gate


def apply_waivers(
    adjudication: dict[str, Any],
    waivers: list[dict[str, Any]],
    gate_file_stub: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """section 6.4: validate waivers and apply if valid.

    Returns (overall_verdict, valid_waivers, rationale).
    WAIVED only if original overall is FAIL and all failing
    categories are covered by valid, unexpired waivers.
    """
    original_overall = adjudication.get("overall", "FAIL")
    if original_overall == "PASS":
        return "PASS", [], ""
    if not waivers:
        return original_overall, [], "no waivers provided"

    valid_waivers: list[dict[str, Any]] = []
    rejection_reasons: list[str] = []
    for waiver in waivers:
        ok, reason = validate_waiver_for_gate(waiver, gate_file_stub, now=now)
        if ok:
            valid_waivers.append(waiver)
        else:
            rejection_reasons.append(f"waiver {waiver.get('waiver_id', '?')}: {reason}")

    if valid_waivers and original_overall == "FAIL":
        return "WAIVED", valid_waivers, "all failing categories waived"

    rationale = "; ".join(rejection_reasons) if rejection_reasons else "waivers not applicable"
    return original_overall, valid_waivers, rationale
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add waiver validation and application in verdict engine" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Build Gate File from Adjudication

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `gate_schema.make_gate_file` (from m2), `adjudicate` (from Task 11), `apply_waivers` (from Task 12).
- Produces: `build_gate_file(adjudication: dict, *, gate_id: str, target: dict[str, str], commit_sha: str, profile: dict, factory_version: str, waivers: list[dict] | None = None, scanner_data_snapshot: str = "", risk_profile_ref: str = "", now: datetime | None = None) -> dict[str, Any]` — constructs a complete, validated gate file dict from the adjudication result. §6.4 shape.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
from story_automator.core.verdict_engine import build_gate_file
from story_automator.core.gate_schema import GATE_SCHEMA_VERSION


class BuildGateFileTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def _evidence(self) -> list:
        return [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]

    def test_pass_gate_file(self) -> None:
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g1", target={"kind": "story", "id": "E1.S1"},
            commit_sha="abc123", profile=self.PROFILE,
            factory_version="0.1.0",
        )
        self.assertEqual(gate["gate_id"], "g1")
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["schema_version"], GATE_SCHEMA_VERSION)
        self.assertEqual(gate["commit_sha"], "abc123")
        self.assertIn("hash", gate["profile"])

    def test_fail_gate_file(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="violation"),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok"),
        ]
        adj = adjudicate(evidence, self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g2", target={"kind": "story", "id": "E1.S2"},
            commit_sha="def456", profile=self.PROFILE,
            factory_version="0.1.0",
        )
        self.assertEqual(gate["overall"], "FAIL")

    def test_waived_gate_file(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 1},
                                 findings=["vuln"]),
        ]
        adj = adjudicate(evidence, self.PROFILE, priority="P1")
        profile_hash = adj["profile_hash"]
        waiver = make_waiver(
            waiver_id="w1", operator_id="alice",
            issued_at="2026-06-20T00:00:00Z", expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"], reason="false positive",
            profile_hash=profile_hash,
        )
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        gate = build_gate_file(
            adj, gate_id="g3", target={"kind": "story", "id": "E1.S3"},
            commit_sha="ghi789", profile=self.PROFILE,
            factory_version="0.1.0", waivers=[waiver], now=now,
        )
        self.assertEqual(gate["overall"], "WAIVED")
        self.assertEqual(len(gate["waivers"]), 1)

    def test_gate_file_has_evidence_bundle_hash(self) -> None:
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g4", target={"kind": "story", "id": "E1.S4"},
            commit_sha="abc", profile=self.PROFILE, factory_version="0.1.0",
        )
        self.assertEqual(len(gate["evidence_bundle_hash"]), 16)

    def test_gate_file_validates(self) -> None:
        from story_automator.core.gate_schema import validate_gate_file
        adj = adjudicate(self._evidence(), self.PROFILE, priority="P1")
        gate = build_gate_file(
            adj, gate_id="g5", target={"kind": "story", "id": "E1.S5"},
            commit_sha="abc", profile=self.PROFILE, factory_version="0.1.0",
        )
        validate_gate_file(gate)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::BuildGateFileTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from .gate_schema import make_gate_file as _make_gate_file


def build_gate_file(
    adjudication: dict[str, Any],
    *,
    gate_id: str,
    target: dict[str, str],
    commit_sha: str,
    profile: dict[str, Any],
    factory_version: str,
    waivers: list[dict[str, Any]] | None = None,
    scanner_data_snapshot: str = "",
    risk_profile_ref: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a complete gate file from adjudication results."""
    profile_hash = adjudication.get("profile_hash", compute_profile_hash(profile))
    categories = adjudication["categories"]
    overall = adjudication["overall"]

    gate_stub = {
        "categories": categories,
        "profile": {
            "id": profile.get("id", ""),
            "version": profile.get("version", 1),
            "hash": profile_hash,
        },
    }
    valid_waivers: list[dict[str, Any]] = []
    if waivers and overall in ("FAIL", "CONCERNS"):
        overall, valid_waivers, _ = apply_waivers(
            adjudication, waivers, gate_stub, now=now,
        )

    return _make_gate_file(
        gate_id=gate_id,
        target=target,
        commit_sha=commit_sha,
        scanner_data_snapshot=scanner_data_snapshot,
        profile={
            "id": profile.get("id", ""),
            "version": profile.get("version", 1),
            "hash": profile_hash,
        },
        factory_version=factory_version,
        risk_profile_ref=risk_profile_ref,
        categories=categories,
        overall=overall,
        waivers=valid_waivers,
        evidence_bundle_hash=adjudication.get("evidence_bundle_hash", ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add build_gate_file from adjudication results" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Gate Decision and Rendered Audit Events

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing `audit_for_policy`, `emit_gate_audit` pattern from gate_audit.py.
- Produces:
  - `GateDecisionAudit(gate_id, overall, commit_sha, profile_hash, categories_summary, tier)` — audit event emitted when the adjudicator produces a verdict.
  - `GateRenderedAudit(gate_id, gate_file_path, evidence_bundle_hash)` — audit event emitted when the gate file is persisted to disk.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_gate_audit.py` first. Then append:

```python
from story_automator.core.gate_audit import GateDecisionAudit, GateRenderedAudit


class GateDecisionAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateDecisionAudit(
            gate_id="g1", overall="PASS", commit_sha="abc",
            profile_hash="aabb", categories_summary="correctness:PASS,security:PASS",
        )
        self.assertEqual(event.event_name, "GateDecision")

    def test_to_dict_has_all_fields(self) -> None:
        event = GateDecisionAudit(
            gate_id="g1", overall="FAIL", commit_sha="abc",
            profile_hash="aabb", categories_summary="security:FAIL",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["overall"], "FAIL")
        self.assertEqual(d["commit_sha"], "abc")
        self.assertIn("categories_summary", d)


class GateRenderedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateRenderedAudit(
            gate_id="g1", gate_file_path="verdicts/g1.json",
            evidence_bundle_hash="1234567890abcdef",
        )
        self.assertEqual(event.event_name, "GateRendered")

    def test_to_dict_has_all_fields(self) -> None:
        event = GateRenderedAudit(
            gate_id="g1", gate_file_path="verdicts/g1.json",
            evidence_bundle_hash="abcd1234",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["gate_file_path"], "verdicts/g1.json")
        self.assertEqual(d["evidence_bundle_hash"], "abcd1234")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py::GateDecisionAuditTests tests/test_gate_audit.py::GateRenderedAuditTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_audit.py` (after `GateBoundaryViolation`, before `emit_gate_audit`):

```python
@dataclasses.dataclass(frozen=True)
class GateDecisionAudit:
    """Audit event: adjudicator produced a verdict."""
    event_name: str = dataclasses.field(default="GateDecision", init=False)
    gate_id: str = ""
    overall: str = ""
    commit_sha: str = ""
    profile_hash: str = ""
    categories_summary: str = ""
    tier: str = "code"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "overall": self.overall,
            "commit_sha": self.commit_sha,
            "profile_hash": self.profile_hash,
            "categories_summary": self.categories_summary,
            "tier": self.tier,
        }


@dataclasses.dataclass(frozen=True)
class GateRenderedAudit:
    """Audit event: gate file persisted to disk."""
    event_name: str = dataclasses.field(default="GateRendered", init=False)
    gate_id: str = ""
    gate_file_path: str = ""
    evidence_bundle_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_file_path": self.gate_file_path,
            "evidence_bundle_hash": self.evidence_bundle_hash,
        }
```

Update `__all__` to include `GateDecisionAudit`, `GateRenderedAudit`.

Update the type annotation on `emit_gate_audit`'s `event` parameter to include the new types.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add GateDecision and GateRendered audit events" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: evaluate_gate() End-to-End Entry Point

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `evidence_io.load_evidence_bundle`, `evidence_io.persist_gate_file` (from m2), `gate_audit.GateDecisionAudit`, `gate_audit.GateRenderedAudit`, `gate_audit.emit_gate_audit` (from Task 14), `adjudicate` (from Task 11), `build_gate_file` (from Task 13).
- Produces: `evaluate_gate(project_root: str | Path, gate_id: str, *, commit_sha: str, target: dict[str, str], profile: dict, factory_version: str, priority: str = "P1", has_unmitigated_risk_9: bool = False, waivers: list[dict] | None = None, audit_policy: dict | None = None, audit_path: Path | None = None) -> dict[str, Any]` — loads evidence, adjudicates, builds gate file, persists, emits audit events, returns the gate file dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verdict_engine.py`:

```python
import tempfile
from pathlib import Path
from story_automator.core.verdict_engine import evaluate_gate
from story_automator.core.evidence_io import persist_evidence_record


class EvaluateGateTests(unittest.TestCase):
    PROFILE = {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def _setup_evidence(self, tmp: str, gate_id: str) -> None:
        persist_evidence_record(tmp, gate_id, make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        ))
        persist_evidence_record(tmp, gate_id, make_evidence_record(
            collector="scanner", tool="semgrep", category="security",
            status="ok", metrics={"sast_high_count": 0},
        ))

    def test_end_to_end_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_evidence(tmp, "eval-g1")
            gate = evaluate_gate(
                tmp, "eval-g1", commit_sha="abc123",
                target={"kind": "story", "id": "E1.S1"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "PASS")
            self.assertEqual(gate["gate_id"], "eval-g1")

    def test_persists_gate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._setup_evidence(tmp, "eval-g2")
            evaluate_gate(
                tmp, "eval-g2", commit_sha="abc123",
                target={"kind": "story", "id": "E1.S2"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            gate_path = Path(tmp) / "_bmad" / "gate" / "verdicts" / "eval-g2.json"
            self.assertTrue(gate_path.is_file())

    def test_end_to_end_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "eval-g3", make_evidence_record(
                collector="runner", tool="pytest", category="correctness",
                status="violation",
            ))
            persist_evidence_record(tmp, "eval-g3", make_evidence_record(
                collector="scanner", tool="semgrep", category="security",
                status="ok",
            ))
            gate = evaluate_gate(
                tmp, "eval-g3", commit_sha="def456",
                target={"kind": "story", "id": "E1.S3"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "FAIL")

    def test_no_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = evaluate_gate(
                tmp, "eval-g4", commit_sha="xyz",
                target={"kind": "story", "id": "E1.S4"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            self.assertEqual(gate["overall"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py::EvaluateGateTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `verdict_engine.py`:

```python
from pathlib import Path

from .evidence_io import load_evidence_bundle, persist_gate_file
from .gate_audit import (
    GateDecisionAudit,
    GateRenderedAudit,
    emit_gate_audit,
)


def evaluate_gate(
    project_root: str | Path,
    gate_id: str,
    *,
    commit_sha: str,
    target: dict[str, str],
    profile: dict[str, Any],
    factory_version: str,
    priority: str = "P1",
    has_unmitigated_risk_9: bool = False,
    waivers: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """End-to-end gate evaluation entry point.

    Loads evidence -> adjudicates -> builds gate file -> persists -> audit.
    """
    evidence_bundle = load_evidence_bundle(project_root, gate_id)
    adj = adjudicate(
        evidence_bundle, profile,
        priority=priority, has_unmitigated_risk_9=has_unmitigated_risk_9,
    )
    gate_file = build_gate_file(
        adj, gate_id=gate_id, target=target, commit_sha=commit_sha,
        profile=profile, factory_version=factory_version, waivers=waivers,
    )

    gate_path = persist_gate_file(project_root, gate_file)

    if audit_policy is not None and audit_path is not None:
        cats_summary = ",".join(
            f"{c}:{v['verdict']}" for c, v in sorted(gate_file["categories"].items())
            if isinstance(v, dict) and "verdict" in v
        )
        emit_gate_audit(
            audit_policy, audit_path,
            GateDecisionAudit(
                gate_id=gate_id, overall=gate_file["overall"],
                commit_sha=commit_sha,
                profile_hash=gate_file["profile"].get("hash", ""),
                categories_summary=cats_summary,
            ),
        )
        emit_gate_audit(
            audit_policy, audit_path,
            GateRenderedAudit(
                gate_id=gate_id,
                gate_file_path=gate_path.as_posix() if gate_path else "",
                evidence_bundle_hash=gate_file.get("evidence_bundle_hash", ""),
            ),
        )

    return gate_file
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/verdict_engine.py tests/test_verdict_engine.py
git commit -m "feat(gate): add evaluate_gate end-to-end entry point with audit events" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 16: Edge Case and Determinism Integration Tests

**Files:**
- Modify: `tests/test_verdict_engine.py`
- Modify: `tests/test_category_rules.py`

**Interfaces:**
- Consumes: All functions from Tasks 1-15.
- Produces: No new code — validates edge cases and determinism guarantees.

- [ ] **Step 1: Write edge case tests**

Append to `tests/test_verdict_engine.py`:

```python
class VerdictEngineDeterminismTests(unittest.TestCase):
    PROFILE = {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness", "security"], "system": []},
        "categories_na": [],
    }

    def test_same_input_same_output(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        r1 = adjudicate(evidence, self.PROFILE, priority="P1")
        r2 = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(r1["overall"], r2["overall"])
        self.assertEqual(r1["evidence_bundle_hash"], r2["evidence_bundle_hash"])
        self.assertEqual(r1["profile_hash"], r2["profile_hash"])

    def test_evidence_order_does_not_affect_verdict(self) -> None:
        r1 = make_evidence_record(collector="a", tool="t", category="correctness",
                                  status="ok", metrics={"coverage_pct": 95, "regressions": 0})
        r2 = make_evidence_record(collector="b", tool="t", category="security",
                                  status="ok", metrics={"sast_high_count": 0})
        adj1 = adjudicate([r1, r2], self.PROFILE, priority="P1")
        adj2 = adjudicate([r2, r1], self.PROFILE, priority="P1")
        self.assertEqual(adj1["overall"], adj2["overall"])

    def test_all_na_categories_pass(self) -> None:
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": [], "system": []}
        profile["categories_na"] = ["correctness", "security"]
        result = adjudicate([], profile, priority="P1")
        self.assertEqual(result["overall"], "PASS")

    def test_mixed_na_and_active(self) -> None:
        profile = dict(self.PROFILE)
        profile["categories_na"] = ["security"]
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        result = adjudicate(evidence, profile, priority="P1")
        self.assertEqual(result["categories"]["security"]["verdict"], "NA")
        self.assertEqual(result["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(result["overall"], "PASS")

    def test_fail_takes_precedence_over_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="a", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 85, "regressions": 0}),
            make_evidence_record(collector="b", tool="t", category="security",
                                 status="violation", metrics={"sast_high_count": 1},
                                 findings=["vuln"]),
        ]
        result = adjudicate(evidence, self.PROFILE, priority="P1")
        self.assertEqual(result["overall"], "FAIL")
```

Append to `tests/test_category_rules.py`:

```python
class CategoryRulesEdgeCaseTests(unittest.TestCase):
    def test_coverage_verdict_float_precision(self) -> None:
        self.assertEqual(coverage_verdict(89.999, 90, "P1"), "CONCERNS")
        self.assertEqual(coverage_verdict(90.001, 90, "P1"), "PASS")

    def test_security_rule_all_metrics_zero(self) -> None:
        evidence = [make_evidence_record(
            collector="s", tool="t", category="security", status="ok",
            metrics={"sast_high_count": 0, "deps_critical_count": 0, "secrets_count": 0},
        )]
        result = security_rule(evidence, {"rules": {"security": {"sast_max_high": 0}}}, {})
        self.assertEqual(result["verdict"], "PASS")
```

- [ ] **Step 2: Run all tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_category_rules.py tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_verdict_engine.py tests/test_category_rules.py
git commit -m "test(gate): add edge case and determinism integration tests for verdict engine" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 17: End-to-End Round-Trip with Gate File Reuse Validation

**Files:**
- Modify: `tests/test_verdict_engine.py`

**Interfaces:**
- Consumes: `evaluate_gate`, `evidence_io.can_reuse_gate_file`, `evidence_io.load_gate_file`.
- Produces: No new code — validates the full pipeline: evidence → evaluate → persist → load → reuse check.

- [ ] **Step 1: Write round-trip tests**

Append to `tests/test_verdict_engine.py`:

```python
from story_automator.core.evidence_io import can_reuse_gate_file, load_gate_file
from story_automator.core.product_profile import compute_profile_hash


class GateRoundTripTests(unittest.TestCase):
    PROFILE = {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [],
    }

    def test_evaluate_then_reload_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g1", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g1", commit_sha="sha1",
                target={"kind": "story", "id": "E1.S1"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            loaded = load_gate_file(tmp, "rt-g1")
            self.assertEqual(loaded["overall"], gate["overall"])
            self.assertEqual(loaded["gate_id"], gate["gate_id"])

    def test_reuse_validation_passes_for_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g2", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g2", commit_sha="sha2",
                target={"kind": "story", "id": "E1.S2"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            ok, reason = can_reuse_gate_file(
                gate, commit_sha="sha2",
                profile_hash=compute_profile_hash(self.PROFILE),
                factory_version="0.1.0",
            )
            self.assertTrue(ok, reason)

    def test_reuse_fails_on_commit_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_evidence_record(tmp, "rt-g3", make_evidence_record(
                collector="a", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ))
            gate = evaluate_gate(
                tmp, "rt-g3", commit_sha="sha3",
                target={"kind": "story", "id": "E1.S3"},
                profile=self.PROFILE, factory_version="0.1.0",
            )
            ok, reason = can_reuse_gate_file(
                gate, commit_sha="sha-different",
                profile_hash=compute_profile_hash(self.PROFILE),
                factory_version="0.1.0",
            )
            self.assertFalse(ok)
```

- [ ] **Step 2: Run all tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_verdict_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_verdict_engine.py
git commit -m "test(gate): add end-to-end round-trip and gate reuse validation tests" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 18: Final Verification + LOC Check

**Files:**
- None created or modified — verification only.

**Interfaces:**
- Consumes: All files from Tasks 1-17.
- Produces: Confidence that all constraints are met.

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short 2>&1 | tail -40`
Expected: All tests PASS with zero failures. No regressions in existing tests.

- [ ] **Step 2: Verify LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/category_rules.py skills/bmad-story-automator/src/story_automator/core/verdict_engine.py skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
Expected: `category_rules.py` <= 330 LOC (includes worst_evidence_status moved from verdict_engine), `verdict_engine.py` <= 330 LOC, `gate_audit.py` <= 130 LOC.

- [ ] **Step 3: Verify no trailing whitespace**

Run: `grep -rn ' $' skills/bmad-story-automator/src/story_automator/core/category_rules.py skills/bmad-story-automator/src/story_automator/core/verdict_engine.py; echo "exit: $?"`
Expected: No matches, exit 1.

- [ ] **Step 4: Verify no new deps**

Run: `grep -n '^import\|^from' skills/bmad-story-automator/src/story_automator/core/category_rules.py skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`
Expected: Only stdlib imports + local imports (no `filelock`, `psutil`, or external packages).

- [ ] **Step 5: Run existing tests to confirm no regressions**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: All tests PASS. No test from m1-m7 modules broken.

- [ ] **Step 6: Verify modules are importable**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -c "from story_automator.core.verdict_engine import adjudicate, evaluate_gate, build_gate_file; from story_automator.core.category_rules import CATEGORY_RULES, apply_category_rule, coverage_verdict, risk_to_requirements, worst_evidence_status; print('All imports OK')"`
Expected: "All imports OK"
