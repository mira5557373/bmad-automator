# Integration M10: Orchestrator Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the production-readiness gate into the existing orchestrator loop so the gate becomes the single authority for `review → done`. Implements the §9.1 step map, §9.2 control flow (resumable, remediator, park-and-continue), registers the `production_ready_gate` verifier, ships gate CLI commands, and delivers the operator runbook (§11).

**Architecture:** Three new modules plus surgical modifications to existing orchestrator infrastructure:
- `gate_orchestrator.py` (~350 LOC) — main gate lifecycle: crash recovery, reuse validation, drift detection, collect→adjudicate→route, atomic marker semantics.
- `gate_status.py` (~250 LOC) — park/resume/invalidate state management, mitigation-debt tracking, parked-story listing.
- `gate_cmd.py` (~300 LOC) — CLI commands: `gate status`, `gate resume`, `gate invalidate`.

**Dependency graph:** All existing m1-m9 modules consumed but NOT modified except for registration in `runtime_policy.py` (VALID_VERIFIERS), `success_verifiers.py` (VERIFIERS), `gate_audit.py` (new events), and `orchestrator.py` (dispatch wiring). Import direction: `gate_status.py` → `gate_orchestrator.py` → `gate_cmd.py` (strictly unidirectional — `gate_status.py` NEVER imports from `gate_orchestrator.py`).

