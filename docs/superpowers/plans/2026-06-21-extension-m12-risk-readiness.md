# Extension M12: Risk-Scored Readiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the pre-build readiness gate (spec §8 module 1, §6.1, §9.1). A story enters `ready-for-dev` only after: (1) a structured risk profile is parsed and validated, (2) risk scores are mapped to priority P0–P3 which drives downstream coverage/level requirements, (3) `forbidden_until` ADR dependencies are resolved with no open blockers, and (4) the readiness verdict is persisted and auditable. This is the "front door" of the factory gate — nothing builds until readiness passes.

**Architecture:** Two new modules plus surgical modifications to existing M10 infrastructure:
- `risk_profile.py` (~200 LOC) — risk entry schema, validation, score→priority mapping, persistence under `_bmad/gate/risk/`, evidence-record conversion.
- `readiness_gate.py` (~200 LOC) — readiness evaluation combining risk assessment + forbidden_until blocker resolution + readiness verdict (READY/BLOCKED/NEEDS_RISK).

**Spec references:**
- §6.1: Risk drives requirements — Probability×Impact = 1–9, category ∈ {TECH, SEC, PERF, DATA, BUS, OPS}; score → P0–P3 → coverage/levels/NFRs.
- §8 Module 1: Implementation-Readiness Check (epic) + `validate-create-story` (story) + TEA `*risk`/`test-design`; computes story↔ADR deps → `forbidden_until`.
- §9.1 Readiness step: `risk+test-design(TEA) ▸ readiness gate PASS + no OPEN blocking ADR → ready-for-dev`.

**Dependency graph:** All existing M1–M10 modules consumed but NOT modified except: `gate_audit.py` (new readiness audit event), `gate_orchestrator.py` (readiness gate wiring), `commands/gate_cmd.py` (readiness CLI subcommand), `success_verifiers.py` (readiness verifier registration), `runtime_policy.py` (VALID_VERIFIERS addition). Import direction: `risk_profile.py` → `readiness_gate.py` → `gate_orchestrator.py` → `gate_cmd.py` (strictly unidirectional).

**Key existing interfaces consumed:**
- `product_profile.py`: `is_story_blocked`, `required_for_priority`, `compute_profile_hash`, `load_effective_profile`
- `category_rules.py`: `risk_to_requirements`
- `gate_schema.py`: `make_llm_evidence_record`, `canonical_json`, `GateSchemaError`
- `gate_audit.py`: `emit_gate_audit`, frozen dataclass event protocol
- `gate_orchestrator.py`: `run_production_gate` (consumes priority/has_unmitigated_risk_9 params)
- `evidence_io.py`: `persist_evidence_record`
- `trust_boundary.py`: `assert_host_context`
- `utils.py`: `ensure_dir`, `write_atomic`, `iso_now`, `md5_hex8`
- `profile_bridge.py`: `profile_customize_facts` (forbidden_until already surfaced)

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT modify existing m1–m9 module logic** except: `gate_audit.py` (new audit event), `gate_orchestrator.py` (readiness wiring), `commands/gate_cmd.py` (readiness subcommand), `success_verifiers.py` (readiness verifier), `runtime_policy.py` (VALID_VERIFIERS).
- **500-LOC soft limit per Python module.** `risk_profile.py` target ~200 LOC; `readiness_gate.py` ~200 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path; use `os.replace` via `write_atomic` for atomic writes.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/risk_profile.py` — risk schema, validation, score→priority, persistence, evidence (~200 LOC)
- `skills/bmad-story-automator/src/story_automator/core/readiness_gate.py` — readiness evaluation, blocker resolution, verdict (~200 LOC)
- `tests/test_risk_profile.py` — risk profile unit tests (~350 LOC)
- `tests/test_readiness_gate.py` — readiness gate unit tests (~350 LOC)
- `tests/test_readiness_integration.py` — end-to-end integration tests (~200 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — add `GateReadinessAudit` event (~+25 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — add `run_readiness_gate` wiring (~+50 LOC)
- `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py` — add `gate_readiness_action` + dispatch (~+50 LOC)
- `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py` — add `readiness_gate` verifier (~+30 LOC)
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` — add `"readiness_gate"` to `VALID_VERIFIERS` (~+1 line)
- `tests/test_gate_audit.py` — add tests for `GateReadinessAudit` (~+25 LOC)
- `tests/test_gate_cmd.py` — add tests for readiness CLI (~+40 LOC)
- `tests/test_success_verifiers.py` — add tests for readiness verifier (~+40 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/verdict_engine.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`, `core/product_profile.py`, `core/category_rules.py`, `core/gate_status.py`, `core/gate_remediation.py`.

---

### Task 1: Risk Profile Schema and Validation

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/risk_profile.py`
- Create: `tests/test_risk_profile.py`

**Interfaces:**
- Consumes: `gate_schema.GateSchemaError`.
- Produces:
  - `VALID_RISK_CATEGORIES` — frozenset `{"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"}` (§6.1).
  - `RiskProfileError(ValueError)` — raised on invalid risk data.
  - `validate_risk_entry(entry: dict) -> None` — validates a single risk entry has: `category` ∈ VALID_RISK_CATEGORIES, `probability` int 1–3, `impact` int 1–3, `score` == probability × impact (1–9), optional `rationale` str.
  - `validate_risk_profile(entries: list[dict]) -> None` — validates a list of risk entries. At least one entry required. No duplicate categories.
  - `make_risk_entry(category, probability, impact, *, rationale="") -> dict` — factory that computes score and validates.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_risk_profile.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.risk_profile import (
    VALID_RISK_CATEGORIES,
    RiskProfileError,
    make_risk_entry,
    validate_risk_entry,
    validate_risk_profile,
)


class RiskCategoriesTests(unittest.TestCase):
    def test_all_six_categories_present(self) -> None:
        self.assertEqual(
            VALID_RISK_CATEGORIES,
            frozenset({"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"}),
        )


class ValidateRiskEntryTests(unittest.TestCase):
    def test_valid_entry(self) -> None:
        entry = {
            "category": "SEC", "probability": 3, "impact": 3,
            "score": 9, "rationale": "critical auth flow",
        }
        validate_risk_entry(entry)

    def test_invalid_category(self) -> None:
        entry = {
            "category": "UNKNOWN", "probability": 1, "impact": 1,
            "score": 1,
        }
        with self.assertRaises(RiskProfileError):
            validate_risk_entry(entry)

    def test_probability_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": bad,
                    "impact": 1, "score": bad,
                })

    def test_impact_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": 1,
                    "impact": bad, "score": bad,
                })

    def test_score_must_equal_probability_times_impact(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 2,
                "impact": 3, "score": 5,
            })

    def test_missing_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({"probability": 1, "impact": 1, "score": 1})

    def test_boolean_probability_rejected(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": True,
                "impact": 1, "score": 1,
            })

    def test_rationale_must_be_string_if_present(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 1,
                "impact": 1, "score": 1, "rationale": 42,
            })


class ValidateRiskProfileTests(unittest.TestCase):
    def test_valid_profile(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "TECH", "probability": 2, "impact": 2, "score": 4},
        ]
        validate_risk_profile(entries)

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile([])

    def test_duplicate_category_raises(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "SEC", "probability": 1, "impact": 1, "score": 1},
        ]
        with self.assertRaises(RiskProfileError):
            validate_risk_profile(entries)

    def test_non_list_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile("not a list")


