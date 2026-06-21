# Integration M11: Gate Operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the operational completeness layer for the production-readiness gate. M10 wired the core lifecycle (`run_production_gate`, `route_gate_verdict`, crash recovery, park/resume/invalidate, CLI, runbook). M11 adds the operational tooling an operator needs in production: concurrent gate safety (filelock), gate duration tracking with completion audit events, health checks (`gate doctor`), verdict history querying (`gate list`), aggregate metrics (`gate summary`), remediation write-back integration, a convenience `gate rerun` command, and comprehensive end-to-end operational scenario testing.

**Architecture:** One new module (`gate_ops.py`) for operational helpers plus surgical additions to M10 modules:
- `gate_ops.py` (~250 LOC) — operational queries (list verdicts, doctor health check, summary metrics, remediation write-back bridge, runbook enrichment).
- `gate_orchestrator.py` (+~50 LOC) — filelock-based concurrent gate protection, duration tracking, GateCompletedAudit emission.
- `gate_audit.py` (+~15 LOC) — GateCompletedAudit event dataclass.
- `gate_cmd.py` (+~140 LOC) — four new CLI subcommands: doctor, list, summary, rerun.

**Dependency graph:** Builds on M10's stable interfaces. New `gate_ops.py` imports from `gate_status.py`, `gate_remediation.py`, `evidence_io.py`, `gate_schema.py`. Modified `gate_orchestrator.py` gains filelock import (already an allowed dep). CLI additions in `gate_cmd.py` consume `gate_ops.py` functions. Import direction: `gate_ops.py` → `gate_cmd.py` (gate_ops never imports from gate_cmd).

**Key existing interfaces consumed (from M10, unchanged):**
- `gate_orchestrator.py`: `run_production_gate`, `route_gate_verdict`, `recover_from_crash`, `check_gate_reuse`, `resolve_factory_version`
- `gate_status.py`: `park_story`, `resume_story`, `list_parked`, `invalidate_gate`, `invalidate_gates_for_target`, `record_mitigation_debt`, `load_mitigation_debt`
- `gate_remediation.py`: `prepare_remediation_tasks`, `write_remediation_to_story`, `failing_categories_from_gate`, `request_review_continuation`
- `evidence_io.py`: `load_gate_file`, `persist_gate_file`, `read_gate_marker`, `write_gate_marker`, `clear_gate_marker`, `load_evidence_bundle`
- `gate_audit.py`: `emit_gate_audit`, all existing audit event types
- `gate_schema.py`: `GateSchemaError`, `make_gate_file`, `make_evidence_record`, `canonical_json`

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT change existing M10 function signatures.** Add new functions or optional parameters only.
- **500-LOC soft limit per Python module.** `gate_orchestrator.py` stays ≤340 LOC; `gate_ops.py` target ~250 LOC; `gate_cmd.py` stays ≤260 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path; use `os.replace` via `write_atomic` for atomic writes.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_ops.py` — operational helpers (~250 LOC)
- `tests/test_gate_ops.py` — tests for gate_ops (~350 LOC)
- `tests/test_gate_m11_integration.py` — operational scenario integration tests (~400 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — filelock + duration + completion audit (~+50 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — GateCompletedAudit dataclass (~+15 LOC)
- `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py` — four new subcommands (~+140 LOC)
- `tests/test_gate_orchestrator.py` — duration + lock tests (~+80 LOC)
- `tests/test_gate_audit.py` — GateCompletedAudit tests (~+30 LOC)
- `tests/test_gate_cmd.py` — new command tests (~+120 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/verdict_engine.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`, `core/product_profile.py`, `core/category_rules.py`, `core/gate_status.py`, `core/gate_remediation.py`, `core/success_verifiers.py`, `core/runtime_policy.py`.

---

### Task 1: GateCompletedAudit Event

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing frozen-dataclass + `to_dict` audit event pattern.
- Produces: `GateCompletedAudit` — emitted when a full gate lifecycle completes (after verdict + marker clear). Fields: `gate_id`, `overall`, `duration_ms`, `commit_sha`, `runbook_ref` (empty string for PASS, else runbook section identifier). Added to `_AuditEvent` union and `__all__`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
from story_automator.core.gate_audit import GateCompletedAudit


class GateCompletedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateCompletedAudit(
            gate_id="g1", overall="PASS", duration_ms=5000,
            commit_sha="abc123", runbook_ref="",
        )
        self.assertEqual(event.event_name, "GateCompleted")

    def test_to_dict_contains_all_fields(self) -> None:
        event = GateCompletedAudit(
            gate_id="g1", overall="FAIL", duration_ms=12345,
            commit_sha="abc123", runbook_ref="section-4",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["overall"], "FAIL")
        self.assertEqual(d["duration_ms"], 12345)
        self.assertEqual(d["commit_sha"], "abc123")
        self.assertEqual(d["runbook_ref"], "section-4")

    def test_frozen(self) -> None:
        event = GateCompletedAudit(gate_id="g1", overall="PASS", duration_ms=0, commit_sha="x")
        with self.assertRaises(AttributeError):
            event.gate_id = "g2"

    def test_satisfies_audit_event_protocol(self) -> None:
        event = GateCompletedAudit(gate_id="g1", overall="PASS", duration_ms=0, commit_sha="x")
        self.assertIsInstance(event, AuditEventProtocol)

    def test_runbook_ref_defaults_empty(self) -> None:
        event = GateCompletedAudit(gate_id="g1", overall="PASS", duration_ms=0, commit_sha="x")
        self.assertEqual(event.runbook_ref, "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v -k "Completed"`
Expected: ImportError — `GateCompletedAudit` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_audit.py` before the `_AuditEvent` union:

```python
@dataclasses.dataclass(frozen=True)
class GateCompletedAudit:
    """Audit event: full gate lifecycle completed."""
    event_name: str = dataclasses.field(default="GateCompleted", init=False)
    gate_id: str = ""
    overall: str = ""
    duration_ms: int = 0
    commit_sha: str = ""
    runbook_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "overall": self.overall,
            "duration_ms": self.duration_ms,
            "commit_sha": self.commit_sha,
            "runbook_ref": self.runbook_ref,
        }