**Key existing interfaces consumed:**
- `evidence_io.py`: `write_gate_marker`, `read_gate_marker`, `clear_gate_marker`, `can_reuse_gate_file`, `load_gate_file`, `load_evidence_bundle`
- `verdict_engine.py`: `evaluate_gate`, `adjudicate`, `build_gate_file`
- `collector_runner.py`: `run_gate_collectors`
- `trust_boundary.py`: `assert_host_context`, `resolve_host_evidence_dir`
- `product_profile.py`: `load_effective_profile`, `compute_profile_hash`
- `gate_audit.py`: `emit_gate_audit`, all audit event types
- `gate_rules.py`: `aggregate_verdicts`, `validate_waiver_for_gate`
- `collector_registry.py`: `CollectorRegistry`, `applicable`
- `success_verifiers.py`: `VERIFIERS` dict pattern
- `runtime_policy.py`: `VALID_VERIFIERS`, `review_max_cycles`, `crash_max_retries`

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT modify existing m1-m9 module logic** except: `runtime_policy.py` (add to VALID_VERIFIERS set), `success_verifiers.py` (add to VERIFIERS dict), `gate_audit.py` (new audit events), `commands/orchestrator.py` (dispatch wiring).
- **500-LOC soft limit per Python module.** `gate_orchestrator.py` target ~350 LOC; `gate_status.py` ~250 LOC; `gate_cmd.py` ~300 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path; use `os.replace` via `write_atomic` for atomic writes.
- **factory_version**: read from `story_automator.__version__` (`"1.15.0"` currently).

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — gate lifecycle orchestration (~350 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_status.py` — park/resume/invalidate/mitigation-debt (~250 LOC)
- `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py` — CLI gate subcommands (~300 LOC)
- `tests/test_gate_orchestrator.py` — unit tests (~400 LOC)
- `tests/test_gate_status.py` — unit tests (~350 LOC)
- `tests/test_gate_cmd.py` — CLI tests (~300 LOC)
- `tests/test_gate_m10_integration.py` — integration tests (~250 LOC)
- `docs/operations/gate-troubleshooting.md` — operator runbook

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` — add `"production_ready_gate"` to `VALID_VERIFIERS` set (~1 line)
- `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py` — add `production_ready_gate` function + register in `VERIFIERS` (~+35 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — add `GateProfileDriftAudit`, `GateParkedAudit` events (~+40 LOC)
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` — add `gate` dispatch (~+10 LOC)
- `tests/test_success_verifiers.py` — add tests for new verifier (~+60 LOC)
- `tests/test_gate_audit.py` — add tests for new audit events (~+30 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/verdict_engine.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`, `core/product_profile.py`, `core/category_rules.py`.

---

### Task 1: GateProfileDrift + GateParked Audit Events

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing `emit_gate_audit` pattern, frozen dataclass protocol.
- Produces:
  - `GateProfileDriftAudit` — emitted when gate reuse is rejected due to profile.hash or factory_version mismatch. Fields: `gate_id`, `old_hash`, `new_hash`, `old_factory_version`, `new_factory_version`, `reason`.
  - `GateParkedAudit` — emitted when a story is parked due to exhaustion/risk-9. Fields: `gate_id`, `story_key`, `reason`, `overall_verdict`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
from story_automator.core.gate_audit import (
    GateProfileDriftAudit,
    GateParkedAudit,
)


class GateProfileDriftAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateProfileDriftAudit(
            gate_id="g1", old_hash="aabb", new_hash="ccdd",
            old_factory_version="1.14.0", new_factory_version="1.15.0",
            reason="profile.hash mismatch",
        )
        self.assertEqual(event.event_name, "GateProfileDrift")

    def test_to_dict_contains_all_fields(self) -> None:
        event = GateProfileDriftAudit(
            gate_id="g1", old_hash="aabb", new_hash="ccdd",
            old_factory_version="1.14.0", new_factory_version="1.15.0",
            reason="profile.hash mismatch",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["old_hash"], "aabb")
        self.assertEqual(d["new_hash"], "ccdd")
        self.assertEqual(d["reason"], "profile.hash mismatch")

    def test_frozen(self) -> None:
        event = GateProfileDriftAudit(gate_id="g1")
        with self.assertRaises(AttributeError):
            event.gate_id = "g2"


class GateParkedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateParkedAudit(
            gate_id="g1", story_key="E1-001", reason="exhausted",
            overall_verdict="FAIL",
        )
        self.assertEqual(event.event_name, "GateParked")

    def test_to_dict(self) -> None:
        event = GateParkedAudit(
            gate_id="g1", story_key="E1-001", reason="risk-9",
            overall_verdict="FAIL",
        )
        d = event.to_dict()
        self.assertEqual(d["story_key"], "E1-001")
        self.assertEqual(d["reason"], "risk-9")
        self.assertEqual(d["overall_verdict"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v -k "Drift or Parked"`
Expected: ImportError — `GateProfileDriftAudit`, `GateParkedAudit` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` (before the `_AuditEvent` union):

```python
@dataclasses.dataclass(frozen=True)
class GateProfileDriftAudit:
    """Audit event: gate reuse rejected due to profile/version drift."""
    event_name: str = dataclasses.field(default="GateProfileDrift", init=False)
    gate_id: str = ""
    old_hash: str = ""
    new_hash: str = ""
    old_factory_version: str = ""
    new_factory_version: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "old_factory_version": self.old_factory_version,
            "new_factory_version": self.new_factory_version,
            "reason": self.reason,
        }


@dataclasses.dataclass(frozen=True)
class GateParkedAudit:
    """Audit event: story parked due to exhaustion or unmitigated risk-9."""
    event_name: str = dataclasses.field(default="GateParked", init=False)
    gate_id: str = ""
    story_key: str = ""
    reason: str = ""
    overall_verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "story_key": self.story_key,
            "reason": self.reason,
            "overall_verdict": self.overall_verdict,
        }
```

Update the `_AuditEvent` union type and `__all__` to include the new types.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add GateProfileDrift and GateParked audit events" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: production_ready_gate Verifier

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py`
- Modify: `tests/test_success_verifiers.py`

**Interfaces:**
- Consumes: `evidence_io.load_gate_file` (from m2), `gate_schema.GateSchemaError` (from m2), `trust_boundary.resolve_host_evidence_dir` (from m3).
- Produces: `production_ready_gate(*, project_root, story_key, output_file, contract) -> dict[str, object]` — checks if a gate file exists for the story target, verifies overall verdict is PASS/CONCERNS/WAIVED (not FAIL), fail-closed when gate file is absent. Registered in both `VERIFIERS` dict and `VALID_VERIFIERS` set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_success_verifiers.py`:

```python
from story_automator.core.success_verifiers import production_ready_gate
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class ProductionReadyGateVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = tempfile.mkdtemp()

    def _write_gate_file(self, overall: str) -> None:
        categories = {"correctness": {
            "verdict": overall, "required": {}, "actual": {},
            "rationale": "test",
        }}
        gate = make_gate_file(
            gate_id="test-gate",
            target={"kind": "story", "id": "E1-001-my-story"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories=categories,
            overall=overall,
        )
        persist_gate_file(self.project_root, gate)

    def test_absent_gate_file_fails_closed(self) -> None:
        result = production_ready_gate(
            project_root=self.project_root,
            story_key="E1-001-my-story",
            contract={},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "gate_file_absent")

    def test_pass_verdict_succeeds(self) -> None:
        self._write_gate_file("PASS")
        result = production_ready_gate(
            project_root=self.project_root,
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": "test-gate"}},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["overall"], "PASS")

    def test_concerns_verdict_succeeds_with_note(self) -> None:
        self._write_gate_file("CONCERNS")
        result = production_ready_gate(
            project_root=self.project_root,
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": "test-gate"}},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["overall"], "CONCERNS")
        self.assertIn("mitigation_debt", result)

    def test_fail_verdict_fails(self) -> None:
        self._write_gate_file("FAIL")
        result = production_ready_gate(
            project_root=self.project_root,
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": "test-gate"}},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "gate_verdict_fail")

    def test_waived_verdict_succeeds(self) -> None:
        self._write_gate_file("WAIVED")
        result = production_ready_gate(
            project_root=self.project_root,
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": "test-gate"}},
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["overall"], "WAIVED")

    def test_registered_in_verifiers(self) -> None:
        from story_automator.core.success_verifiers import VERIFIERS
        self.assertIn("production_ready_gate", VERIFIERS)

    def test_registered_in_valid_verifiers(self) -> None:
        from story_automator.core.runtime_policy import VALID_VERIFIERS
        self.assertIn("production_ready_gate", VALID_VERIFIERS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_success_verifiers.py -v -k "ProductionReady"`
Expected: ImportError — `production_ready_gate` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `success_verifiers.py`:

```python
from .evidence_io import load_gate_file
from .gate_schema import GateSchemaError


def production_ready_gate(
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    config = _success_config(contract)
    gate_id = str(config.get("gate_id") or "").strip()
    if not gate_id:
        return {"verified": False, "reason": "gate_file_absent", "source": "production_ready_gate"}
    try:
        gate_file = load_gate_file(project_root, gate_id)
    except (GateSchemaError, FileNotFoundError):
        return {"verified": False, "reason": "gate_file_absent", "source": "production_ready_gate"}
    overall = gate_file.get("overall", "FAIL")
    if overall == "FAIL":
        return {
            "verified": False,
            "reason": "gate_verdict_fail",
            "overall": overall,
            "source": "production_ready_gate",
            "gate_id": gate_id,
        }
    payload: dict[str, object] = {
        "verified": True,
        "overall": overall,
        "source": "production_ready_gate",
        "gate_id": gate_id,
        "story": story_key,
    }
    if overall == "CONCERNS":
        failing = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        payload["mitigation_debt"] = failing
    return payload
```

Add `"production_ready_gate": production_ready_gate` to the `VERIFIERS` dict.

In `runtime_policy.py`, add `"production_ready_gate"` to the `VALID_VERIFIERS` set:
```python
VALID_VERIFIERS = {"create_story_artifact", "session_exit", "review_completion", "epic_complete", "production_ready_gate"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_success_verifiers.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/success_verifiers.py \
       skills/bmad-story-automator/src/story_automator/core/runtime_policy.py \
       tests/test_success_verifiers.py
git commit -m "feat(gate): register production_ready_gate verifier in VERIFIERS and VALID_VERIFIERS" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Gate Status Persistence — Mitigation Debt

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_status.py`
- Create: `tests/test_gate_status.py`

**Interfaces:**
- Consumes: `utils.ensure_dir`, `utils.write_atomic`, `utils.iso_now`, `gate_schema.canonical_json`, `trust_boundary.assert_host_context`.
- Produces:
  - `record_mitigation_debt(project_root, gate_id, story_key, categories: list[str]) -> Path` — persists a mitigation-debt annotation under `_bmad/gate/mitigation/<gate_id>.json`. Records which categories had CONCERNS, timestamped for tracking.
  - `load_mitigation_debt(project_root) -> list[dict]` — loads all outstanding mitigation-debt records.
  - `clear_mitigation_debt(project_root, gate_id) -> bool` — removes a mitigation-debt record (operator/retro clears it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_status.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.gate_status import (
    record_mitigation_debt,
    load_mitigation_debt,
    clear_mitigation_debt,
)


class MitigationDebtTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_record_creates_file(self) -> None:
        path = record_mitigation_debt(
            self.tmp, "gate-1", "E1-001", ["security", "static"],
        )
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["gate_id"], "gate-1")
        self.assertEqual(data["story_key"], "E1-001")
        self.assertEqual(data["categories"], ["security", "static"])
        self.assertIn("recorded_at", data)

    def test_load_returns_all_records(self) -> None:
        record_mitigation_debt(self.tmp, "gate-1", "E1-001", ["security"])
        record_mitigation_debt(self.tmp, "gate-2", "E1-002", ["static"])
        records = load_mitigation_debt(self.tmp)
        self.assertEqual(len(records), 2)

    def test_load_empty_returns_empty(self) -> None:
        self.assertEqual(load_mitigation_debt(self.tmp), [])

    def test_clear_removes_record(self) -> None:
        record_mitigation_debt(self.tmp, "gate-1", "E1-001", ["security"])
        self.assertTrue(clear_mitigation_debt(self.tmp, "gate-1"))
        self.assertEqual(load_mitigation_debt(self.tmp), [])

    def test_clear_nonexistent_returns_false(self) -> None:
        self.assertFalse(clear_mitigation_debt(self.tmp, "no-such"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py::MitigationDebtTests -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/gate_status.py`:

```python
"""Gate status persistence — park/resume/invalidate/mitigation-debt.

Manages gate lifecycle state beyond the single-evaluation scope:
parked stories, mitigation-debt tracking, and gate invalidation.
Artifacts live under _bmad/gate/{parked,mitigation}/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic

_MITIGATION_DIR = "mitigation"


def _mitigation_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _MITIGATION_DIR


def record_mitigation_debt(
    project_root: str | Path,
    gate_id: str,
    story_key: str,
    categories: list[str],
) -> Path:
    assert_host_context("record_mitigation_debt")
    debt_dir = _mitigation_dir(project_root)
    ensure_dir(debt_dir)
    record = {
        "gate_id": gate_id,
        "story_key": story_key,
        "categories": categories,
        "recorded_at": iso_now(),
    }
    target = debt_dir / f"{gate_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_mitigation_debt(project_root: str | Path) -> list[dict[str, Any]]:
    debt_dir = _mitigation_dir(project_root)
    if not debt_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(debt_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def clear_mitigation_debt(project_root: str | Path, gate_id: str) -> bool:
    assert_host_context("clear_mitigation_debt")
    target = _mitigation_dir(project_root) / f"{gate_id}.json"
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_status.py tests/test_gate_status.py
git commit -m "feat(gate): add mitigation-debt persistence for CONCERNS verdicts" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Gate Status Persistence — Park and Resume

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_status.py`
- Modify: `tests/test_gate_status.py`

**Interfaces:**
- Consumes: same as Task 3 + `gate_audit.emit_gate_audit`, `gate_audit.GateParkedAudit`.
- Produces:
  - `park_story(project_root, gate_id, story_key, reason, overall_verdict, *, audit_policy=None, audit_path=None) -> Path` — writes a parked-story record to `_bmad/gate/parked/<gate_id>.json`. Emits `GateParkedAudit`.
  - `list_parked(project_root, *, state_filter=None) -> list[dict]` — lists all parked stories, optionally filtered.
  - `resume_story(project_root, gate_id) -> dict | None` — removes parked record, returns the record data for the caller to re-queue. Returns None if not found.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_status.py`:

```python
from story_automator.core.gate_status import (
    park_story,
    list_parked,
    resume_story,
)


class ParkResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_park_creates_record(self) -> None:
        path = park_story(
            self.tmp, "gate-1", "E1-001", "exhausted", "FAIL",
        )
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["gate_id"], "gate-1")
        self.assertEqual(data["story_key"], "E1-001")
        self.assertEqual(data["reason"], "exhausted")
        self.assertEqual(data["overall_verdict"], "FAIL")
        self.assertIn("parked_at", data)

    def test_list_parked_returns_all(self) -> None:
        park_story(self.tmp, "gate-1", "E1-001", "exhausted", "FAIL")
        park_story(self.tmp, "gate-2", "E1-002", "risk-9", "FAIL")
        parked = list_parked(self.tmp)
        self.assertEqual(len(parked), 2)

    def test_list_parked_empty(self) -> None:
        self.assertEqual(list_parked(self.tmp), [])

    def test_resume_removes_and_returns(self) -> None:
        park_story(self.tmp, "gate-1", "E1-001", "exhausted", "FAIL")
        record = resume_story(self.tmp, "gate-1")
        self.assertIsNotNone(record)
        self.assertEqual(record["story_key"], "E1-001")
        self.assertEqual(list_parked(self.tmp), [])

    def test_resume_nonexistent_returns_none(self) -> None:
        self.assertIsNone(resume_story(self.tmp, "no-such"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py::ParkResumeTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_status.py`:

```python
from .gate_audit import GateParkedAudit, emit_gate_audit
import pathlib

_PARKED_DIR = "parked"


def _parked_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _PARKED_DIR


def park_story(
    project_root: str | Path,
    gate_id: str,
    story_key: str,
    reason: str,
    overall_verdict: str,
    *,
    audit_policy: dict[str, Any] | None = None,
    audit_path: pathlib.Path | None = None,
) -> Path:
    assert_host_context("park_story")
    parked_d = _parked_dir(project_root)
    ensure_dir(parked_d)
    record = {
        "gate_id": gate_id,
        "story_key": story_key,
        "reason": reason,
        "overall_verdict": overall_verdict,
        "parked_at": iso_now(),
    }
    target = parked_d / f"{gate_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateParkedAudit(
                gate_id=gate_id, story_key=story_key,
                reason=reason, overall_verdict=overall_verdict,
            ),
        )
    return target


def list_parked(project_root: str | Path, *, state_filter: str | None = None) -> list[dict[str, Any]]:
    parked_d = _parked_dir(project_root)
    if not parked_d.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(parked_d.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if state_filter is None or data.get("reason") == state_filter:
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def resume_story(project_root: str | Path, gate_id: str) -> dict[str, Any] | None:
    assert_host_context("resume_story")
    target = _parked_dir(project_root) / f"{gate_id}.json"
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    return data if isinstance(data, dict) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_status.py tests/test_gate_status.py
git commit -m "feat(gate): add park/resume/list state management for parked stories" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Gate Invalidation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_status.py`
- Modify: `tests/test_gate_status.py`

**Interfaces:**
- Consumes: `evidence_io.load_gate_file`, `gate_schema.GateSchemaError`.
- Produces:
  - `invalidate_gate(project_root, gate_id) -> tuple[bool, str]` — marks a gate file as invalidated by renaming `verdicts/<gate_id>.json` to `verdicts/<gate_id>.invalidated.json`. Returns `(success, reason)`. §9.2: forces re-evaluation on next run.
  - `invalidate_gates_for_target(project_root, target_id) -> list[str]` — invalidates all gate files whose `target.id` matches. For `gate invalidate <story|epic>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_status.py`:

```python
from story_automator.core.gate_status import (
    invalidate_gate,
    invalidate_gates_for_target,
)
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class InvalidateGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str = "story-1") -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc123",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

    def test_invalidate_existing_gate(self) -> None:
        self._create_gate("gate-1")
        ok, reason = invalidate_gate(self.tmp, "gate-1")
        self.assertTrue(ok)
        verdicts = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        self.assertFalse((verdicts / "gate-1.json").exists())
        self.assertTrue((verdicts / "gate-1.invalidated.json").exists())

    def test_invalidate_nonexistent_returns_false(self) -> None:
        ok, reason = invalidate_gate(self.tmp, "no-such")
        self.assertFalse(ok)
        self.assertIn("not found", reason)

    def test_invalidate_for_target(self) -> None:
        self._create_gate("gate-1", "story-1")
        self._create_gate("gate-2", "story-1")
        self._create_gate("gate-3", "story-2")
        invalidated = invalidate_gates_for_target(self.tmp, "story-1")
        self.assertEqual(len(invalidated), 2)
        self.assertIn("gate-1", invalidated)
        self.assertIn("gate-2", invalidated)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py::InvalidateGateTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_status.py`:

```python
def invalidate_gate(project_root: str | Path, gate_id: str) -> tuple[bool, str]:
    assert_host_context("invalidate_gate")
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    source = verdicts_dir / f"{gate_id}.json"
    if not source.is_file():
        return False, f"gate file not found: {gate_id}"
    dest = verdicts_dir / f"{gate_id}.invalidated.json"
    source.rename(dest)
    return True, f"invalidated {gate_id}"


def invalidate_gates_for_target(
    project_root: str | Path, target_id: str,
) -> list[str]:
    assert_host_context("invalidate_gates_for_target")
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    if not verdicts_dir.is_dir():
        return []
    invalidated: list[str] = []
    for path in sorted(verdicts_dir.glob("*.json")):
        if path.name.endswith(".invalidated.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        target = data.get("target", {})
        if target.get("id") == target_id or target.get("epic") == target_id:
            gate_id = path.stem
            ok, _ = invalidate_gate(project_root, gate_id)
            if ok:
                invalidated.append(gate_id)
    return invalidated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_status.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_status.py tests/test_gate_status.py
git commit -m "feat(gate): add gate invalidation with target-scoped bulk invalidate" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Gate Reuse Check with Drift Detection

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Create: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `evidence_io.can_reuse_gate_file`, `evidence_io.load_gate_file`, `gate_audit.GateProfileDriftAudit`, `gate_audit.emit_gate_audit`, `product_profile.compute_profile_hash`.
- Produces: `check_gate_reuse(project_root, gate_id, commit_sha, profile, factory_version, *, audit_policy=None, audit_path=None) -> tuple[dict | None, str]` — checks if an existing gate file can be reused. Returns `(gate_file_or_None, reason)`. When rejected due to drift, emits `GateProfileDriftAudit` naming old/new hashes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_orchestrator.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_orchestrator import check_gate_reuse
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class CheckGateReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {"id": "test", "version": 1}

    def _create_gate(self, gate_id: str, commit_sha: str = "abc",
                     profile_hash: str = "aabb", factory_version: str = "1.15.0") -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": "s1"},
            commit_sha=commit_sha,
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version=factory_version,
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

    def test_reuse_when_all_match(self) -> None:
        self._create_gate("g1", "abc", "aabb", "1.15.0")
        gate, reason = check_gate_reuse(
            self.tmp, "g1", "abc", self.profile, "1.15.0",
        )
        self.assertIsNotNone(gate)
        self.assertEqual(gate["overall"], "PASS")

    def test_reject_on_commit_sha_mismatch(self) -> None:
        self._create_gate("g1", "abc", "aabb", "1.15.0")
        gate, reason = check_gate_reuse(
            self.tmp, "g1", "def", self.profile, "1.15.0",
        )
        self.assertIsNone(gate)
        self.assertIn("commit_sha", reason)

    def test_reject_on_profile_hash_mismatch(self) -> None:
        self._create_gate("g1", "abc", "aabb", "1.15.0")
        gate, reason = check_gate_reuse(
            self.tmp, "g1", "abc", self.profile, "1.15.0",
        )
        # profile hash computed from self.profile won't match "aabb"
        # (which was hard-coded in _create_gate)
        # This verifies drift detection works
        self.assertIsNone(gate)

    def test_reject_on_factory_version_mismatch(self) -> None:
        self._create_gate("g1", "abc", "aabb", "1.14.0")
        gate, reason = check_gate_reuse(
            self.tmp, "g1", "abc", self.profile, "1.15.0",
        )
        self.assertIsNone(gate)
        self.assertIn("factory_version", reason)

    def test_missing_gate_returns_none(self) -> None:
        gate, reason = check_gate_reuse(
            self.tmp, "no-such", "abc", self.profile, "1.15.0",
        )
        self.assertIsNone(gate)
        self.assertIn("not found", reason.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::CheckGateReuseTests -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`:

```python
"""Gate orchestrator — lifecycle management for production-readiness gate.

Wires the gate step into the orchestrator loop (§9.1, §9.2):
crash recovery, reuse validation, drift detection, collect → adjudicate
→ verdict routing, and atomic-marker semantics.
"""
from __future__ import annotations

import pathlib
from typing import Any

from .evidence_io import (
    can_reuse_gate_file,
    load_gate_file,
)
from .gate_audit import (
    GateProfileDriftAudit,
    emit_gate_audit,
)
from .gate_schema import GateSchemaError
from .product_profile import compute_profile_hash
from .trust_boundary import assert_host_context


def check_gate_reuse(
    project_root: str | pathlib.Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    factory_version: str,
    *,
    audit_policy: dict[str, Any] | None = None,
    audit_path: pathlib.Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """§9.2: check if existing gate file can be reused.

    Returns (gate_file, "") on reuse, (None, reason) on rejection.
    Emits GateProfileDriftAudit on hash/version mismatch.
    """
    try:
        gate_file = load_gate_file(project_root, gate_id)
    except GateSchemaError:
        return None, f"gate file not found or invalid: {gate_id}"

    current_hash = compute_profile_hash(profile)
    reusable, reason = can_reuse_gate_file(
        gate_file,
        commit_sha=commit_sha,
        profile_hash=current_hash,
        factory_version=factory_version,
    )

    if reusable:
        return gate_file, ""

    if audit_policy is not None and audit_path is not None:
        old_hash = (gate_file.get("profile") or {}).get("hash", "")
        old_fv = gate_file.get("factory_version", "")
        emit_gate_audit(
            audit_policy, audit_path,
            GateProfileDriftAudit(
                gate_id=gate_id,
                old_hash=old_hash,
                new_hash=current_hash,
                old_factory_version=old_fv,
                new_factory_version=factory_version,
                reason=reason,
            ),
        )
    return None, reason
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add gate reuse check with profile-drift audit emission" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Crash Recovery

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `evidence_io.read_gate_marker`, `evidence_io.clear_gate_marker`, `trust_boundary.assert_host_context`.
- Produces: `recover_from_crash(project_root) -> dict[str, Any]` — §9.2 atomic-gate crash semantics. Checks for `gate-in-progress.json` marker. If found AND no final verdict exists, deletes partial evidence bundle, removes marker, and returns `{"recovered": True, "gate_id": ...}`. If marker absent, returns `{"recovered": False}`. Fail-closed: always re-runs from scratch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
from story_automator.core.gate_orchestrator import recover_from_crash
from story_automator.core.evidence_io import write_gate_marker


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_no_marker_returns_not_recovered(self) -> None:
        result = recover_from_crash(self.tmp)
        self.assertFalse(result["recovered"])

    def test_marker_without_verdict_cleans_up(self) -> None:
        write_gate_marker(self.tmp, "gate-1", "abc123")
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "gate-1"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "test.json").write_text("{}")
        result = recover_from_crash(self.tmp)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "gate-1")
        self.assertFalse(evidence_dir.exists())
        marker = Path(self.tmp) / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.exists())

    def test_marker_with_existing_verdict_clears_marker_only(self) -> None:
        write_gate_marker(self.tmp, "gate-1", "abc123")
        verdicts_dir = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        verdicts_dir.mkdir(parents=True, exist_ok=True)
        gate_file = make_gate_file(
            gate_id="gate-1", target={"kind": "story", "id": "s1"},
            commit_sha="abc123",
            profile={"id": "t", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate_file)
        result = recover_from_crash(self.tmp)
        self.assertTrue(result["recovered"])
        self.assertTrue((verdicts_dir / "gate-1.json").exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::CrashRecoveryTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
import shutil

from .evidence_io import (
    clear_gate_marker,
    read_gate_marker,
)


def recover_from_crash(project_root: str | pathlib.Path) -> dict[str, Any]:
    """§9.2: atomic-gate crash recovery.

    If gate-in-progress marker exists but no verdict, delete partial
    evidence and remove marker. Fail-closed: re-run from scratch.
    """
    assert_host_context("recover_from_crash")
    marker = read_gate_marker(project_root)
    if marker is None:
        return {"recovered": False}

    gate_id = marker.get("gate_id", "")
    verdicts_path = (
        pathlib.Path(project_root) / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    )
    evidence_dir = (
        pathlib.Path(project_root) / "_bmad" / "gate" / "evidence" / gate_id
    )

    if not verdicts_path.is_file() and evidence_dir.is_dir():
        shutil.rmtree(evidence_dir, ignore_errors=True)

    clear_gate_marker(project_root)
    return {
        "recovered": True,
        "gate_id": gate_id,
        "had_verdict": verdicts_path.is_file(),
        "commit_sha": marker.get("commit_sha", ""),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add atomic-gate crash recovery with fail-closed semantics" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Core Gate Orchestration — run_production_gate

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `recover_from_crash` (Task 7), `check_gate_reuse` (Task 6), `evidence_io.write_gate_marker`/`clear_gate_marker`, `collector_runner.run_gate_collectors`, `verdict_engine.evaluate_gate`, `gate_audit.GateStartedAudit`/`emit_gate_audit`.
- Produces: `run_production_gate(project_root, gate_id, *, commit_sha, target, profile, factory_version, registry, priority, waivers, audit_policy, audit_path) -> dict[str, Any]` — Full gate lifecycle:
  1. Crash recovery check
  2. Reuse check (return cached if valid)
  3. Write gate-in-progress marker
  4. Run collectors
  5. Evaluate gate (adjudicate + build gate file + persist)
  6. Clear marker
  7. Return gate file

- [ ] **Step 1: Write the failing tests**

**IMPORTANT: Mocking strategy.** `run_gate_collectors` persists evidence to disk via `run_single_collector` → `persist_evidence_record`. When `_run_collectors` is mocked, no evidence reaches disk, so `evaluate_gate` → `load_evidence_bundle` finds nothing and fails closed. Tests MUST persist evidence records to disk in setUp/arrange, then mock `_run_collectors` to no-op (prevent real subprocess calls). The mock return value is ignored by `run_production_gate`.

Append to `tests/test_gate_orchestrator.py`:

```python
from unittest.mock import MagicMock, patch
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.evidence_io import persist_evidence_record, persist_gate_file
from story_automator.core.product_profile import compute_profile_hash


class RunProductionGateTests(unittest.TestCase):
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
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
        }
        self.registry = CollectorRegistry()

    def _persist_evidence(self, gate_id: str, records: list[dict]) -> None:
        """Persist evidence to disk so evaluate_gate can load it."""
        for record in records:
            persist_evidence_record(self.tmp, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_full_lifecycle_pass(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-test", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "gate-test",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "PASS")
        marker = Path(self.tmp) / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.exists())

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_on_success(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-test", evidence)
        mock_run.return_value = []
        run_production_gate(
            self.tmp, "gate-test", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        marker_path = Path(self.tmp) / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker_path.exists())

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_on_failure(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="error", findings=["crash"],
        )]
        self._persist_evidence("gate-test", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "gate-test", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")
        marker_path = Path(self.tmp) / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker_path.exists())

    def test_reuse_returns_cached_gate(self) -> None:
        gate = make_gate_file(
            gate_id="gate-test",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": compute_profile_hash(self.profile)},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = run_production_gate(
            self.tmp, "gate-test", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(result["overall"], "PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::RunProductionGateTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
from .collector_runner import run_gate_collectors
from .collector_registry import CollectorRegistry
from .evidence_io import (
    write_gate_marker,
    load_evidence_bundle,
    persist_evidence_record,
)
from .gate_audit import GateStartedAudit
from .verdict_engine import evaluate_gate


def _run_collectors(
    project_root, gate_id, commit_sha, profile, registry,
    *, diff_categories=None, audit_policy=None, audit_path=None,
):
    """Wrapper for testability — delegates to run_gate_collectors."""
    return run_gate_collectors(
        project_root, gate_id, commit_sha, profile, registry,
        diff_categories=diff_categories,
        audit_policy=audit_policy, audit_path=audit_path,
    )


def run_production_gate(
    project_root: str | pathlib.Path,
    gate_id: str,
    *,
    commit_sha: str,
    target: dict[str, str],
    profile: dict[str, Any],
    factory_version: str,
    registry: CollectorRegistry,
    priority: str = "P1",
    has_unmitigated_risk_9: bool = False,
    waivers: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """§9.1/§9.2: full gate lifecycle.

    1. Crash recovery
    2. Reuse check
    3. Write marker → collect → evaluate → clear marker
    """
    assert_host_context("run_production_gate")

    recover_from_crash(project_root)

    existing, _ = check_gate_reuse(
        project_root, gate_id, commit_sha, profile, factory_version,
        audit_policy=audit_policy, audit_path=audit_path,
    )
    if existing is not None:
        return existing

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateStartedAudit(
                gate_id=gate_id, commit_sha=commit_sha,
                profile_hash=compute_profile_hash(profile),
            ),
        )

    write_gate_marker(project_root, gate_id, commit_sha)
    try:
        _run_collectors(
            project_root, gate_id, commit_sha, profile, registry,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        gate_file = evaluate_gate(
            project_root, gate_id,
            commit_sha=commit_sha, target=target,
            profile=profile, factory_version=factory_version,
            priority=priority,
            has_unmitigated_risk_9=has_unmitigated_risk_9,
            waivers=waivers,
            audit_policy=audit_policy, audit_path=audit_path,
        )
    finally:
        clear_gate_marker(project_root)

    return gate_file
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add run_production_gate lifecycle with marker/reuse/crash-recovery" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Verdict Routing — PASS/CONCERNS/FAIL/WAIVED

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `gate_status.record_mitigation_debt` (Task 3), `gate_status.park_story` (Task 4), `runtime_policy.review_max_cycles` (existing).
- Produces: `route_gate_verdict(project_root, gate_file, *, story_key, remediation_cycle, max_cycles, has_unmitigated_risk_9, audit_policy, audit_path) -> dict[str, Any]` — §9.2 control flow:
  - `PASS` → `{"action": "done", "commit": True}`
  - `CONCERNS` → `{"action": "done", "commit": True, "mitigation_debt": [...]}` + records debt
  - `WAIVED` → `{"action": "done", "commit": True, "waived": True}`
  - `FAIL` + `has_unmitigated_risk_9` → `{"action": "park", "reason": "risk-9"}` (immediate park, no remediation)
  - `FAIL` + cycles < max → `{"action": "remediate"}`
  - `FAIL` + cycles >= max → `{"action": "park", "reason": "exhausted"}` + parks story

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
from story_automator.core.gate_orchestrator import route_gate_verdict


class RouteGateVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _gate(self, overall: str, categories: dict | None = None) -> dict:
        return make_gate_file(
            gate_id="gate-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "t", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories=categories or {"c": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"}},
            overall=overall,
        )

    def test_pass_returns_done(self) -> None:
        result = route_gate_verdict(
            self.tmp, self._gate("PASS"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["commit"])

    def test_concerns_returns_done_with_debt(self) -> None:
        gate = self._gate("CONCERNS", {
            "security": {"verdict": "CONCERNS", "required": {}, "actual": {}, "rationale": "low confidence"},
            "correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"},
        })
        result = route_gate_verdict(
            self.tmp, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["commit"])
        self.assertIn("mitigation_debt", result)

    def test_waived_returns_done(self) -> None:
        result = route_gate_verdict(
            self.tmp, self._gate("WAIVED"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["waived"])

    def test_fail_below_max_returns_remediate(self) -> None:
        result = route_gate_verdict(
            self.tmp, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=1, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")

    def test_fail_at_max_returns_park(self) -> None:
        result = route_gate_verdict(
            self.tmp, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=3, max_cycles=3,
        )
        self.assertEqual(result["action"], "park")
        self.assertEqual(result["reason"], "exhausted")

    def test_fail_risk_9_parks_immediately(self) -> None:
        result = route_gate_verdict(
            self.tmp, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
            has_unmitigated_risk_9=True,
        )
        self.assertEqual(result["action"], "park")
        self.assertEqual(result["reason"], "risk-9")

    def test_park_creates_parked_record(self) -> None:
        from story_automator.core.gate_status import list_parked
        route_gate_verdict(
            self.tmp, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=3, max_cycles=3,
        )
        parked = list_parked(self.tmp)
        self.assertEqual(len(parked), 1)
        self.assertEqual(parked[0]["story_key"], "E1-001")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::RouteGateVerdictTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
from .gate_status import record_mitigation_debt, park_story


def route_gate_verdict(
    project_root: str | pathlib.Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
    max_cycles: int = 3,
    has_unmitigated_risk_9: bool = False,
    audit_policy: dict[str, Any] | None = None,
    audit_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """§9.2: route verdict to action.

    PASS → done, CONCERNS → done+debt, FAIL+risk-9 → immediate park,
    FAIL → remediate or park, WAIVED → done+waived.
    """
    assert_host_context("route_gate_verdict")
    overall = gate_file.get("overall", "FAIL")
    gate_id = gate_file.get("gate_id", "")

    if overall == "PASS":
        return {"action": "done", "commit": True, "overall": "PASS"}

    if overall == "WAIVED":
        return {"action": "done", "commit": True, "waived": True, "overall": "WAIVED"}

    if overall == "CONCERNS":
        concerns_cats = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        record_mitigation_debt(project_root, gate_id, story_key, concerns_cats)
        return {
            "action": "done", "commit": True,
            "overall": "CONCERNS", "mitigation_debt": concerns_cats,
        }

    if has_unmitigated_risk_9:
        park_story(
            project_root, gate_id, story_key,
            "risk-9", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "risk-9",
            "overall": overall, "gate_id": gate_id,
        }

    if remediation_cycle >= max_cycles:
        park_story(
            project_root, gate_id, story_key,
            "exhausted", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "exhausted",
            "overall": overall, "gate_id": gate_id,
        }

    return {
        "action": "remediate", "overall": overall,
        "gate_id": gate_id, "cycle": remediation_cycle + 1,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add verdict routing with CONCERNS debt, FAIL remediation, and PARK" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Factory Version Resolution

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `story_automator.__version__`.
- Produces: `resolve_factory_version() -> str` — returns the current factory version from `story_automator.__version__`. Used by the gate orchestrator and CLI to stamp gate files.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
from story_automator.core.gate_orchestrator import resolve_factory_version


class FactoryVersionTests(unittest.TestCase):
    def test_returns_nonempty_string(self) -> None:
        version = resolve_factory_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_matches_package_version(self) -> None:
        from story_automator import __version__
        self.assertEqual(resolve_factory_version(), __version__)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::FactoryVersionTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
def resolve_factory_version() -> str:
    from story_automator import __version__
    return __version__
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add factory version resolution from package version" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Gate CLI — gate status Command

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Create: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_status.list_parked` (Task 4), `gate_status.load_mitigation_debt` (Task 3), `evidence_io.read_gate_marker`.
- Produces: `gate_status_action(args) -> int` — CLI: `gate status [--state=parked]`. Prints JSON with parked stories, in-flight gate markers, and outstanding mitigation debt.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_cmd.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.gate_cmd import gate_status_action


class GateStatusActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_empty_status(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_status_action([])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["parked"], [])
        self.assertFalse(output["in_progress"])

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_with_parked_filter(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.gate_status import park_story
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_status_action(["--state=parked"])
        output = json.loads(out.getvalue())
        self.assertEqual(len(output["parked"]), 1)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_shows_in_progress(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.evidence_io import write_gate_marker
        write_gate_marker(self.tmp, "g1", "abc123")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_status_action([])
        output = json.loads(out.getvalue())
        self.assertTrue(output["in_progress"])
        self.assertEqual(output["in_progress_gate_id"], "g1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateStatusActionTests -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`:

```python
"""Gate CLI commands — status, resume, invalidate.

Shipped with M10 (Orchestrator Wiring). Each action returns an
int exit code; output is structured JSON on stdout.
"""
from __future__ import annotations

import sys
from typing import Any

from story_automator.core.evidence_io import read_gate_marker
from story_automator.core.gate_status import (
    list_parked,
    load_mitigation_debt,
    resume_story,
    invalidate_gate,
    invalidate_gates_for_target,
)
from story_automator.core.utils import get_project_root, print_json


def _project_root() -> str:
    return get_project_root()


def gate_status_action(args: list[str]) -> int:
    project_root = _project_root()
    state_filter = None
    for arg in args:
        if arg.startswith("--state="):
            state_filter = arg.split("=", 1)[1]

    parked = list_parked(project_root, state_filter=state_filter)
    marker = read_gate_marker(project_root)
    debt = load_mitigation_debt(project_root)

    result: dict[str, Any] = {
        "ok": True,
        "parked": parked,
        "parked_count": len(parked),
        "in_progress": marker is not None,
        "mitigation_debt": debt,
        "mitigation_debt_count": len(debt),
    }
    if marker is not None:
        result["in_progress_gate_id"] = marker.get("gate_id", "")
        result["in_progress_commit"] = marker.get("commit_sha", "")
    print_json(result)
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate status CLI command with parked/in-progress/debt views" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Gate CLI — gate resume Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_status.resume_story` (Task 4).
- Produces: `gate_resume_action(args) -> int` — CLI: `gate resume <gate_id>`. Removes parked record and prints the resumed story info.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_resume_action


class GateResumeActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_resume_existing(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.gate_status import park_story
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action(["g1"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["story_key"], "E1-001")

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_resume_nonexistent(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action(["no-such"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(output["ok"])

    def test_resume_missing_arg(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action([])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateResumeActionTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
def gate_resume_action(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "gate_id required"})
        return 1
    gate_id = args[0]
    project_root = _project_root()
    record = resume_story(project_root, gate_id)
    if record is None:
        print_json({"ok": False, "error": "parked story not found", "gate_id": gate_id})
        return 1
    print_json({
        "ok": True,
        "gate_id": gate_id,
        "story_key": record.get("story_key", ""),
        "reason": record.get("reason", ""),
        "resumed": True,
    })
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate resume CLI command" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Gate CLI — gate invalidate Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_status.invalidate_gate`, `gate_status.invalidate_gates_for_target` (Task 5).
- Produces: `gate_invalidate_action(args) -> int` — CLI: `gate invalidate <story|epic>`. Invalidates gate files matching the target.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_invalidate_action
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class GateInvalidateActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str) -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc",
            profile={"id": "t", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_invalidate_by_target(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        self._create_gate("g1", "story-1")
        self._create_gate("g2", "story-1")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action(["story-1"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["invalidated_count"], 2)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_invalidate_no_matches(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action(["no-match"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["invalidated_count"], 0)

    def test_invalidate_missing_arg(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action([])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateInvalidateActionTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
def gate_invalidate_action(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "target (story or epic id) required"})
        return 1
    target_id = args[0]
    project_root = _project_root()
    invalidated = invalidate_gates_for_target(project_root, target_id)
    print_json({
        "ok": True,
        "target": target_id,
        "invalidated": invalidated,
        "invalidated_count": len(invalidated),
    })
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate invalidate CLI command with target-scoped bulk invalidation" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Orchestrator CLI Dispatch Wiring

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py` (add `gate_dispatch`)
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_cmd.gate_status_action`, `gate_cmd.gate_resume_action`, `gate_cmd.gate_invalidate_action`.
- Produces:
  - `gate_dispatch(args) -> int` in `gate_cmd.py` — routes `gate status|resume|invalidate` to the right action.
  - Adds `"gate": gate_dispatch` to the orchestrator dispatch table in `orchestrator.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_dispatch


class GateDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_dispatch_status(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["status"])
        self.assertEqual(code, 0)
        output = json.loads(out.getvalue())
        self.assertTrue(output["ok"])

    def test_dispatch_no_subcommand_shows_usage(self) -> None:
        code = gate_dispatch([])
        self.assertEqual(code, 1)

    def test_dispatch_unknown_subcommand(self) -> None:
        code = gate_dispatch(["unknown"])
        self.assertEqual(code, 1)
```

Also verify that orchestrator.py includes `gate` in its dispatch table:

```python
class OrchestratorGateDispatchTests(unittest.TestCase):
    def test_gate_in_dispatch_table(self) -> None:
        from story_automator.commands.orchestrator import cmd_orchestrator_helper
        # The dispatch table is internal, but we verify the action is recognized
        # by checking it doesn't return the usage exit code for known actions
        import io
        from unittest.mock import patch
        with patch("sys.stderr", new_callable=io.StringIO):
            with patch("story_automator.commands.gate_cmd._project_root", return_value=self.tmp):
                with patch("sys.stdout", new_callable=io.StringIO):
                    code = cmd_orchestrator_helper(["gate", "status"])
        self.assertEqual(code, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateDispatchTests -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
def gate_dispatch(args: list[str]) -> int:
    if not args:
        _gate_usage()
        return 1
    subcommand = args[0]
    dispatch = {
        "status": gate_status_action,
        "resume": gate_resume_action,
        "invalidate": gate_invalidate_action,
    }
    handler = dispatch.get(subcommand)
    if handler is None:
        _gate_usage()
        return 1
    return handler(args[1:])


def _gate_usage() -> None:
    print("Usage: orchestrator-helper gate <status|resume|invalidate> [args]",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("  gate status [--state=parked]", file=sys.stderr)
    print("  gate resume <gate_id>", file=sys.stderr)
    print("  gate invalidate <story|epic>", file=sys.stderr)
```

In `orchestrator.py`, add to the dispatch dict:

```python
from .gate_cmd import gate_dispatch

# In cmd_orchestrator_helper dispatch dict:
"gate": lambda args: gate_dispatch(args),
```

And add to the `_usage` function:

```python
print("  gate status [--state=parked]", file=target)
print("  gate resume <gate_id>", file=target)
print("  gate invalidate <story|epic>", file=target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py \
       skills/bmad-story-automator/src/story_automator/commands/orchestrator.py \
       tests/test_gate_cmd.py
git commit -m "feat(gate): wire gate CLI dispatch into orchestrator-helper" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: Integration Test — End-to-End Gate Lifecycle

**Files:**
- Create: `tests/test_gate_m10_integration.py`

**Interfaces:**
- Consumes: All modules from Tasks 1-14.
- Produces: Integration tests covering the full gate lifecycle round-trip:
  1. Run gate → PASS → verify done routing
  2. Run gate → CONCERNS → verify mitigation debt recorded
  3. Run gate → FAIL → verify remediate routing → exhaust → park
  4. Gate reuse on unchanged inputs
  5. Gate invalidation forces re-evaluation
  6. Crash recovery cleans up partial state
  7. CLI round-trip: status → park → status shows parked → resume → status shows empty

- [ ] **Step 1: Write the integration tests**

Create `tests/test_gate_m10_integration.py`:

```python
"""Integration tests for M10 orchestrator wiring.

End-to-end round-trips through the full gate lifecycle:
collect → adjudicate → route → persist → CLI query.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.gate_orchestrator import (
    run_production_gate,
    route_gate_verdict,
    recover_from_crash,
    resolve_factory_version,
)
from story_automator.core.gate_status import (
    list_parked,
    load_mitigation_debt,
    park_story,
)
from story_automator.core.gate_schema import make_evidence_record, make_gate_file
from story_automator.core.evidence_io import (
    persist_gate_file,
    persist_evidence_record,
    write_gate_marker,
)
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.product_profile import compute_profile_hash
from story_automator.core.success_verifiers import VERIFIERS, production_ready_gate
from story_automator.core.runtime_policy import VALID_VERIFIERS
from story_automator.commands.gate_cmd import gate_dispatch


PROFILE = {
    "id": "test", "version": 1,
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": []},
        "P1": {"coverage_pct": 90, "levels": []},
        "P2": {"coverage_pct": 50, "levels": []},
        "P3": {"coverage_pct": 20, "levels": []},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
}


class FullLifecycleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.registry = CollectorRegistry()

    def _persist_evidence(self, gate_id: str, records: list[dict]) -> None:
        for record in records:
            persist_evidence_record(self.tmp, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_pass_lifecycle(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="s", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        self._persist_evidence("integ-1", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "PASS")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(route["action"], "done")
        self.assertTrue(route["commit"])

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_concerns_records_debt(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 85, "regressions": 0}),
            make_evidence_record(collector="s", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        self._persist_evidence("integ-2", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-2", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "CONCERNS")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-002",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(route["action"], "done")
        debt = load_mitigation_debt(self.tmp)
        self.assertEqual(len(debt), 1)
        self.assertIn("correctness", debt[0]["categories"])

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_fail_exhaust_park_lifecycle(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="error", findings=["crash"]),
        ]
        self._persist_evidence("integ-3", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-3", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-003",
            remediation_cycle=3, max_cycles=3,
        )
        self.assertEqual(route["action"], "park")
        parked = list_parked(self.tmp)
        self.assertEqual(len(parked), 1)

    def test_crash_recovery_cleans_partial(self) -> None:
        write_gate_marker(self.tmp, "crash-1", "abc")
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "crash-1"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "partial.json").write_text("{}")
        result = recover_from_crash(self.tmp)
        self.assertTrue(result["recovered"])
        self.assertFalse(evidence_dir.exists())


class VerifierRegistrationIntegrationTests(unittest.TestCase):
    def test_production_ready_gate_in_verifiers(self) -> None:
        self.assertIn("production_ready_gate", VERIFIERS)

    def test_production_ready_gate_in_valid_verifiers(self) -> None:
        self.assertIn("production_ready_gate", VALID_VERIFIERS)

    def test_verifier_callable(self) -> None:
        self.assertTrue(callable(VERIFIERS["production_ready_gate"]))


class CLIRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_park_resume_round_trip(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status1 = json.loads(out.getvalue())
        self.assertEqual(status1["parked_count"], 0)

        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status2 = json.loads(out.getvalue())
        self.assertEqual(status2["parked_count"], 1)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["resume", "g1"])
        resume = json.loads(out.getvalue())
        self.assertTrue(resume["ok"])

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status3 = json.loads(out.getvalue())
        self.assertEqual(status3["parked_count"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they pass (all prior tasks must be complete)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_m10_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gate_m10_integration.py
git commit -m "test(gate): add end-to-end integration tests for M10 orchestrator wiring" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 16: Edge Case and Determinism Tests

**Files:**
- Modify: `tests/test_gate_m10_integration.py`

**Interfaces:**
- Consumes: All modules from Tasks 1-14.
- Produces: Edge case tests:
  1. Concurrent gate marker — second run detects existing marker
  2. Invalidated gate forces re-evaluation (not reused)
  3. Gate reuse with matching inputs returns cached result without re-running collectors
  4. Empty collector registry produces all-FAIL verdict (fail-closed)
  5. Mitigation debt idempotent — re-recording same gate_id overwrites
  6. Park + resume + re-run cycle

- [ ] **Step 1: Write the edge case tests**

Append to `tests/test_gate_m10_integration.py`:

```python
class EdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_gate_reuse_skips_collectors(self, mock_run: MagicMock) -> None:
        profile_hash = compute_profile_hash(PROFILE)
        gate = make_gate_file(
            gate_id="reuse-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = run_production_gate(
            self.tmp, "reuse-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        mock_run.assert_not_called()
        self.assertEqual(result["overall"], "PASS")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_empty_registry_fails_closed(self, mock_run: MagicMock) -> None:
        # No evidence persisted to disk — evaluate_gate finds nothing → fail-closed
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "empty-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")

    def test_mitigation_debt_idempotent(self) -> None:
        from story_automator.core.gate_status import record_mitigation_debt
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security"])
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security", "static"])
        debt = load_mitigation_debt(self.tmp)
        self.assertEqual(len(debt), 1)
        self.assertEqual(debt[0]["categories"], ["security", "static"])

    def test_invalidated_gate_not_reused(self) -> None:
        from story_automator.core.gate_status import invalidate_gate
        profile_hash = compute_profile_hash(PROFILE)
        gate = make_gate_file(
            gate_id="inv-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        invalidate_gate(self.tmp, "inv-1")
        from story_automator.core.gate_orchestrator import check_gate_reuse
        result, reason = check_gate_reuse(
            self.tmp, "inv-1", "abc", PROFILE, "1.15.0",
        )
        self.assertIsNone(result)

    def test_factory_version_deterministic(self) -> None:
        v1 = resolve_factory_version()
        v2 = resolve_factory_version()
        self.assertEqual(v1, v2)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_m10_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gate_m10_integration.py
git commit -m "test(gate): add edge case and determinism tests for orchestrator wiring" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 17: Operator Runbook

**Files:**
- Create: `docs/operations/gate-troubleshooting.md`

**Interfaces:**
- None (documentation only).
- §11.1: required sections with executable jq/CLI recipes.

- [ ] **Step 1: Create the runbook**

Create `docs/operations/gate-troubleshooting.md` with the nine required sections per §11.1:

1. **First-run profile discovery** — `story-automator doctor` output, profile precedence, recovery for malformed profiles.
2. **Verdict interpretation decision tree** — per-category PASS/CONCERNS/FAIL/NA with next action; `categories_na` opt-outs.
3. **PARK + remediation exhaustion flow** — `review_max_cycles` exceeded → PARK; `story-automator gate status --state=parked`; resume via `story-automator gate resume <gate_id>`.
4. **Partial-FAIL playbook** — per-category remediation stories vs blanket re-run.
5. **Profile-drift re-gate procedure** — `story-automator gate invalidate <story|epic>`; explicit gate-file invalidation rules.
6. **Waiver SOP** — mandatory fields, signing process, max TTL, audit-trail location.
7. **Atomic-gate crash recovery** — `gate-in-progress.json` marker; manual clear procedure.
8. **Operator takeover checklist** — pause, manual edit, resume; BMAD edit-authorization.
9. **Repeated-timeout handling** — raise `profile.timeouts.<category>` or kill-switch collector.

Each section includes executable jq/CLI recipes (not prose only).

- [ ] **Step 2: Verify no trailing whitespace**

Run: `grep -n ' $' docs/operations/gate-troubleshooting.md | head`
Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add docs/operations/gate-troubleshooting.md
git commit -m "docs(gate): add operator runbook per §11.1 with executable jq/CLI recipes" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 18: Full Test Suite Validation + CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- None (validation + documentation only).

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short`
Expected: All tests PASS (including all pre-existing m1-m9 tests — no regressions).

- [ ] **Step 2: Run ruff lint**

Run: `cd skills/bmad-story-automator && python3 -m ruff check src/ && cd ../..`
Expected: Clean.

- [ ] **Step 3: Verify LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py skills/bmad-story-automator/src/story_automator/core/gate_status.py skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
Expected: Each under 500 LOC.

- [ ] **Step 4: Update CLAUDE.md module map**

Add to the Gate subsystem section:

```markdown
- **Orchestrator wiring (m10)** `core/gate_orchestrator.py` (`run_production_gate`, `route_gate_verdict`, `recover_from_crash`, `check_gate_reuse`, `resolve_factory_version`), `core/gate_status.py` (`park_story`, `resume_story`, `list_parked`, `invalidate_gate`, `invalidate_gates_for_target`, `record_mitigation_debt`, `load_mitigation_debt`, `clear_mitigation_debt`), `commands/gate_cmd.py` (`gate_dispatch`, `gate_status_action`, `gate_resume_action`, `gate_invalidate_action`). `production_ready_gate` verifier registered in `success_verifiers.py` VERIFIERS and `runtime_policy.py` VALID_VERIFIERS.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with M10 orchestrator wiring module map" \
  --trailer "Generated-By: claude-opus-4-6"
```