class MakeRiskEntryTests(unittest.TestCase):
    def test_computes_score(self) -> None:
        entry = make_risk_entry("PERF", 2, 3, rationale="latency risk")
        self.assertEqual(entry["score"], 6)
        self.assertEqual(entry["category"], "PERF")
        self.assertEqual(entry["rationale"], "latency risk")

    def test_invalid_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            make_risk_entry("INVALID", 1, 1)

    def test_score_range_1_to_9(self) -> None:
        entry_min = make_risk_entry("TECH", 1, 1)
        entry_max = make_risk_entry("TECH", 3, 3)
        self.assertEqual(entry_min["score"], 1)
        self.assertEqual(entry_max["score"], 9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v`
Expected: ModuleNotFoundError — `risk_profile` not found.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/risk_profile.py`:

```python
"""Risk profile schema, validation, and scoring (§6.1, §8 module 1).

Parses the structured risk profile emitted by TEA *risk generators.
Maps Probability×Impact scores (1–9) to priorities (P0–P3) which
drive downstream coverage/level requirements via profile.matrix.
"""
from __future__ import annotations

from typing import Any


class RiskProfileError(ValueError):
    pass


VALID_RISK_CATEGORIES = frozenset({"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"})

_PROBABILITY_RANGE = range(1, 4)  # 1–3
_IMPACT_RANGE = range(1, 4)       # 1–3


def validate_risk_entry(entry: dict[str, Any]) -> None:
    if not isinstance(entry, dict):
        raise RiskProfileError("risk entry must be a dict")
    category = entry.get("category")
    if not isinstance(category, str) or category not in VALID_RISK_CATEGORIES:
        raise RiskProfileError(
            f"risk entry category must be one of "
            f"{sorted(VALID_RISK_CATEGORIES)}; got {category!r}"
        )
    _validate_int_range(entry, "probability", _PROBABILITY_RANGE)
    _validate_int_range(entry, "impact", _IMPACT_RANGE)
    score = entry.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise RiskProfileError("risk entry score must be an integer")
    expected = entry["probability"] * entry["impact"]
    if score != expected:
        raise RiskProfileError(
            f"risk entry score must equal probability × impact "
            f"({expected}); got {score}"
        )
    rationale = entry.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise RiskProfileError("risk entry rationale must be a string")


def validate_risk_profile(entries: Any) -> None:
    if not isinstance(entries, list):
        raise RiskProfileError("risk profile must be a list of entries")
    if not entries:
        raise RiskProfileError("risk profile must have at least one entry")
    seen: set[str] = set()
    for entry in entries:
        validate_risk_entry(entry)
        cat = entry["category"]
        if cat in seen:
            raise RiskProfileError(f"duplicate risk category: {cat}")
        seen.add(cat)


def make_risk_entry(
    category: str,
    probability: int,
    impact: int,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "category": category,
        "probability": probability,
        "impact": impact,
        "score": probability * impact,
    }
    if rationale:
        entry["rationale"] = rationale
    validate_risk_entry(entry)
    return entry


def _validate_int_range(
    obj: dict[str, Any], key: str, valid_range: range,
) -> None:
    val = obj.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise RiskProfileError(f"risk entry {key} must be an integer")
    if val not in valid_range:
        raise RiskProfileError(
            f"risk entry {key} must be {valid_range.start}–"
            f"{valid_range.stop - 1}; got {val}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/risk_profile.py tests/test_risk_profile.py
git commit -m "feat(gate): add risk profile schema and validation (§6.1)" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Risk Score → Priority Mapping

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/risk_profile.py`
- Modify: `tests/test_risk_profile.py`

**Interfaces:**
- Consumes: `validate_risk_profile` (Task 1).
- Produces:
  - `DEFAULT_RISK_THRESHOLDS` — dict mapping score ranges to priorities: `{9: "P0", 6: "P1", 3: "P2", 1: "P3"}` (lower bounds; score ≥ threshold → that priority). §6.1: score 9→P0, 6–8→P1, 3–5→P2, 1–2→P3.
  - `risk_score_to_priority(score: int, *, thresholds=None) -> str` — maps a single score to priority. Profile-overridable via custom thresholds.
  - `aggregate_risk_priority(entries: list[dict]) -> str` — returns worst (highest) priority across all risk entries. §6.1: the factory uses the worst risk to set the bar.
  - `has_unmitigated_risk_9(entries: list[dict]) -> bool` — True if any entry has score 9 and no mitigation rationale. §6.3: "if any risk.score==9 and no mitigation → FAIL".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk_profile.py`:

```python
from story_automator.core.risk_profile import (
    DEFAULT_RISK_THRESHOLDS,
    risk_score_to_priority,
    aggregate_risk_priority,
    has_unmitigated_risk_9,
)


class RiskScoreToPriorityTests(unittest.TestCase):
    def test_score_9_is_p0(self) -> None:
        self.assertEqual(risk_score_to_priority(9), "P0")

    def test_scores_6_7_8_are_p1(self) -> None:
        for score in (6, 7, 8):
            self.assertEqual(risk_score_to_priority(score), "P1", f"score={score}")

    def test_scores_3_4_5_are_p2(self) -> None:
        for score in (3, 4, 5):
            self.assertEqual(risk_score_to_priority(score), "P2", f"score={score}")

    def test_scores_1_2_are_p3(self) -> None:
        for score in (1, 2):
            self.assertEqual(risk_score_to_priority(score), "P3", f"score={score}")

    def test_custom_thresholds(self) -> None:
        custom = {7: "P0", 4: "P1", 2: "P2", 1: "P3"}
        self.assertEqual(risk_score_to_priority(9, thresholds=custom), "P0")
        self.assertEqual(risk_score_to_priority(5, thresholds=custom), "P1")
        self.assertEqual(risk_score_to_priority(3, thresholds=custom), "P2")
        self.assertEqual(risk_score_to_priority(1, thresholds=custom), "P3")

    def test_out_of_range_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(0)
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(10)

    def test_default_thresholds_has_four_entries(self) -> None:
        self.assertEqual(len(DEFAULT_RISK_THRESHOLDS), 4)


class AggregateRiskPriorityTests(unittest.TestCase):
    def test_worst_priority_wins(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),   # score=1 → P3
            make_risk_entry("SEC", 3, 3),    # score=9 → P0
            make_risk_entry("PERF", 2, 2),   # score=4 → P2
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P0")

    def test_single_entry(self) -> None:
        entries = [make_risk_entry("DATA", 2, 1)]  # score=2 → P3
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_all_low_risk(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),  # P3
            make_risk_entry("OPS", 1, 2),   # P3
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            aggregate_risk_priority([])


class HasUnmitigatedRisk9Tests(unittest.TestCase):
    def test_no_score_9(self) -> None:
        entries = [make_risk_entry("TECH", 2, 3)]  # score=6
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_score_9_without_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]  # score=9, no rationale
        self.assertTrue(has_unmitigated_risk_9(entries))

    def test_score_9_with_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated by WAF")]
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_mixed_some_mitigated(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 3, rationale="mitigated"),
            make_risk_entry("DATA", 3, 3),  # score=9, no rationale
        ]
        self.assertTrue(has_unmitigated_risk_9(entries))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v -k "Priority or Risk9 or Threshold"`
Expected: ImportError — `risk_score_to_priority` etc. not found.

- [ ] **Step 3: Write minimal implementation**

Add to `risk_profile.py`:

```python
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_SCORE_RANGE = range(1, 10)  # 1–9

DEFAULT_RISK_THRESHOLDS: dict[int, str] = {9: "P0", 6: "P1", 3: "P2", 1: "P3"}