```

Update `_AuditEvent` union to include `GateCompletedAudit`. Update `__all__` to include `"GateCompletedAudit"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add GateCompletedAudit event with duration and runbook reference" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Gate Duration Tracking

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `time.monotonic()` for duration measurement, `gate_audit.GateCompletedAudit` (Task 1), `emit_gate_audit`.
- Produces: `run_production_gate` now returns a gate file dict with an additional `"duration_ms"` key (int). Emits `GateCompletedAudit` with the measured duration. The duration covers marker-write through verdict-persist (excludes reuse/crash-recovery preamble).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
class GateDurationTrackingTests(unittest.TestCase):
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

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_gate_file_contains_duration_ms(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "dur-1", evidence[0])
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "dur-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("duration_ms", gate)
        self.assertIsInstance(gate["duration_ms"], int)
        self.assertGreaterEqual(gate["duration_ms"], 0)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_reused_gate_has_no_new_duration(self, mock_run: MagicMock) -> None:
        """Reused gates keep their original data — no duration_ms override."""
        profile_hash = compute_profile_hash(self.profile)
        gate = make_gate_file(
            gate_id="dur-reuse",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = run_production_gate(
            self.tmp, "dur-reuse", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        mock_run.assert_not_called()
        self.assertNotIn("duration_ms", result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::GateDurationTrackingTests -v`
Expected: `AssertionError` — `duration_ms` not in gate file.

- [ ] **Step 3: Write minimal implementation**

Modify `run_production_gate` in `gate_orchestrator.py`:

```python
import time

# Inside run_production_gate, after the reuse check (before write_gate_marker):
    _start = time.monotonic()

    write_gate_marker(project_root, gate_id, commit_sha)
    try:
        _run_collectors(...)
        gate_file = evaluate_gate(...)
    finally:
        clear_gate_marker(project_root)

    duration_ms = int((time.monotonic() - _start) * 1000)
    gate_file["duration_ms"] = duration_ms

    if audit_policy is not None and audit_path is not None:
        _runbook_ref = _runbook_ref_for_verdict(gate_file.get("overall", ""))
        emit_gate_audit(
            audit_policy, audit_path,
            GateCompletedAudit(
                gate_id=gate_id,
                overall=gate_file.get("overall", ""),
                duration_ms=duration_ms,
                commit_sha=commit_sha,
                runbook_ref=_runbook_ref,
            ),
        )

    return gate_file
```

Add helper (at module level):

```python
_VERDICT_RUNBOOK_REFS: dict[str, str] = {
    "FAIL": "section-4",
    "CONCERNS": "section-2",
    "WAIVED": "section-6",
}

def _runbook_ref_for_verdict(overall: str) -> str:
    return _VERDICT_RUNBOOK_REFS.get(overall, "")
```

Add `GateCompletedAudit` to imports from `.gate_audit`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): track gate duration and emit GateCompletedAudit on lifecycle completion" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Filelock-Based Gate Concurrent Access Protection

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Consumes: `filelock.FileLock` (allowed dep), `utils.ensure_dir`.
- Produces: `run_production_gate` acquires a filelock (`_bmad/gate/gate.lock`) before the marker-write phase. Lock timeout is 5 seconds (prevents indefinite blocking on concurrent runs). On `filelock.Timeout`, raises `GateConcurrencyError(ValueError)` with a clear message directing the operator to `gate status`. Lock is released in the `finally` block.
- New export: `GateConcurrencyError` exception class.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
from story_automator.core.gate_orchestrator import GateConcurrencyError


class GateConcurrencyTests(unittest.TestCase):
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

    def test_gate_lock_file_created(self) -> None:
        """Gate lock file exists under _bmad/gate/ after initialization."""
        lock_path = Path(self.tmp) / "_bmad" / "gate" / "gate.lock"
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "lock-1", evidence[0])
        with patch("story_automator.core.gate_orchestrator._run_collectors"):
            run_production_gate(
                self.tmp, "lock-1", commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile, factory_version="1.15.0",
                registry=self.registry,
            )
        self.assertTrue(lock_path.exists())

    def test_concurrent_gate_raises_error(self) -> None:
        """A second gate attempt while locked raises GateConcurrencyError."""
        from filelock import FileLock
        lock_path = Path(self.tmp) / "_bmad" / "gate" / "gate.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        external_lock = FileLock(str(lock_path), timeout=0)
        external_lock.acquire()
        try:
            with self.assertRaises(GateConcurrencyError):
                run_production_gate(
                    self.tmp, "lock-2", commit_sha="abc",
                    target={"kind": "story", "id": "s1"},
                    profile=self.profile, factory_version="1.15.0",
                    registry=self.registry,
                )
        finally:
            external_lock.release()

    def test_lock_released_on_exception(self) -> None:
        """Lock is released even when gate evaluation raises."""
        lock_path = Path(self.tmp) / "_bmad" / "gate" / "gate.lock"
        with patch("story_automator.core.gate_orchestrator._run_collectors", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_production_gate(
                    self.tmp, "lock-exc", commit_sha="abc",
                    target={"kind": "story", "id": "s1"},
                    profile=self.profile, factory_version="1.15.0",
                    registry=self.registry,
                )
        from filelock import FileLock
        reacquired = FileLock(str(lock_path), timeout=0)
        reacquired.acquire()
        reacquired.release()

    def test_concurrency_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(GateConcurrencyError, ValueError))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py::GateConcurrencyTests -v`
Expected: ImportError — `GateConcurrencyError` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_orchestrator.py`:

```python
from filelock import FileLock, Timeout as FileLockTimeout
from .utils import ensure_dir


class GateConcurrencyError(ValueError):
    """Raised when another gate run is already in progress."""


_GATE_LOCK_TIMEOUT = 1  # seconds; fail fast, operator retries via 'gate status'


def _gate_lock(project_root: str | Path) -> FileLock:
    lock_dir = Path(project_root) / "_bmad" / "gate"
    ensure_dir(lock_dir)
    return FileLock(str(lock_dir / "gate.lock"), timeout=_GATE_LOCK_TIMEOUT)
```

Modify `run_production_gate` to wrap the marker/collect/evaluate block:

```python
    lock = _gate_lock(project_root)
    try:
        lock.acquire()
    except FileLockTimeout:
        raise GateConcurrencyError(
            "another gate run is in progress; check 'gate status' for details"
        )

    _start = time.monotonic()
    try:
        write_gate_marker(project_root, gate_id, commit_sha)
        try:
            _run_collectors(...)
            gate_file = evaluate_gate(...)
        finally:
            clear_gate_marker(project_root)

        duration_ms = int((time.monotonic() - _start) * 1000)
        gate_file["duration_ms"] = duration_ms
        # ... GateCompletedAudit emission ...
    finally:
        lock.release()

    return gate_file
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py tests/test_gate_orchestrator.py
git commit -m "feat(gate): add filelock-based concurrent gate protection" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Gate Ops — list_verdicts

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`
- Create: `tests/test_gate_ops.py`

**Interfaces:**
- Consumes: `evidence_io.load_gate_file`, `gate_schema.GateSchemaError`.
- Produces: `list_verdicts(project_root, *, target_filter=None, verdict_filter=None) -> list[dict]` — scans `_bmad/gate/verdicts/*.json` (excluding `*.invalidated.json`), returns a list of summary dicts `{gate_id, target, overall, commit_sha, factory_version, profile_id}`. Filtered by target.id and/or overall verdict when filters are provided.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_ops.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.gate_ops import list_verdicts
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class ListVerdictsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str = "s1",
                     overall: str = "PASS") -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "ok"}},
            overall=overall,
        )
        persist_gate_file(self.tmp, gate)

    def test_empty_project_returns_empty(self) -> None:
        self.assertEqual(list_verdicts(self.tmp), [])

    def test_returns_all_verdicts(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        result = list_verdicts(self.tmp)
        self.assertEqual(len(result), 2)

    def test_excludes_invalidated(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        inv_path = Path(self.tmp) / "_bmad" / "gate" / "verdicts" / "g1.invalidated.json"
        src_path = Path(self.tmp) / "_bmad" / "gate" / "verdicts" / "g1.json"
        src_path.rename(inv_path)
        result = list_verdicts(self.tmp)
        self.assertEqual(len(result), 0)

    def test_filter_by_target(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "PASS")
        result = list_verdicts(self.tmp, target_filter="s1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "g1")

    def test_filter_by_verdict(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        result = list_verdicts(self.tmp, verdict_filter="FAIL")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "g2")

    def test_summary_contains_expected_keys(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        result = list_verdicts(self.tmp)
        self.assertIn("gate_id", result[0])
        self.assertIn("target", result[0])
        self.assertIn("overall", result[0])
        self.assertIn("commit_sha", result[0])
        self.assertIn("factory_version", result[0])
        self.assertIn("profile_id", result[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py::ListVerdictsTests -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`:

```python
"""Gate operations — operational helpers for day-to-day gate management.

Query, health-check, metrics, and remediation-bridge functions that
build on the M10 gate primitives without modifying them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "list_verdicts",
    "gate_doctor",
    "gate_summary",
    "apply_remediation",
    "enrich_route_with_runbook",
]


def list_verdicts(
    project_root: str | Path,
    *,
    target_filter: str | None = None,
    verdict_filter: str | None = None,
) -> list[dict[str, Any]]:
    """List all gate verdict summaries, optionally filtered."""
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    if not verdicts_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(verdicts_dir.glob("*.json")):
        if path.name.endswith(".invalidated.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        target = data.get("target", {})
        target_id = target.get("id", "") if isinstance(target, dict) else ""
        overall = data.get("overall", "")
        if target_filter is not None and target_id != target_filter:
            continue
        if verdict_filter is not None and overall != verdict_filter:
            continue
        profile = data.get("profile", {})
        results.append({
            "gate_id": data.get("gate_id", path.stem),
            "target": target,
            "overall": overall,
            "commit_sha": data.get("commit_sha", ""),
            "factory_version": data.get("factory_version", ""),
            "profile_id": profile.get("id", "") if isinstance(profile, dict) else "",
        })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_ops.py tests/test_gate_ops.py
git commit -m "feat(gate): add list_verdicts operational helper for querying gate history" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Gate Ops — gate_doctor Health Check

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`
- Modify: `tests/test_gate_ops.py`

**Interfaces:**
- Consumes: `evidence_io.read_gate_marker`, `list_verdicts` (Task 4).
- Produces: `gate_doctor(project_root) -> dict[str, Any]` — validates gate infrastructure consistency. Checks: (a) orphan gate-in-progress marker without active process, (b) evidence directories without matching verdicts, (c) verdicts with unparseable JSON, (d) parked records with missing gate files. Returns `{"healthy": bool, "checks": [...], "issues": [...]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_ops.py`:

```python
from story_automator.core.gate_ops import gate_doctor
from story_automator.core.evidence_io import write_gate_marker
from story_automator.core.gate_status import park_story


class GateDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_healthy_empty_project(self) -> None:
        result = gate_doctor(self.tmp)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["issues"], [])

    def test_healthy_with_valid_verdict(self) -> None:
        gate = make_gate_file(
            gate_id="g1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = gate_doctor(self.tmp)
        self.assertTrue(result["healthy"])

    def test_detects_orphan_marker(self) -> None:
        write_gate_marker(self.tmp, "g-orphan", "abc")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("orphan_marker", issues)

    def test_detects_orphan_evidence(self) -> None:
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "orphan-gate"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "data.json").write_text("{}")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("orphan_evidence", issues)

    def test_detects_invalid_verdict_json(self) -> None:
        verdicts_dir = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        verdicts_dir.mkdir(parents=True)
        (verdicts_dir / "bad.json").write_text("not json{{{")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("invalid_verdict", issues)

    def test_reports_check_counts(self) -> None:
        result = gate_doctor(self.tmp)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py::GateDoctorTests -v`
Expected: ImportError — `gate_doctor` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_ops.py`:

```python
from .evidence_io import read_gate_marker


def gate_doctor(project_root: str | Path) -> dict[str, Any]:
    """Validate gate infrastructure consistency."""
    root = Path(project_root)
    gate_dir = root / "_bmad" / "gate"
    checks: list[str] = []
    issues: list[dict[str, str]] = []

    # Check 1: orphan marker
    checks.append("orphan_marker")
    marker = read_gate_marker(project_root)
    if marker is not None:
        issues.append({
            "type": "orphan_marker",
            "detail": f"gate-in-progress marker exists for gate_id={marker.get('gate_id', '?')}",
        })

    # Check 2: orphan evidence directories
    checks.append("orphan_evidence")
    evidence_dir = gate_dir / "evidence"
    verdicts_dir = gate_dir / "verdicts"
    if evidence_dir.is_dir():
        for child in sorted(evidence_dir.iterdir()):
            if child.is_dir():
                verdict_path = verdicts_dir / f"{child.name}.json"
                if not verdict_path.is_file():
                    issues.append({
                        "type": "orphan_evidence",
                        "detail": f"evidence dir '{child.name}' has no matching verdict",
                    })

    # Check 3: invalid verdict JSON
    checks.append("verdict_validity")
    if verdicts_dir.is_dir():
        for path in sorted(verdicts_dir.glob("*.json")):
            if path.name.endswith(".invalidated.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "gate_id" not in data:
                    issues.append({
                        "type": "invalid_verdict",
                        "detail": f"verdict '{path.name}' missing required fields",
                    })
            except (json.JSONDecodeError, OSError):
                issues.append({
                    "type": "invalid_verdict",
                    "detail": f"verdict '{path.name}' contains invalid JSON",
                })

    return {
        "healthy": len(issues) == 0,
        "checks": checks,
        "issues": issues,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_ops.py tests/test_gate_ops.py
git commit -m "feat(gate): add gate_doctor health check for infrastructure consistency" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Gate Ops — apply_remediation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`
- Modify: `tests/test_gate_ops.py`

**Interfaces:**
- Consumes: `gate_remediation.write_remediation_to_story` (M10).
- Produces: `apply_remediation(story_path, route_result) -> dict[str, Any]` — takes the `route_gate_verdict` result (when `action == "remediate"`) and writes the remediation tasks to the story file. Returns `{"applied": True, "tasks_written": int, "review_continuation": dict}`. Raises `ValueError` if route_result action is not "remediate". This bridges the gap between route_gate_verdict returning tasks and actually writing them to the story.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_ops.py`:

```python
import shutil

from story_automator.core.gate_ops import apply_remediation


class ApplyRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.story_path = Path(self.tmp) / "E1-001.md"
        self.story_path.write_text(
            "---\nStatus: in-progress\n---\n\n## Tasks\n- [ ] Existing\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_tasks_to_story(self) -> None:
        route_result = {
            "action": "remediate",
            "remediation_tasks": [
                {"title": "[AI-Review] Fix correctness: low coverage",
                 "category": "correctness", "gate_id": "g1", "rationale": "cov 40<80"},
            ],
            "review_continuation": {
                "action": "review_continuation",
                "story_key": "E1-001",
                "gate_id": "g1",
                "cycle": 1,
                "failing_categories": ["correctness"],
            },
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertTrue(result["applied"])
        self.assertEqual(result["tasks_written"], 1)
        self.assertIn("review_continuation", result)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review] Fix correctness", content)

    def test_rejects_non_remediate_action(self) -> None:
        with self.assertRaises(ValueError):
            apply_remediation(self.story_path, {"action": "done"})

    def test_noop_with_empty_tasks(self) -> None:
        route_result = {
            "action": "remediate",
            "remediation_tasks": [],
            "review_continuation": {"action": "review_continuation"},
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertTrue(result["applied"])
        self.assertEqual(result["tasks_written"], 0)

    def test_multiple_tasks_written(self) -> None:
        route_result = {
            "action": "remediate",
            "remediation_tasks": [
                {"title": "[AI-Review] Fix correctness", "category": "correctness",
                 "gate_id": "g1", "rationale": "r"},
                {"title": "[AI-Review] Fix security", "category": "security",
                 "gate_id": "g1", "rationale": "r"},
            ],
            "review_continuation": {"action": "review_continuation"},
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertEqual(result["tasks_written"], 2)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review] Fix correctness", content)
        self.assertIn("[AI-Review] Fix security", content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py::ApplyRemediationTests -v`
Expected: ImportError — `apply_remediation` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_ops.py`:

```python
from .gate_remediation import write_remediation_to_story


def apply_remediation(
    story_path: str | Path,
    route_result: dict[str, Any],
) -> dict[str, Any]:
    """Bridge route_gate_verdict's remediate action to story write-back.

    §9.2: FAIL -> Remediator writes [AI-Review] tasks to the dev-story
    via review_continuation, honoring edit-authorization.
    """
    if route_result.get("action") != "remediate":
        raise ValueError(
            f"apply_remediation requires action='remediate', got '{route_result.get('action')}'"
        )
    tasks = route_result.get("remediation_tasks", [])
    write_remediation_to_story(story_path, tasks)
    return {
        "applied": True,
        "tasks_written": len(tasks),
        "review_continuation": route_result.get("review_continuation", {}),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_ops.py tests/test_gate_ops.py
git commit -m "feat(gate): add apply_remediation bridge for FAIL→story write-back" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Gate Ops — gate_summary Metrics

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`
- Modify: `tests/test_gate_ops.py`

**Interfaces:**
- Consumes: `list_verdicts` (Task 4), `gate_status.load_mitigation_debt`, `gate_status.list_parked`.
- Produces: `gate_summary(project_root) -> dict[str, Any]` — aggregate operational metrics. Returns `{"total_verdicts": int, "by_verdict": {"PASS": int, "FAIL": int, "CONCERNS": int, "WAIVED": int}, "parked_count": int, "mitigation_debt_count": int, "avg_duration_ms": int | None}`. `avg_duration_ms` is computed from verdicts that have a `duration_ms` field (M11 gates); None if no duration data.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_ops.py`:

```python
from story_automator.core.gate_ops import gate_summary
from story_automator.core.gate_status import park_story, record_mitigation_debt


class GateSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, overall: str = "PASS",
                     duration_ms: int | None = None) -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": f"s-{gate_id}"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": overall, "required": {}, "actual": {}, "rationale": "ok"}},
            overall=overall,
        )
        if duration_ms is not None:
            gate["duration_ms"] = duration_ms
        persist_gate_file(self.tmp, gate)

    def test_empty_project(self) -> None:
        result = gate_summary(self.tmp)
        self.assertEqual(result["total_verdicts"], 0)
        self.assertIsNone(result["avg_duration_ms"])

    def test_counts_by_verdict(self) -> None:
        self._create_gate("g1", "PASS")
        self._create_gate("g2", "PASS")
        self._create_gate("g3", "FAIL")
        result = gate_summary(self.tmp)
        self.assertEqual(result["total_verdicts"], 3)
        self.assertEqual(result["by_verdict"]["PASS"], 2)
        self.assertEqual(result["by_verdict"]["FAIL"], 1)

    def test_includes_parked_count(self) -> None:
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        result = gate_summary(self.tmp)
        self.assertEqual(result["parked_count"], 1)

    def test_includes_debt_count(self) -> None:
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security"])
        result = gate_summary(self.tmp)
        self.assertEqual(result["mitigation_debt_count"], 1)

    def test_avg_duration_computed(self) -> None:
        self._create_gate("g1", "PASS", duration_ms=1000)
        self._create_gate("g2", "PASS", duration_ms=3000)
        result = gate_summary(self.tmp)
        self.assertEqual(result["avg_duration_ms"], 2000)

    def test_avg_duration_none_without_data(self) -> None:
        self._create_gate("g1", "PASS")
        result = gate_summary(self.tmp)
        self.assertIsNone(result["avg_duration_ms"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py::GateSummaryTests -v`
Expected: ImportError — `gate_summary` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_ops.py`:

```python
from .gate_status import list_parked, load_mitigation_debt


def gate_summary(project_root: str | Path) -> dict[str, Any]:
    """Aggregate operational metrics across gate verdicts."""
    root = Path(project_root)
    verdicts_dir = root / "_bmad" / "gate" / "verdicts"
    by_verdict: dict[str, int] = {}
    durations: list[int] = []
    total = 0
    if verdicts_dir.is_dir():
        for path in sorted(verdicts_dir.glob("*.json")):
            if path.name.endswith(".invalidated.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            total += 1
            overall = data.get("overall", "")
            by_verdict[overall] = by_verdict.get(overall, 0) + 1
            dur = data.get("duration_ms")
            if isinstance(dur, int):
                durations.append(dur)
    parked = list_parked(project_root)
    debt = load_mitigation_debt(project_root)
    avg_dur = int(sum(durations) / len(durations)) if durations else None
    return {
        "total_verdicts": total,
        "by_verdict": by_verdict,
        "parked_count": len(parked),
        "mitigation_debt_count": len(debt),
        "avg_duration_ms": avg_dur,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_ops.py tests/test_gate_ops.py
git commit -m "feat(gate): add gate_summary for aggregate operational metrics" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Gate Ops — enrich_route_with_runbook

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_ops.py`
- Modify: `tests/test_gate_ops.py`

**Interfaces:**
- Consumes: none beyond the route_result dict.
- Produces: `enrich_route_with_runbook(route_result) -> dict[str, Any]` — enriches the route_gate_verdict result with a `runbook_ref` key pointing to the relevant runbook section per §11.1. Mapping: `FAIL`→`"section-4: Partial-FAIL Playbook"`, `CONCERNS`→`"section-2: Verdict Interpretation"`, park(exhausted)→`"section-3: PARK + Remediation"`, park(risk-9)→`"section-3: PARK + Remediation"`, `WAIVED`→`"section-6: Waiver SOP"`. PASS returns empty string.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_ops.py`:

```python
from story_automator.core.gate_ops import enrich_route_with_runbook


class EnrichRouteWithRunbookTests(unittest.TestCase):
    def test_pass_gets_empty_ref(self) -> None:
        result = enrich_route_with_runbook({"action": "done", "overall": "PASS"})
        self.assertEqual(result["runbook_ref"], "")

    def test_fail_remediate_gets_section_4(self) -> None:
        result = enrich_route_with_runbook({"action": "remediate", "overall": "FAIL"})
        self.assertIn("section-4", result["runbook_ref"])

    def test_concerns_gets_section_2(self) -> None:
        result = enrich_route_with_runbook({"action": "done", "overall": "CONCERNS"})
        self.assertIn("section-2", result["runbook_ref"])

    def test_park_exhausted_gets_section_3(self) -> None:
        result = enrich_route_with_runbook({
            "action": "park", "reason": "exhausted", "overall": "FAIL",
        })
        self.assertIn("section-3", result["runbook_ref"])

    def test_park_risk9_gets_section_3(self) -> None:
        result = enrich_route_with_runbook({
            "action": "park", "reason": "risk-9", "overall": "FAIL",
        })
        self.assertIn("section-3", result["runbook_ref"])

    def test_waived_gets_section_6(self) -> None:
        result = enrich_route_with_runbook({"action": "done", "overall": "WAIVED"})
        self.assertIn("section-6", result["runbook_ref"])

    def test_original_keys_preserved(self) -> None:
        original = {"action": "done", "overall": "PASS", "commit": True}
        result = enrich_route_with_runbook(original)
        self.assertTrue(result["commit"])
        self.assertEqual(result["action"], "done")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py::EnrichRouteWithRunbookTests -v`
Expected: ImportError — `enrich_route_with_runbook` not found.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_ops.py`:

```python
_RUNBOOK_REFS: dict[str, str] = {
    "FAIL": "section-4: Partial-FAIL Playbook",
    "CONCERNS": "section-2: Verdict Interpretation",
    "WAIVED": "section-6: Waiver SOP",
}


def enrich_route_with_runbook(route_result: dict[str, Any]) -> dict[str, Any]:
    """Add runbook_ref to route_gate_verdict result per §11.1."""
    enriched = dict(route_result)
    action = route_result.get("action", "")
    overall = route_result.get("overall", "")
    if action == "park":
        enriched["runbook_ref"] = "section-3: PARK + Remediation"
    elif overall in _RUNBOOK_REFS:
        enriched["runbook_ref"] = _RUNBOOK_REFS[overall]
    else:
        enriched["runbook_ref"] = ""
    return enriched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_ops.py tests/test_gate_ops.py
git commit -m "feat(gate): add runbook reference enrichment for route results per §11.1" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Gate CLI — doctor Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_ops.gate_doctor` (Task 5).
- Produces: `gate_doctor_action(args) -> int` — CLI: `gate doctor`. Prints JSON health check result. Exit code 0 if healthy, 1 if issues found.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_dispatch


class GateDoctorActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_healthy_project(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["doctor"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["healthy"])

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_unhealthy_returns_exit_1(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.evidence_io import write_gate_marker
        write_gate_marker(self.tmp, "orphan", "abc")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["doctor"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(output["healthy"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateDoctorActionTests -v`
Expected: KeyError — `"doctor"` not in dispatch.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
from story_automator.core.gate_ops import gate_doctor


def gate_doctor_action(args: list[str]) -> int:
    project_root = _project_root()
    result = gate_doctor(project_root)
    print_json(result)
    return 0 if result["healthy"] else 1
```

Add `"doctor": gate_doctor_action` to the `dispatch` dict in `gate_dispatch`. Update `_gate_usage` to include `gate doctor`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate doctor CLI command for health checks" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Gate CLI — list Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_ops.list_verdicts` (Task 4).
- Produces: `gate_list_action(args) -> int` — CLI: `gate list [--target=<id>] [--verdict=<PASS|FAIL|CONCERNS|WAIVED>]`. Prints JSON array of verdict summaries.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
class GateListActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str, overall: str) -> None:
        from story_automator.core.gate_schema import make_gate_file
        from story_automator.core.evidence_io import persist_gate_file
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": overall, "required": {}, "actual": {}, "rationale": "ok"}},
            overall=overall,
        )
        persist_gate_file(self.tmp, gate)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_list_all(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["list"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(len(output["verdicts"]), 2)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_list_filter_by_verdict(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["list", "--verdict=FAIL"])
        output = json.loads(out.getvalue())
        self.assertEqual(len(output["verdicts"]), 1)
        self.assertEqual(output["verdicts"][0]["overall"], "FAIL")

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_list_filter_by_target(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "PASS")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["list", "--target=s1"])
        output = json.loads(out.getvalue())
        self.assertEqual(len(output["verdicts"]), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateListActionTests -v`
Expected: KeyError — `"list"` not in dispatch.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
from story_automator.core.gate_ops import list_verdicts


def gate_list_action(args: list[str]) -> int:
    project_root = _project_root()
    target_filter = None
    verdict_filter = None
    for arg in args:
        if arg.startswith("--target="):
            target_filter = arg.split("=", 1)[1]
        elif arg.startswith("--verdict="):
            verdict_filter = arg.split("=", 1)[1]
    verdicts = list_verdicts(
        project_root,
        target_filter=target_filter,
        verdict_filter=verdict_filter,
    )
    print_json({"ok": True, "verdicts": verdicts, "count": len(verdicts)})
    return 0
```

Add `"list": gate_list_action` to `dispatch` dict. Update `_gate_usage`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate list CLI command for verdict history queries" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Gate CLI — summary Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_ops.gate_summary` (Task 7).
- Produces: `gate_summary_action(args) -> int` — CLI: `gate summary`. Prints JSON with aggregate gate metrics.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
class GateSummaryActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_summary_empty_project(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["summary"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["total_verdicts"], 0)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_summary_with_verdicts(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.gate_schema import make_gate_file
        from story_automator.core.evidence_io import persist_gate_file
        for gid, verdict in [("g1", "PASS"), ("g2", "FAIL")]:
            gate = make_gate_file(
                gate_id=gid,
                target={"kind": "story", "id": f"s-{gid}"},
                commit_sha="abc",
                profile={"id": "test", "version": 1, "hash": "aabb"},
                factory_version="1.15.0",
                categories={"c": {"verdict": verdict, "required": {}, "actual": {}, "rationale": "ok"}},
                overall=verdict,
            )
            persist_gate_file(self.tmp, gate)
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["summary"])
        output = json.loads(out.getvalue())
        self.assertEqual(output["total_verdicts"], 2)
        self.assertEqual(output["by_verdict"]["PASS"], 1)
        self.assertEqual(output["by_verdict"]["FAIL"], 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateSummaryActionTests -v`
Expected: KeyError — `"summary"` not in dispatch.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
from story_automator.core.gate_ops import gate_summary as _gate_summary


def gate_summary_action(args: list[str]) -> int:
    project_root = _project_root()
    summary = _gate_summary(project_root)
    print_json(summary)
    return 0
```

Add `"summary": gate_summary_action` to `dispatch` dict. Update `_gate_usage`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate summary CLI command for aggregate metrics" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Gate CLI — rerun Command

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_status.invalidate_gates_for_target`, `gate_status.resume_story`.
- Produces: `gate_rerun_action(args) -> int` — CLI: `gate rerun <target_id>`. Convenience command that: (1) invalidates all gates for the target, (2) resumes any parked story matching the target. Prints JSON summary of what was invalidated and resumed. This does NOT trigger a new gate evaluation — it prepares the state so the next orchestrator run will re-evaluate.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
class GateRerunActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_rerun_invalidates_and_resumes(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        from story_automator.core.gate_schema import make_gate_file
        from story_automator.core.evidence_io import persist_gate_file
        from story_automator.core.gate_status import park_story
        gate = make_gate_file(
            gate_id="g1",
            target={"kind": "story", "id": "story-rerun"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        persist_gate_file(self.tmp, gate)
        park_story(self.tmp, "g1", "story-rerun", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["rerun", "story-rerun"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["invalidated_count"], 1)
        self.assertEqual(output["resumed_count"], 1)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_rerun_requires_target(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["rerun"])
        self.assertEqual(code, 1)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_rerun_rejects_traversal(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["rerun", "../../etc/passwd"])
        self.assertEqual(code, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py::GateRerunActionTests -v`
Expected: KeyError — `"rerun"` not in dispatch.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_cmd.py`:

```python
def gate_rerun_action(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "target_id required"})
        return 1
    target_id = args[0]
    if not _SAFE_ID.match(target_id):
        print_json({"ok": False, "error": "invalid target_id format"})
        return 1
    project_root = _project_root()
    invalidated = invalidate_gates_for_target(project_root, target_id)
    resumed: list[str] = []
    parked = list_parked(project_root)
    for record in parked:
        if record.get("story_key") == target_id:
            gate_id = record.get("gate_id", "")
            if gate_id:
                result = resume_story(project_root, gate_id)
                if result is not None:
                    resumed.append(gate_id)
    print_json({
        "ok": True,
        "target": target_id,
        "invalidated": invalidated,
        "invalidated_count": len(invalidated),
        "resumed": resumed,
        "resumed_count": len(resumed),
    })
    return 0
```

Add `"rerun": gate_rerun_action` to `dispatch` dict. Update `_gate_usage`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_cmd.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add gate rerun CLI command for invalidate+resume convenience" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Audit Chain End-to-End Integration Test

**Files:**
- Create: `tests/test_gate_m11_integration.py`

**Interfaces:**
- Consumes: all M10 + M11 gate modules.
- Produces: integration test verifying the full audit event chain emitted by `run_production_gate`: GateStarted → EvidenceCollected (from collector_runner, but mocked) → GateDecision → GateRendered → GateCompleted. Verifies events are hash-chained in the audit log and contain expected fields.

- [ ] **Step 1: Write the tests**

Create `tests/test_gate_m11_integration.py`:

```python
"""Integration tests for M11 gate operations.

Comprehensive operational scenarios covering audit chain, duration
tracking, concurrent safety, remediation write-back, and CLI
round-trips through the new M11 subcommands.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.commands.gate_cmd import gate_dispatch
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record, persist_gate_file
from story_automator.core.gate_orchestrator import run_production_gate, route_gate_verdict
from story_automator.core.gate_ops import (
    apply_remediation,
    enrich_route_with_runbook,
    gate_doctor,
    gate_summary,
    list_verdicts,
)
from story_automator.core.gate_schema import make_evidence_record, make_gate_file
from story_automator.core.gate_status import park_story
from story_automator.core.product_profile import compute_profile_hash

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


class AuditChainIntegrationTests(unittest.TestCase):
    """Verify run_production_gate emits the full audit chain."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.audit_path = pathlib.Path(self.tmp) / "audit.jsonl"
        self.audit_policy = {"security": {"audit_trail": True}}
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_full_audit_chain_on_pass(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(
                collector="c", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="s", tool="t", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
        ]
        for e in evidence:
            persist_evidence_record(self.tmp, "audit-chain-1", e)
        mock_run.return_value = []
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
            gate = run_production_gate(
                self.tmp, "audit-chain-1", commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=PROFILE, factory_version="1.15.0",
                registry=self.registry,
                audit_policy=self.audit_policy,
                audit_path=self.audit_path,
            )
        self.assertTrue(self.audit_path.exists())
        lines = self.audit_path.read_text().strip().split("\n")
        events = [json.loads(line)["event"] for line in lines]
        self.assertIn("GateStarted", events)
        self.assertIn("GateDecision", events)
        self.assertIn("GateRendered", events)
        self.assertIn("GateCompleted", events)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_completed_event_has_duration(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "audit-dur-1", evidence[0])
        mock_run.return_value = []
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
            run_production_gate(
                self.tmp, "audit-dur-1", commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=PROFILE, factory_version="1.15.0",
                registry=self.registry,
                audit_policy=self.audit_policy,
                audit_path=self.audit_path,
            )
        lines = self.audit_path.read_text().strip().split("\n")
        completed = [json.loads(l) for l in lines if json.loads(l)["event"] == "GateCompleted"]
        self.assertEqual(len(completed), 1)
        self.assertIn("duration_ms", completed[0]["payload"])
        self.assertGreaterEqual(completed[0]["payload"]["duration_ms"], 0)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_m11_integration.py::AuditChainIntegrationTests -v`
Expected: All tests PASS (depends on Tasks 1-3).

- [ ] **Step 3: Commit**

```bash
git add tests/test_gate_m11_integration.py
git commit -m "test(gate): add audit chain end-to-end integration tests for M11" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Multi-Story Operational Scenario Integration Tests

**Files:**
- Modify: `tests/test_gate_m11_integration.py`

**Interfaces:**
- Consumes: all M10 + M11 modules.
- Produces: realistic multi-story operational scenarios testing the complete M11 surface:
  1. **FAIL → remediate → write-back → resume** — full remediation lifecycle
  2. **Park → rerun CLI → clean state** — park then convenience rerun
  3. **Doctor after crash recovery** — crash → recover → doctor reports healthy
  4. **Summary across multiple verdicts** — aggregate metrics accuracy
  5. **List + filter round-trip** — CLI list with filters
  6. **Runbook enrichment through route** — verdict routing with runbook refs

- [ ] **Step 1: Write the tests**

Append to `tests/test_gate_m11_integration.py`:

```python
class RemediationWriteBackIntegrationTests(unittest.TestCase):
    """FAIL → route → apply_remediation → story file updated."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.story_path = Path(self.tmp) / "E1-001.md"
        self.story_path.write_text(
            "---\nStatus: in-progress\n---\n\n## Tasks\n- [ ] Original task\n",
            encoding="utf-8",
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_fail_remediate_writes_to_story(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="error", findings=["test failure"],
        )]
        persist_evidence_record(self.tmp, "rem-1", evidence[0])
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "rem-1", commit_sha="abc",
            target={"kind": "story", "id": "E1-001"},
            profile=PROFILE, factory_version="1.15.0",
            registry=CollectorRegistry(),
        )
        self.assertEqual(gate["overall"], "FAIL")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(route["action"], "remediate")
        result = apply_remediation(self.story_path, route)
        self.assertTrue(result["applied"])
        self.assertGreaterEqual(result["tasks_written"], 1)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review]", content)
        self.assertIn("Original task", content)


class ParkRerunCLIIntegrationTests(unittest.TestCase):
    """Park → rerun CLI → clean state."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_park_then_rerun(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        gate = make_gate_file(
            gate_id="g-rerun",
            target={"kind": "story", "id": "rerun-target"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        persist_gate_file(self.tmp, gate)
        park_story(self.tmp, "g-rerun", "rerun-target", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["rerun", "rerun-target"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["invalidated_count"], 1)
        self.assertEqual(output["resumed_count"], 1)
        verdicts_dir = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        active = [p for p in verdicts_dir.glob("*.json") if not p.name.endswith(".invalidated.json")]
        self.assertEqual(len(active), 0)


class DoctorAfterCrashIntegrationTests(unittest.TestCase):
    """Crash → recover → doctor reports healthy."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_doctor_healthy_after_crash_recovery(self) -> None:
        from story_automator.core.gate_orchestrator import recover_from_crash
        from story_automator.core.evidence_io import write_gate_marker
        write_gate_marker(self.tmp, "crash-doc", "abc")
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "crash-doc"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "partial.json").write_text("{}")
        self.assertFalse(gate_doctor(self.tmp)["healthy"])
        recover_from_crash(self.tmp)
        self.assertTrue(gate_doctor(self.tmp)["healthy"])


class SummaryAccuracyIntegrationTests(unittest.TestCase):
    """Summary metrics match actual verdicts."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_summary_matches_verdicts(self) -> None:
        for gid, verdict in [("g1", "PASS"), ("g2", "PASS"), ("g3", "FAIL"), ("g4", "CONCERNS")]:
            gate = make_gate_file(
                gate_id=gid,
                target={"kind": "story", "id": f"s-{gid}"},
                commit_sha="abc",
                profile={"id": "test", "version": 1, "hash": "aabb"},
                factory_version="1.15.0",
                categories={"c": {"verdict": verdict, "required": {}, "actual": {}, "rationale": "ok"}},
                overall=verdict,
            )
            persist_gate_file(self.tmp, gate)
        summary = gate_summary(self.tmp)
        self.assertEqual(summary["total_verdicts"], 4)
        self.assertEqual(summary["by_verdict"]["PASS"], 2)
        self.assertEqual(summary["by_verdict"]["FAIL"], 1)
        self.assertEqual(summary["by_verdict"]["CONCERNS"], 1)
        verdicts = list_verdicts(self.tmp)
        self.assertEqual(len(verdicts), summary["total_verdicts"])


class RunbookEnrichmentIntegrationTests(unittest.TestCase):
    """Route results enriched with runbook references."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_fail_route_enriched_with_runbook(self) -> None:
        gate = make_gate_file(
            gate_id="g-enrich",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        enriched = enrich_route_with_runbook(route)
        self.assertIn("section-4", enriched["runbook_ref"])
        self.assertEqual(enriched["action"], route["action"])

    def test_park_route_enriched_with_runbook(self) -> None:
        gate = make_gate_file(
            gate_id="g-park-rb",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=3, max_cycles=3,
        )
        enriched = enrich_route_with_runbook(route)
        self.assertIn("section-3", enriched["runbook_ref"])


class CLINewCommandsRoundTripTests(unittest.TestCase):
    """Round-trip tests for M11 CLI commands."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_doctor_list_summary_round_trip(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        gate = make_gate_file(
            gate_id="g-rt",
            target={"kind": "story", "id": "s-rt"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["doctor"])
        doc = json.loads(out.getvalue())
        self.assertTrue(doc["healthy"])

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["list"])
        lst = json.loads(out.getvalue())
        self.assertEqual(lst["count"], 1)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["summary"])
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["total_verdicts"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run all tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_m11_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gate_m11_integration.py
git commit -m "test(gate): add comprehensive M11 operational scenario integration tests" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: Final Validation and Runbook Update

**Files:**
- Modify: `docs/operations/gate-troubleshooting.md`

**Interfaces:**
- Consumes: all M11 deliverables.
- Produces: Updated runbook with M11 CLI commands documented. Adds entries for `gate doctor`, `gate list`, `gate summary`, `gate rerun` under appropriate sections. No new sections — adds to existing sections 3, 7, and adds a new section 10 for operational queries.

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + new).

- [ ] **Step 2: Update runbook**

Add to `docs/operations/gate-troubleshooting.md`:

In section 3 (PARK + Remediation), add the `gate rerun` command:

```markdown
# After fixing the issue, invalidate + resume in one step:
orchestrator-helper gate rerun <story_id>
```

In section 7 (Atomic-Gate Crash Recovery), add the `gate doctor` command:

```markdown
# Comprehensive health check after recovery:
orchestrator-helper gate doctor
```

Add new section 10:

```markdown
## 10. Operational Queries

List all gate verdicts:

```bash
orchestrator-helper gate list
orchestrator-helper gate list --verdict=FAIL
orchestrator-helper gate list --target=<story_id>
```

Aggregate metrics:

```bash
orchestrator-helper gate summary
```

Health check:

```bash
orchestrator-helper gate doctor
```

- [ ] **Step 3: Run ruff lint check**

Run: `ruff check skills/bmad-story-automator/src/story_automator/core/gate_ops.py skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py skills/bmad-story-automator/src/story_automator/core/gate_audit.py skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
Expected: No errors.

- [ ] **Step 4: Run full test suite again**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/operations/gate-troubleshooting.md
git commit -m "docs(gate): update runbook with M11 operational query commands" \
  --trailer "Generated-By: claude-opus-4-6"
```