def risk_score_to_priority(
    score: int,
    *,
    thresholds: dict[int, str] | None = None,
) -> str:
    if not isinstance(score, int) or isinstance(score, bool) or score not in _SCORE_RANGE:
        raise RiskProfileError(f"risk score must be 1–9; got {score}")
    thr = thresholds or DEFAULT_RISK_THRESHOLDS
    for threshold in sorted(thr, reverse=True):
        if score >= threshold:
            return thr[threshold]
    return "P3"


def aggregate_risk_priority(entries: list[dict[str, Any]]) -> str:
    validate_risk_profile(entries)
    worst = "P3"
    worst_order = _PRIORITY_ORDER["P3"]
    for entry in entries:
        priority = risk_score_to_priority(entry["score"])
        order = _PRIORITY_ORDER.get(priority, 3)
        if order < worst_order:
            worst = priority
            worst_order = order
    return worst


def has_unmitigated_risk_9(entries: list[dict[str, Any]]) -> bool:
    for entry in entries:
        if entry.get("score", 0) == 9:
            rationale = entry.get("rationale", "")
            if not rationale or not rationale.strip():
                return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/risk_profile.py tests/test_risk_profile.py
git commit -m "feat(gate): add risk score to priority mapping with configurable thresholds" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Risk Profile Persistence

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/risk_profile.py`
- Modify: `tests/test_risk_profile.py`

**Interfaces:**
- Consumes: `validate_risk_profile` (Task 1), `gate_schema.canonical_json`, `trust_boundary.assert_host_context`, `utils.ensure_dir`, `utils.write_atomic`, `utils.iso_now`.
- Produces:
  - `persist_risk_profile(project_root, target_id, entries, *, tier="code") -> Path` — writes validated risk profile to `_bmad/gate/risk/<target_id>.json` atomically. Stores: `{target_id, tier, entries, created_at, version}`.
  - `load_risk_profile(project_root, target_id) -> dict[str, Any]` — loads and re-validates a persisted risk profile. Raises `RiskProfileError` on missing/corrupt.
  - `risk_profile_exists(project_root, target_id) -> bool` — fast existence check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk_profile.py`:

```python
import json
import tempfile
from pathlib import Path

from story_automator.core.risk_profile import (
    persist_risk_profile,
    load_risk_profile,
    risk_profile_exists,
)


class PersistRiskProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.entries = [
            make_risk_entry("SEC", 3, 3, rationale="auth flow"),
            make_risk_entry("TECH", 2, 2),
        ]

    def test_persist_creates_file(self) -> None:
        path = persist_risk_profile(self.tmp, "E1-001", self.entries)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["target_id"], "E1-001")
        self.assertEqual(len(data["entries"]), 2)
        self.assertIn("created_at", data)

    def test_persist_validates_entries(self) -> None:
        with self.assertRaises(RiskProfileError):
            persist_risk_profile(self.tmp, "E1-001", [])

    def test_persist_path_under_gate_risk(self) -> None:
        path = persist_risk_profile(self.tmp, "E1-001", self.entries)
        self.assertIn("_bmad/gate/risk", path.as_posix())
        self.assertEqual(path.name, "E1-001.json")

    def test_persist_overwrites_existing(self) -> None:
        persist_risk_profile(self.tmp, "E1-001", self.entries)
        new_entries = [make_risk_entry("OPS", 1, 1)]
        path = persist_risk_profile(self.tmp, "E1-001", new_entries)
        data = json.loads(path.read_text())
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["category"], "OPS")


class LoadRiskProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.entries = [make_risk_entry("SEC", 3, 2)]

    def test_load_returns_persisted_data(self) -> None:
        persist_risk_profile(self.tmp, "E1-001", self.entries)
        data = load_risk_profile(self.tmp, "E1-001")
        self.assertEqual(data["target_id"], "E1-001")
        self.assertEqual(len(data["entries"]), 1)

    def test_load_missing_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            load_risk_profile(self.tmp, "no-such")

    def test_load_corrupt_raises(self) -> None:
        risk_dir = Path(self.tmp) / "_bmad" / "gate" / "risk"
        risk_dir.mkdir(parents=True)
        (risk_dir / "bad.json").write_text("not json")
        with self.assertRaises(RiskProfileError):
            load_risk_profile(self.tmp, "bad")


class RiskProfileExistsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_exists_after_persist(self) -> None:
        entries = [make_risk_entry("TECH", 1, 1)]
        persist_risk_profile(self.tmp, "E1-001", entries)
        self.assertTrue(risk_profile_exists(self.tmp, "E1-001"))

    def test_not_exists_initially(self) -> None:
        self.assertFalse(risk_profile_exists(self.tmp, "E1-001"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v -k "Persist or Load or Exists"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `risk_profile.py`:

```python
import json
from pathlib import Path

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic

_RISK_DIR = "risk"
_RISK_PROFILE_VERSION = 1


def _risk_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _RISK_DIR


def persist_risk_profile(
    project_root: str | Path,
    target_id: str,
    entries: list[dict[str, Any]],
    *,
    tier: str = "code",
) -> Path:
    assert_host_context("persist_risk_profile")
    validate_risk_profile(entries)
    risk_d = _risk_dir(project_root)
    ensure_dir(risk_d)
    record: dict[str, Any] = {
        "version": _RISK_PROFILE_VERSION,
        "target_id": target_id,
        "tier": tier,
        "entries": entries,
        "created_at": iso_now(),
    }
    target = risk_d / f"{target_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_risk_profile(
    project_root: str | Path,
    target_id: str,
) -> dict[str, Any]:
    path = _risk_dir(project_root) / f"{target_id}.json"
    if not path.is_file():
        raise RiskProfileError(f"risk profile not found: {target_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RiskProfileError(
            f"risk profile corrupt: {target_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RiskProfileError(f"risk profile must be a dict: {target_id}")
    validate_risk_profile(data.get("entries", []))
    return data


def risk_profile_exists(
    project_root: str | Path,
    target_id: str,
) -> bool:
    return (_risk_dir(project_root) / f"{target_id}.json").is_file()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/risk_profile.py tests/test_risk_profile.py
git commit -m "feat(gate): add risk profile persistence under _bmad/gate/risk/" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Risk Profile as Evidence Record

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/risk_profile.py`
- Modify: `tests/test_risk_profile.py`

**Interfaces:**
- Consumes: `gate_schema.make_llm_evidence_record` (risk data is LLM-proposed per §6.1, hence non-deterministic), `aggregate_risk_priority` (Task 2), `has_unmitigated_risk_9` (Task 2).
- Produces:
  - `risk_profile_to_evidence(entries, target_id, *, confidence=7) -> dict[str, Any]` — converts a risk profile into a LLM evidence record for the gate file's `risk_profile_ref`. Category is `"readiness"`, status is `"ok"` (risk assessment completed), metrics include `{priority, max_score, unmitigated_risk_9, entry_count}`.
  - `compute_risk_profile_ref(entries, target_id) -> str` — compute a stable hash ref for the risk profile to populate `gate_file.risk_profile_ref`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk_profile.py`:

```python
from story_automator.core.risk_profile import (
    risk_profile_to_evidence,
    compute_risk_profile_ref,
)


class RiskProfileToEvidenceTests(unittest.TestCase):
    def test_basic_evidence_record(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 3, rationale="critical"),
            make_risk_entry("TECH", 2, 1),
        ]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertEqual(evidence["category"], "readiness")
        self.assertEqual(evidence["status"], "ok")
        self.assertFalse(evidence["deterministic"])
        self.assertIn("confidence", evidence)
        self.assertEqual(evidence["metrics"]["priority"], "P0")
        self.assertEqual(evidence["metrics"]["max_score"], 9)
        self.assertEqual(evidence["metrics"]["entry_count"], 2)

    def test_evidence_flags_unmitigated_risk_9(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertTrue(evidence["metrics"]["unmitigated_risk_9"])

    def test_evidence_with_custom_confidence(self) -> None:
        entries = [make_risk_entry("TECH", 1, 1)]
        evidence = risk_profile_to_evidence(entries, "E1-001", confidence=3)
        self.assertEqual(evidence["confidence"], 3)

    def test_collector_name(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertEqual(evidence["collector"], "risk_assessment")
        self.assertEqual(evidence["tool"], "tea_risk")


class ComputeRiskProfileRefTests(unittest.TestCase):
    def test_deterministic_ref(self) -> None:
        entries = [make_risk_entry("SEC", 3, 2)]
        ref1 = compute_risk_profile_ref(entries, "E1-001")
        ref2 = compute_risk_profile_ref(entries, "E1-001")
        self.assertEqual(ref1, ref2)
        self.assertTrue(len(ref1) > 0)

    def test_different_entries_different_ref(self) -> None:
        e1 = [make_risk_entry("SEC", 3, 2)]
        e2 = [make_risk_entry("SEC", 1, 1)]
        self.assertNotEqual(
            compute_risk_profile_ref(e1, "E1-001"),
            compute_risk_profile_ref(e2, "E1-001"),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v -k "Evidence or ProfileRef"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `risk_profile.py`:

```python
from .gate_schema import make_llm_evidence_record
from .utils import md5_hex8


def risk_profile_to_evidence(
    entries: list[dict[str, Any]],
    target_id: str,
    *,
    confidence: int = 7,
) -> dict[str, Any]:
    validate_risk_profile(entries)
    priority = aggregate_risk_priority(entries)
    max_score = max(e["score"] for e in entries)
    unmitigated = has_unmitigated_risk_9(entries)
    return make_llm_evidence_record(
        collector="risk_assessment",
        tool="tea_risk",
        category="readiness",
        status="ok",
        metrics={
            "priority": priority,
            "max_score": max_score,
            "unmitigated_risk_9": unmitigated,
            "entry_count": len(entries),
            "target_id": target_id,
        },
        confidence=confidence,
        rationale=f"risk assessment for {target_id}: priority={priority}, max_score={max_score}",
    )


def compute_risk_profile_ref(
    entries: list[dict[str, Any]],
    target_id: str,
) -> str:
    stable = canonical_json({"target_id": target_id, "entries": entries})
    return md5_hex8(stable)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/risk_profile.py tests/test_risk_profile.py
git commit -m "feat(gate): add risk profile to evidence record conversion" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Story Blocker Resolution

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/readiness_gate.py`
- Create: `tests/test_readiness_gate.py`

**Interfaces:**
- Consumes: `product_profile.is_story_blocked` (existing M1), `product_profile.load_effective_profile`.
- Produces:
  - `resolve_story_blockers(profile, story_id) -> list[dict[str, Any]]` — checks `forbidden_until` for the given story ID. Returns a list of blocker dicts: `{adr_id: str, patterns: list[str], story_id: str}`. Empty list means no blockers.
  - `format_blocker_summary(blockers: list[dict]) -> str` — human-readable summary of blockers for audit/CLI output.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_readiness_gate.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.readiness_gate import (
    resolve_story_blockers,
    format_blocker_summary,
)


class ResolveStoryBlockersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "id": "msme-erp", "version": 1,
            "forbidden_until": {
                "ADR-0083": ["E*.envelope-*"],
                "DG-2": ["*.cost-to-serve"],
                "DG-3": ["E*.ca-channel-*"],
            },
        }

    def test_blocked_by_adr(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1.envelope-auth")
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["adr_id"], "ADR-0083")

    def test_blocked_by_multiple_adrs(self) -> None:
        profile = {
            "id": "test", "version": 1,
            "forbidden_until": {
                "ADR-1": ["E1-*"],
                "ADR-2": ["E1-*"],
            },
        }
        blockers = resolve_story_blockers(profile, "E1-story")
        self.assertEqual(len(blockers), 2)

    def test_not_blocked(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1-safe-story")
        self.assertEqual(blockers, [])

    def test_no_forbidden_until(self) -> None:
        profile = {"id": "test", "version": 1}
        blockers = resolve_story_blockers(profile, "any-story")
        self.assertEqual(blockers, [])

    def test_cost_to_serve_blocked(self) -> None:
        blockers = resolve_story_blockers(self.profile, "E1.cost-to-serve")
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["adr_id"], "DG-2")


class FormatBlockerSummaryTests(unittest.TestCase):
    def test_empty_blockers(self) -> None:
        self.assertEqual(format_blocker_summary([]), "no blockers")

    def test_single_blocker(self) -> None:
        blockers = [{"adr_id": "ADR-0083", "patterns": ["E*.envelope-*"], "story_id": "E1.envelope-auth"}]
        summary = format_blocker_summary(blockers)
        self.assertIn("ADR-0083", summary)

    def test_multiple_blockers(self) -> None:
        blockers = [
            {"adr_id": "ADR-1", "patterns": ["E1-*"], "story_id": "E1-x"},
            {"adr_id": "ADR-2", "patterns": ["E1-*"], "story_id": "E1-x"},
        ]
        summary = format_blocker_summary(blockers)
        self.assertIn("ADR-1", summary)
        self.assertIn("ADR-2", summary)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/readiness_gate.py`:

```python
"""Readiness gate — pre-build story readiness evaluation (§8 module 1, §9.1).

Evaluates whether a story is ready to enter ready-for-dev:
1. Risk profile parsed and scored → priority (P0–P3)
2. forbidden_until ADR dependencies resolved → no open blockers
3. Readiness verdict: READY / BLOCKED / NEEDS_RISK
"""
from __future__ import annotations

import fnmatch
from typing import Any


def resolve_story_blockers(
    profile: dict[str, Any],
    story_id: str,
) -> list[dict[str, Any]]:
    """Check forbidden_until for story blockers.

    Returns list of blocker dicts. Empty = not blocked.
    """
    mapping = profile.get("forbidden_until") or {}
    blockers: list[dict[str, Any]] = []
    for adr_id in sorted(mapping):
        patterns = mapping[adr_id]
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if fnmatch.fnmatchcase(story_id, pattern):
                blockers.append({
                    "adr_id": adr_id,
                    "patterns": list(patterns),
                    "story_id": story_id,
                })
                break
    return blockers


def format_blocker_summary(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "no blockers"
    parts = [f"{b['adr_id']} blocks {b['story_id']}" for b in blockers]
    return "; ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/readiness_gate.py tests/test_readiness_gate.py
git commit -m "feat(gate): add story blocker resolution from forbidden_until" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Readiness Check Core

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/readiness_gate.py`
- Modify: `tests/test_readiness_gate.py`

**Interfaces:**
- Consumes: `resolve_story_blockers` (Task 5), `risk_profile.aggregate_risk_priority` (Task 2), `risk_profile.has_unmitigated_risk_9` (Task 2), `risk_profile.validate_risk_profile` (Task 1), `risk_profile.risk_score_to_priority` (Task 2), `category_rules.risk_to_requirements` (existing M9), `product_profile.required_for_priority` (existing M1).
- Produces:
  - `READINESS_VERDICTS` — frozenset `{"READY", "BLOCKED", "NEEDS_RISK"}`.
  - `check_readiness(story_id, *, profile, risk_entries=None, thresholds=None) -> dict[str, Any]` — core readiness evaluation. Returns `{verdict, priority, blockers, risk_summary, requirements, reason}`.
    - `NEEDS_RISK`: no risk entries provided and no persisted risk profile.
    - `BLOCKED`: story blocked by forbidden_until ADR dependency.
    - `READY`: risk assessed, no blockers, ready for dev.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_readiness_gate.py`:

```python
from story_automator.core.readiness_gate import (
    READINESS_VERDICTS,
    check_readiness,
)
from story_automator.core.risk_profile import make_risk_entry


class ReadinessVerdictsTests(unittest.TestCase):
    def test_three_verdicts(self) -> None:
        self.assertEqual(
            READINESS_VERDICTS,
            frozenset({"READY", "BLOCKED", "NEEDS_RISK"}),
        )


class CheckReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_ready_with_risk(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P2")
        self.assertIsInstance(result["requirements"], dict)
        self.assertIn("coverage_pct", result["requirements"])

    def test_needs_risk_when_no_entries(self) -> None:
        result = check_readiness("E1-001", profile=self.profile)
        self.assertEqual(result["verdict"], "NEEDS_RISK")
        self.assertIn("no risk", result["reason"].lower())

    def test_blocked_by_forbidden_until(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-0083": ["E1-*"]}
        entries = [make_risk_entry("SEC", 2, 2)]
        result = check_readiness(
            "E1-001", profile=profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(len(result["blockers"]), 1)

    def test_blocked_takes_precedence_over_needs_risk(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        result = check_readiness("E1-001", profile=profile)
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_high_risk_sets_p0(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P0")
        self.assertEqual(result["requirements"]["coverage_pct"], 100)

    def test_low_risk_sets_p3(self) -> None:
        entries = [make_risk_entry("OPS", 1, 1)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P3")
        self.assertEqual(result["requirements"]["coverage_pct"], 20)

    def test_risk_summary_included(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 2),
            make_risk_entry("TECH", 1, 1),
        ]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["risk_summary"]["max_score"], 6)
        self.assertEqual(result["risk_summary"]["entry_count"], 2)

    def test_unmitigated_risk_9_flagged(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertTrue(result["risk_summary"]["unmitigated_risk_9"])

    def test_custom_thresholds(self) -> None:
        custom = {7: "P0", 4: "P1", 2: "P2", 1: "P3"}
        entries = [make_risk_entry("TECH", 2, 2)]  # score=4
        result = check_readiness(
            "E1-001", profile=self.profile,
            risk_entries=entries, thresholds=custom,
        )
        self.assertEqual(result["priority"], "P1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v -k "CheckReadiness or ReadinessVerdicts"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `readiness_gate.py`:

```python
from .risk_profile import (
    aggregate_risk_priority,
    has_unmitigated_risk_9,
    risk_score_to_priority,
    validate_risk_profile,
)
from .product_profile import required_for_priority

READINESS_VERDICTS = frozenset({"READY", "BLOCKED", "NEEDS_RISK"})


def check_readiness(
    story_id: str,
    *,
    profile: dict[str, Any],
    risk_entries: list[dict[str, Any]] | None = None,
    thresholds: dict[int, str] | None = None,
) -> dict[str, Any]:
    """§9.1: evaluate story readiness for ready-for-dev.

    Returns {verdict, priority, blockers, risk_summary, requirements, reason}.
    """
    blockers = resolve_story_blockers(profile, story_id)

    if blockers:
        return {
            "verdict": "BLOCKED",
            "priority": "",
            "blockers": blockers,
            "risk_summary": {},
            "requirements": {},
            "reason": format_blocker_summary(blockers),
        }

    if not risk_entries:
        return {
            "verdict": "NEEDS_RISK",
            "priority": "",
            "blockers": [],
            "risk_summary": {},
            "requirements": {},
            "reason": "no risk profile provided; run TEA risk assessment first",
        }

    validate_risk_profile(risk_entries)
    priority = aggregate_risk_priority(risk_entries)
    if thresholds:
        scores = [e["score"] for e in risk_entries]
        priorities = [risk_score_to_priority(s, thresholds=thresholds) for s in scores]
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        priority = min(priorities, key=lambda p: priority_order.get(p, 3))

    max_score = max(e["score"] for e in risk_entries)
    unmitigated = has_unmitigated_risk_9(risk_entries)
    requirements = required_for_priority(profile, priority)

    return {
        "verdict": "READY",
        "priority": priority,
        "blockers": [],
        "risk_summary": {
            "max_score": max_score,
            "entry_count": len(risk_entries),
            "unmitigated_risk_9": unmitigated,
        },
        "requirements": requirements,
        "reason": f"ready for dev at priority {priority}",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/readiness_gate.py tests/test_readiness_gate.py
git commit -m "feat(gate): add check_readiness core with READY/BLOCKED/NEEDS_RISK verdicts" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Readiness Result Persistence

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/readiness_gate.py`
- Modify: `tests/test_readiness_gate.py`

**Interfaces:**
- Consumes: `check_readiness` (Task 6), `gate_schema.canonical_json`, `trust_boundary.assert_host_context`, `utils.ensure_dir`, `utils.write_atomic`, `utils.iso_now`.
- Produces:
  - `persist_readiness_result(project_root, story_id, result) -> Path` — writes readiness verdict to `_bmad/gate/readiness/<story_id>.json` atomically.
  - `load_readiness_result(project_root, story_id) -> dict[str, Any] | None` — loads persisted readiness result. Returns None if not found.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_readiness_gate.py`:

```python
import json
import tempfile
from pathlib import Path

from story_automator.core.readiness_gate import (
    persist_readiness_result,
    load_readiness_result,
)


class PersistReadinessResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
        }

    def test_persist_creates_file(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = check_readiness("E1-001", profile=self.profile, risk_entries=entries)
        path = persist_readiness_result(self.tmp, "E1-001", result)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["story_id"], "E1-001")
        self.assertEqual(data["verdict"], "READY")

    def test_persist_path_under_readiness(self) -> None:
        result = check_readiness("E1-001", profile=self.profile)
        path = persist_readiness_result(self.tmp, "E1-001", result)
        self.assertIn("_bmad/gate/readiness", path.as_posix())

    def test_load_returns_persisted(self) -> None:
        entries = [make_risk_entry("SEC", 3, 2)]
        result = check_readiness("E1-001", profile=self.profile, risk_entries=entries)
        persist_readiness_result(self.tmp, "E1-001", result)
        loaded = load_readiness_result(self.tmp, "E1-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["verdict"], "READY")

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(load_readiness_result(self.tmp, "no-such"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v -k "PersistReadiness or LoadReadiness"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `readiness_gate.py`:

```python
import json
from pathlib import Path

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic

_READINESS_DIR = "readiness"


def _readiness_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _READINESS_DIR


def persist_readiness_result(
    project_root: str | Path,
    story_id: str,
    result: dict[str, Any],
) -> Path:
    assert_host_context("persist_readiness_result")
    readiness_d = _readiness_dir(project_root)
    ensure_dir(readiness_d)
    record: dict[str, Any] = {
        "story_id": story_id,
        "checked_at": iso_now(),
    }
    record.update(result)
    target = readiness_d / f"{story_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_readiness_result(
    project_root: str | Path,
    story_id: str,
) -> dict[str, Any] | None:
    path = _readiness_dir(project_root) / f"{story_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_gate.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/readiness_gate.py tests/test_readiness_gate.py
git commit -m "feat(gate): add readiness result persistence under _bmad/gate/readiness/" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: GateReadinessCheck Audit Event

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing `emit_gate_audit` pattern, frozen dataclass protocol.
- Produces:
  - `GateReadinessAudit` — emitted when a readiness check completes. Fields: `story_id`, `verdict` (READY/BLOCKED/NEEDS_RISK), `priority`, `blocker_count`, `reason`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
from story_automator.core.gate_audit import GateReadinessAudit


class GateReadinessAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateReadinessAudit(
            story_id="E1-001", verdict="READY",
            priority="P1", blocker_count=0, reason="ready",
        )
        self.assertEqual(event.event_name, "GateReadinessCheck")

    def test_to_dict_contains_all_fields(self) -> None:
        event = GateReadinessAudit(
            story_id="E1-001", verdict="BLOCKED",
            priority="", blocker_count=2, reason="ADR-0083 blocks E1-001",
        )
        d = event.to_dict()
        self.assertEqual(d["story_id"], "E1-001")
        self.assertEqual(d["verdict"], "BLOCKED")
        self.assertEqual(d["blocker_count"], 2)
        self.assertIn("reason", d)

    def test_frozen(self) -> None:
        event = GateReadinessAudit(story_id="E1-001")
        with self.assertRaises(AttributeError):
            event.story_id = "E1-002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v -k "GateReadiness"`
Expected: ImportError — `GateReadinessAudit` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` (before the `_AuditEvent` union, following the existing frozen dataclass pattern):

```python
@dataclasses.dataclass(frozen=True)
class GateReadinessAudit:
    """Audit event: readiness check completed for a story."""
    event_name: str = dataclasses.field(default="GateReadinessCheck", init=False)
    story_id: str = ""
    verdict: str = ""
    priority: str = ""
    blocker_count: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "verdict": self.verdict,
            "priority": self.priority,
            "blocker_count": self.blocker_count,
            "reason": self.reason,
        }
```

Update the `_AuditEvent` union type to include `GateReadinessAudit`:

```python
_AuditEvent = (
    GateStartedAudit | EvidenceCollectedAudit | GateBoundaryViolation
    | GateDecisionAudit | GateRenderedAudit
    | GateProfileDriftAudit | GateParkedAudit
    | GateReadinessAudit
)
```

Add `"GateReadinessAudit"` to the `__all__` list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add GateReadinessCheck audit event" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Readiness Gate Orchestrator Wiring

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Create: `tests/test_readiness_integration.py`

**Interfaces:**
- Consumes: `readiness_gate.check_readiness` (Task 6), `readiness_gate.persist_readiness_result` (Task 7), `risk_profile.load_risk_profile` (Task 3), `risk_profile.risk_profile_exists` (Task 3), `risk_profile.persist_risk_profile` (Task 3), `risk_profile.risk_profile_to_evidence` (Task 4), `risk_profile.compute_risk_profile_ref` (Task 4), `gate_audit.GateReadinessAudit` (Task 8), `gate_audit.emit_gate_audit`, `trust_boundary.assert_host_context`.
- Produces:
  - `run_readiness_gate(project_root, story_id, *, profile, risk_entries=None, audit_policy=None, audit_path=None) -> dict[str, Any]` — full readiness lifecycle:
    1. Load existing risk profile if `risk_entries` not provided.
    2. Persist risk entries if provided (overwrites).
    3. Run `check_readiness`.
    4. Persist readiness result.
    5. Emit `GateReadinessAudit`.
    6. Return readiness result dict enriched with `risk_profile_ref`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_readiness_integration.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_orchestrator import run_readiness_gate
from story_automator.core.risk_profile import (
    make_risk_entry,
    persist_risk_profile,
    load_risk_profile,
)


class RunReadinessGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_ready_with_inline_risk_entries(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P2")
        self.assertIn("risk_profile_ref", result)

    def test_ready_with_persisted_risk(self) -> None:
        entries = [make_risk_entry("SEC", 2, 3)]
        persist_risk_profile(self.tmp, "E1-001", entries)
        result = run_readiness_gate(
            self.tmp, "E1-001", profile=self.profile,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P1")

    def test_needs_risk_when_nothing_available(self) -> None:
        result = run_readiness_gate(
            self.tmp, "E1-001", profile=self.profile,
        )
        self.assertEqual(result["verdict"], "NEEDS_RISK")

    def test_blocked_by_adr(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        entries = [make_risk_entry("TECH", 1, 1)]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_persists_risk_entries(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        loaded = load_risk_profile(self.tmp, "E1-001")
        self.assertEqual(len(loaded["entries"]), 1)

    def test_persists_readiness_result(self) -> None:
        from story_automator.core.readiness_gate import load_readiness_result
        entries = [make_risk_entry("PERF", 1, 2)]
        run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        loaded = load_readiness_result(self.tmp, "E1-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["verdict"], "READY")

    def test_priority_flows_to_requirements(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P0")
        self.assertEqual(result["requirements"]["coverage_pct"], 100)

    def test_inline_entries_override_persisted(self) -> None:
        old_entries = [make_risk_entry("TECH", 1, 1)]
        persist_risk_profile(self.tmp, "E1-001", old_entries)
        new_entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=new_entries,
        )
        self.assertEqual(result["priority"], "P0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_integration.py -v`
Expected: ImportError — `run_readiness_gate` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
from .readiness_gate import check_readiness, persist_readiness_result
from .risk_profile import (
    compute_risk_profile_ref,
    load_risk_profile,
    persist_risk_profile,
    risk_profile_exists,
    RiskProfileError,
)
from .gate_audit import GateReadinessAudit


def run_readiness_gate(
    project_root: str | Path,
    story_id: str,
    *,
    profile: dict[str, Any],
    risk_entries: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """§9.1: full readiness lifecycle — risk + blockers → verdict."""
    assert_host_context("run_readiness_gate")

    resolved_entries = risk_entries
    if resolved_entries:
        persist_risk_profile(project_root, story_id, resolved_entries)
    elif risk_entries is None and risk_profile_exists(project_root, story_id):
        try:
            risk_data = load_risk_profile(project_root, story_id)
            resolved_entries = risk_data.get("entries")
        except RiskProfileError:
            resolved_entries = None

    result = check_readiness(
        story_id, profile=profile, risk_entries=resolved_entries,
    )

    if resolved_entries:
        result["risk_profile_ref"] = compute_risk_profile_ref(
            resolved_entries, story_id,
        )
    else:
        result["risk_profile_ref"] = ""

    persist_readiness_result(project_root, story_id, result)

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateReadinessAudit(
                story_id=story_id,
                verdict=result["verdict"],
                priority=result.get("priority", ""),
                blocker_count=len(result.get("blockers", [])),
                reason=result.get("reason", ""),
            ),
        )

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py \
       tests/test_readiness_integration.py
git commit -m "feat(gate): wire readiness gate into orchestrator with risk persistence and audit" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: readiness_gate Verifier Registration

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py`
- Modify: `tests/test_success_verifiers.py`

**Interfaces:**
- Consumes: `readiness_gate.load_readiness_result` (Task 7).
- Produces: `readiness_gate(*, project_root, story_key, output_file, contract) -> dict[str, object]` — checks if a readiness result exists for the story and its verdict is READY. Fail-closed when readiness result is absent. Registered in both `VERIFIERS` dict and `VALID_VERIFIERS` set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_success_verifiers.py`:

```python
from story_automator.core.success_verifiers import readiness_gate as readiness_gate_verifier


class ReadinessGateVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = tempfile.mkdtemp()

    def test_absent_readiness_fails_closed(self) -> None:
        result = readiness_gate_verifier(
            project_root=self.project_root,
            story_key="E1-001",
            contract={},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "readiness_not_checked")

    def test_ready_verdict_succeeds(self) -> None:
        from story_automator.core.readiness_gate import persist_readiness_result
        persist_readiness_result(self.project_root, "E1-001", {
            "verdict": "READY", "priority": "P2",
            "blockers": [], "reason": "ready",
        })
        result = readiness_gate_verifier(
            project_root=self.project_root,
            story_key="E1-001",
            contract={},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["verdict"], "READY")

    def test_blocked_verdict_fails(self) -> None:
        from story_automator.core.readiness_gate import persist_readiness_result
        persist_readiness_result(self.project_root, "E1-001", {
            "verdict": "BLOCKED", "priority": "",
            "blockers": [{"adr_id": "ADR-1"}], "reason": "blocked",
        })
        result = readiness_gate_verifier(
            project_root=self.project_root,
            story_key="E1-001",
            contract={},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "readiness_blocked")

    def test_needs_risk_verdict_fails(self) -> None:
        from story_automator.core.readiness_gate import persist_readiness_result
        persist_readiness_result(self.project_root, "E1-001", {
            "verdict": "NEEDS_RISK", "priority": "",
            "blockers": [], "reason": "no risk",
        })
        result = readiness_gate_verifier(
            project_root=self.project_root,
            story_key="E1-001",
            contract={},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "readiness_needs_risk")

    def test_registered_in_verifiers(self) -> None:
        from story_automator.core.success_verifiers import VERIFIERS
        self.assertIn("readiness_gate", VERIFIERS)

    def test_registered_in_valid_verifiers(self) -> None:
        from story_automator.core.runtime_policy import VALID_VERIFIERS
        self.assertIn("readiness_gate", VALID_VERIFIERS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_success_verifiers.py -v -k "ReadinessGate"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `success_verifiers.py`:

```python
from .readiness_gate import load_readiness_result


def readiness_gate(
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    result = load_readiness_result(project_root, story_key)
    if result is None:
        return {
            "verified": False,
            "reason": "readiness_not_checked",
            "source": "readiness_gate",
        }
    verdict = result.get("verdict", "")
    if verdict == "READY":
        return {
            "verified": True,
            "verdict": verdict,
            "priority": result.get("priority", ""),
            "source": "readiness_gate",
        }
    if verdict == "BLOCKED":
        return {
            "verified": False,
            "reason": "readiness_blocked",
            "verdict": verdict,
            "blockers": result.get("blockers", []),
            "source": "readiness_gate",
        }
    return {
        "verified": False,
        "reason": f"readiness_{verdict.lower()}" if verdict else "readiness_unknown",
        "verdict": verdict,
        "source": "readiness_gate",
    }
```

Add `"readiness_gate": readiness_gate` to the `VERIFIERS` dict in `success_verifiers.py`.

In `runtime_policy.py`, add `"readiness_gate"` to the `VALID_VERIFIERS` set.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_success_verifiers.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/success_verifiers.py \
       skills/bmad-story-automator/src/story_automator/core/runtime_policy.py \
       tests/test_success_verifiers.py
git commit -m "feat(gate): register readiness_gate verifier in VERIFIERS and VALID_VERIFIERS" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: CLI gate readiness Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_orchestrator.run_readiness_gate` (Task 9), `product_profile.load_effective_profile` (existing M1), `readiness_gate.load_readiness_result` (Task 7), `gate_cmd.gate_dispatch` (existing M10).
- Produces:
  - `gate_readiness_action(args) -> int` — CLI: `gate readiness <story_id> [--risk=<risk.json>]`. Runs readiness gate and prints JSON result. Exit 0 for READY, exit 1 for BLOCKED/NEEDS_RISK.
  - Updated `gate_dispatch` to route `"readiness"` subcommand.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_readiness_action


class GateReadinessActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile_path = Path(self.tmp) / "skills" / "bmad-story-automator" / "data" / "profiles"
        self.profile_path.mkdir(parents=True)

    @patch("story_automator.commands.gate_cmd._project_root")
    @patch("story_automator.commands.gate_cmd.load_effective_profile")
    def test_needs_risk_exit_1(self, mock_profile, mock_root) -> None:
        mock_root.return_value = self.tmp
        mock_profile.return_value = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_readiness_action(["E1-001"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(output["verdict"], "NEEDS_RISK")

    @patch("story_automator.commands.gate_cmd._project_root")
    @patch("story_automator.commands.gate_cmd.load_effective_profile")
    def test_ready_exit_0(self, mock_profile, mock_root) -> None:
        mock_root.return_value = self.tmp
        mock_profile.return_value = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        from story_automator.core.risk_profile import make_risk_entry, persist_risk_profile
        persist_risk_profile(self.tmp, "E1-001", [make_risk_entry("TECH", 1, 1)])
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_readiness_action(["E1-001"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["verdict"], "READY")

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_missing_story_id_exit_2(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        code = gate_readiness_action([])
        self.assertEqual(code, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v -k "GateReadiness"`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add imports and the new function to `gate_cmd.py`:

```python
# Add to imports at the top of gate_cmd.py:
import json as _json

from story_automator.core.gate_orchestrator import run_readiness_gate
from story_automator.core.product_profile import load_effective_profile


def gate_readiness_action(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("usage: gate readiness <story_id> [--risk=<risk.json>]", file=sys.stderr)
        return 2

    story_id = args[0]
    project_root = _project_root()
    profile = load_effective_profile(project_root)

    risk_entries = None
    for arg in args[1:]:
        if arg.startswith("--risk="):
            risk_path = arg.split("=", 1)[1]
            try:
                with open(risk_path, encoding="utf-8") as f:
                    risk_entries = _json.load(f)
            except (OSError, _json.JSONDecodeError) as exc:
                print_json({"ok": False, "error": str(exc)})
                return 1

    result = run_readiness_gate(
        project_root, story_id,
        profile=profile, risk_entries=risk_entries,
    )
    print_json(result)
    return 0 if result.get("verdict") == "READY" else 1
```

Add `"readiness"` to the existing `dispatch` dict in `gate_dispatch`:

```python
    dispatch = {
        "status": gate_status_action,
        "resume": gate_resume_action,
        "invalidate": gate_invalidate_action,
        "readiness": gate_readiness_action,
    }
```

And add the readiness line to `_gate_usage`:

```python
    print("  gate readiness <story_id> [--risk=<risk.json>]", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate readiness CLI command with risk file input" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Risk-to-Production-Gate Bridge

**Files:**
- Modify: `tests/test_readiness_integration.py`

**Interfaces:**
- Consumes: `gate_orchestrator.run_readiness_gate` (Task 9), `gate_orchestrator.run_production_gate` (existing M10), `risk_profile.has_unmitigated_risk_9` (Task 2).
- Produces: Integration tests verifying that readiness priority flows correctly into production gate's `priority` parameter and `has_unmitigated_risk_9` flag.

- [ ] **Step 1: Write the integration tests**

Append to `tests/test_readiness_integration.py`:

```python
from unittest.mock import patch, MagicMock
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.risk_profile import has_unmitigated_risk_9


class ReadinessToProductionGateBridgeTests(unittest.TestCase):
    """Verify readiness priority flows into production gate."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_p0_readiness_drives_100pct_coverage(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertEqual(readiness["priority"], "P0")

        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "gate-1", evidence[0])
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-1",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority=readiness["priority"],
        )
        self.assertEqual(gate["overall"], "FAIL")
        correctness = gate["categories"]["correctness"]
        self.assertEqual(correctness["verdict"], "FAIL")
        self.assertIn("coverage", correctness.get("rationale", ""))

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_p3_readiness_allows_20pct_coverage(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("OPS", 1, 1)]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertEqual(readiness["priority"], "P3")

        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 25, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "gate-2", evidence[0])
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-2",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority=readiness["priority"],
        )
        self.assertEqual(gate["overall"], "PASS")

    def test_unmitigated_risk_9_detection(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        self.assertTrue(has_unmitigated_risk_9(entries))

        entries_mitigated = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        self.assertFalse(has_unmitigated_risk_9(entries_mitigated))

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_unmitigated_risk_9_causes_production_gate_fail(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("SEC", 3, 3)]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertTrue(readiness["risk_summary"]["unmitigated_risk_9"])

        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 100, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "gate-3", evidence[0])
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-3",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority="P0",
            has_unmitigated_risk_9=True,
        )
        self.assertEqual(gate["overall"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_readiness_integration.py -v`
Expected: All tests PASS (uses previously implemented code).

- [ ] **Step 3: Commit**

```bash
git add tests/test_readiness_integration.py
git commit -m "test(gate): add readiness-to-production-gate bridge integration tests" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Edge Cases and Boundary Tests

**Files:**
- Modify: `tests/test_risk_profile.py`
- Modify: `tests/test_readiness_gate.py`

**Interfaces:**
- Tests edge cases for all risk profile and readiness gate functions.

- [ ] **Step 1: Write edge case tests**

Append to `tests/test_risk_profile.py`:

```python
class RiskProfileEdgeCaseTests(unittest.TestCase):
    def test_all_categories_covered(self) -> None:
        entries = [
            make_risk_entry(cat, 1, 1)
            for cat in sorted(VALID_RISK_CATEGORIES)
        ]
        validate_risk_profile(entries)
        self.assertEqual(len(entries), 6)

    def test_single_entry_min_score(self) -> None:
        entry = make_risk_entry("TECH", 1, 1)
        self.assertEqual(entry["score"], 1)
        self.assertEqual(risk_score_to_priority(1), "P3")

    def test_single_entry_max_score(self) -> None:
        entry = make_risk_entry("SEC", 3, 3)
        self.assertEqual(entry["score"], 9)
        self.assertEqual(risk_score_to_priority(9), "P0")

    def test_persist_and_load_roundtrip(self) -> None:
        tmp = tempfile.mkdtemp()
        entries = [
            make_risk_entry("TECH", 2, 3, rationale="complex migration"),
            make_risk_entry("SEC", 3, 3, rationale="auth rewrite"),
            make_risk_entry("PERF", 1, 2),
        ]
        persist_risk_profile(tmp, "E2-005", entries)
        loaded = load_risk_profile(tmp, "E2-005")
        self.assertEqual(len(loaded["entries"]), 3)
        for orig, loaded_entry in zip(entries, loaded["entries"]):
            self.assertEqual(orig["category"], loaded_entry["category"])
            self.assertEqual(orig["score"], loaded_entry["score"])

    def test_evidence_confidence_range(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        for confidence in (1, 5, 10):
            evidence = risk_profile_to_evidence(entries, "E1-001", confidence=confidence)
            self.assertEqual(evidence["confidence"], confidence)

    def test_evidence_invalid_confidence_raises(self) -> None:
        from story_automator.core.gate_schema import GateSchemaError
        entries = [make_risk_entry("DATA", 2, 2)]
        with self.assertRaises(GateSchemaError):
            risk_profile_to_evidence(entries, "E1-001", confidence=0)
        with self.assertRaises(GateSchemaError):
            risk_profile_to_evidence(entries, "E1-001", confidence=11)
```

Append to `tests/test_readiness_gate.py`:

```python
class ReadinessEdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness", "security"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_empty_risk_entries_list_treated_as_needs_risk(self) -> None:
        result = check_readiness("E1-001", profile=self.profile, risk_entries=[])
        self.assertEqual(result["verdict"], "NEEDS_RISK")

    def test_multiple_blockers_all_reported(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {
            "ADR-1": ["E1-*"],
            "ADR-2": ["E1-*"],
            "ADR-3": ["E2-*"],
        }
        entries = [make_risk_entry("TECH", 1, 1)]
        result = check_readiness(
            "E1-001", profile=profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(len(result["blockers"]), 2)

    def test_readiness_requirements_match_profile_matrix(self) -> None:
        entries = [make_risk_entry("TECH", 2, 3)]  # score=6 → P1
        result = check_readiness(
            "E1-001", profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P1")
        self.assertEqual(result["requirements"]["coverage_pct"], 90)
        self.assertEqual(result["requirements"]["levels"], ["unit", "integration", "api"])

    def test_persist_and_load_blocked_result(self) -> None:
        tmp = tempfile.mkdtemp()
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        entries = [make_risk_entry("TECH", 1, 1)]
        result = check_readiness("E1-001", profile=profile, risk_entries=entries)
        persist_readiness_result(tmp, "E1-001", result)
        loaded = load_readiness_result(tmp, "E1-001")
        self.assertEqual(loaded["verdict"], "BLOCKED")
        self.assertEqual(len(loaded["blockers"]), 1)
```

- [ ] **Step 2: Run all tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_risk_profile.py tests/test_readiness_gate.py tests/test_readiness_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_risk_profile.py tests/test_readiness_gate.py
git commit -m "test(gate): add edge case and boundary tests for risk profile and readiness gate" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Full Test Suite Validation

**Files:** None (validation only).

**Goal:** Run the entire test suite to ensure no regressions across the 115+ existing test files.

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests PASS, 0 failures.

- [ ] **Step 2: Run ruff lint**

Run: `cd skills/bmad-story-automator && python3 -m ruff check src/story_automator/core/risk_profile.py src/story_automator/core/readiness_gate.py`
Expected: No lint errors.

- [ ] **Step 3: Check LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/risk_profile.py skills/bmad-story-automator/src/story_automator/core/readiness_gate.py`
Expected: Both under 500 LOC.

- [ ] **Step 4: Commit any lint fixes if needed**

```bash
git add -A && git commit -m "fix(gate): address lint findings in M12 risk-readiness modules" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md`

**Goal:** Update the module map to include the new M12 risk-readiness modules.

- [ ] **Step 1: Add M12 modules to CLAUDE.md module map**

Add to the Gate subsystem section after the M10 orchestrator wiring entry:

```
- **Risk-scored readiness (m12)** `core/risk_profile.py` (`VALID_RISK_CATEGORIES`, `RiskProfileError`, `make_risk_entry`, `validate_risk_entry`, `validate_risk_profile`, `risk_score_to_priority`, `aggregate_risk_priority`, `has_unmitigated_risk_9`, `persist_risk_profile`, `load_risk_profile`, `risk_profile_exists`, `risk_profile_to_evidence`, `compute_risk_profile_ref`; `DEFAULT_RISK_THRESHOLDS`), `core/readiness_gate.py` (`READINESS_VERDICTS`, `resolve_story_blockers`, `format_blocker_summary`, `check_readiness`, `persist_readiness_result`, `load_readiness_result`). `run_readiness_gate` added to `gate_orchestrator.py`; `readiness_gate` verifier registered in `success_verifiers.py` VERIFIERS and `runtime_policy.py` VALID_VERIFIERS; `gate readiness` CLI subcommand added to `gate_cmd.py`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with M12 risk-readiness module map" \
  --trailer "Generated-By: claude-opus-4-6"
```
