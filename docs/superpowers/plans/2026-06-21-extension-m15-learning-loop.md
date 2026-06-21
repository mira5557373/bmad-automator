# Extension M15: Learning Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the feedback loop: gate telemetry from past runs feeds into metrics aggregation, pattern detection, and profile auto-tuning — so the production bar evolves from real evidence, not guesswork. Implements §15.5 (learning loop) and §17 (profile semver split for non-breaking auto-tuning).

**Architecture:** Six new modules plus minimal modifications to existing orchestrator infrastructure:
- `gate_history.py` (~200 LOC) — persistent gate result store with filtering and pruning.
- `gate_metrics.py` (~300 LOC) — aggregate statistics, flaky/timeout/trend detection from history.
- `profile_versioning.py` (~250 LOC) — semver split (`breaking` + `feature`), breaking-change classification, migration from integer version.
- `profile_calibrator.py` (~300 LOC) — propose + apply profile auto-tuning with safety bounds.
- `retrospective_bridge.py` (~150 LOC) — format gate data for BMAD retrospective consumption.
- `learning_loop.py` (~200 LOC) — orchestrate: history → metrics → calibrate → retrospective → audit.

**Dependency graph:** All existing m1–m10 modules consumed but NOT modified except: `gate_orchestrator.py` (hook for history recording, breaking-hash reuse fallback ~+30 LOC), `gate_audit.py` (`GateCalibrationAudit` ~+25 LOC), `product_profile.py` (accept version dict alongside integer ~+40 LOC). Import direction: `gate_history.py` → `gate_metrics.py` → `profile_calibrator.py` → `learning_loop.py` (strictly unidirectional).

**Key existing interfaces consumed:**
- `evidence_io.py`: `load_gate_file`, `can_reuse_gate_file`, `load_evidence_bundle`
- `gate_orchestrator.py`: `run_production_gate`, `route_gate_verdict`, `check_gate_reuse`
- `gate_schema.py`: `canonical_json`, `GateSchemaError`, `validate_gate_file`
- `gate_audit.py`: `emit_gate_audit`, existing audit event pattern
- `gate_rules.py`: `aggregate_verdicts`
- `product_profile.py`: `compute_profile_hash`, `load_effective_profile`, `_validate_profile_shape`
- `gate_status.py`: `record_mitigation_debt`, `load_mitigation_debt`
- `utils.py`: `iso_now`, `md5_hex8`, `write_atomic`, `ensure_dir`, `read_text`
- `trust_boundary.py`: `assert_host_context`

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT modify existing m1–m9 module logic** except: `gate_orchestrator.py` (learning hook + breaking-hash reuse), `gate_audit.py` (new event), `product_profile.py` (version dict support).
- **500-LOC soft limit per Python module.**
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path; use `write_atomic` for atomic writes.
- **Existing tests must pass.** Every modification to existing modules must preserve backward compatibility.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_history.py` — gate result history store (~200 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_metrics.py` — metrics computation from history (~300 LOC)
- `skills/bmad-story-automator/src/story_automator/core/profile_versioning.py` — semver split + breaking-change detection (~250 LOC)
- `skills/bmad-story-automator/src/story_automator/core/profile_calibrator.py` — auto-tuning proposals + application (~300 LOC)
- `skills/bmad-story-automator/src/story_automator/core/retrospective_bridge.py` — BMAD retrospective integration (~150 LOC)
- `skills/bmad-story-automator/src/story_automator/core/learning_loop.py` — learning loop orchestration (~200 LOC)
- `tests/test_gate_history.py` — unit tests (~300 LOC)
- `tests/test_gate_metrics.py` — unit tests (~350 LOC)
- `tests/test_profile_versioning.py` — unit tests (~300 LOC)
- `tests/test_profile_calibrator.py` — unit tests (~350 LOC)
- `tests/test_retrospective_bridge.py` — unit tests (~200 LOC)
- `tests/test_learning_loop.py` — unit tests (~250 LOC)
- `tests/test_learning_loop_integration.py` — end-to-end integration tests (~250 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — add learning hook after verdict + breaking-hash reuse fallback (~+30 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — add `GateCalibrationAudit` event (~+25 LOC)
- `skills/bmad-story-automator/src/story_automator/core/product_profile.py` — accept version dict `{breaking: int, feature: int}` alongside integer (~+40 LOC)
- `tests/test_gate_audit.py` — tests for new audit event (~+30 LOC)
- `tests/test_gate_orchestrator.py` — tests for learning hook + breaking-hash reuse (~+50 LOC)
- `tests/test_product_profile.py` — tests for version dict support (~+40 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/verdict_engine.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`, `core/category_rules.py`, `core/gate_remediation.py`, `core/gate_status.py`, `commands/gate_cmd.py`.

---

### Task 1: Gate History — Data Model and Persistence

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_history.py`
- Create: `tests/test_gate_history.py`

**Interfaces:**
- Consumes: `gate_schema.canonical_json`, `utils.iso_now`, `utils.write_atomic`, `utils.ensure_dir`, `trust_boundary.assert_host_context`
- Produces:
  - `make_history_record(gate_file, *, story_key, remediation_cycle=0)` → `dict` — extract learning-relevant fields from a gate file
  - `record_gate_result(project_root, gate_file, *, story_key, remediation_cycle=0)` → `Path` — persist a history record to `_bmad/gate/history/<timestamp>-<gate_id>.json`

**Data model — history record:**
```python
{
    "gate_id": str,
    "story_key": str,
    "commit_sha": str,
    "overall": str,  # PASS|CONCERNS|FAIL|WAIVED
    "categories": {cat: {"verdict": str, "rationale": str}, ...},
    "profile_id": str,
    "profile_hash": str,
    "factory_version": str,
    "recorded_at": str,  # ISO8601
    "remediation_cycle": int,
    "evidence_bundle_hash": str,
}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_history.py`:

```python
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_history import (
    make_history_record,
    record_gate_result,
)


def _make_gate_file(
    gate_id="g-001",
    overall="PASS",
    commit_sha="abc123",
    categories=None,
    profile_hash="aabb",
    profile_id="default",
    factory_version="1.15.0",
    evidence_bundle_hash="eebb",
):
    return {
        "gate_id": gate_id,
        "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code",
        "commit_sha": commit_sha,
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": profile_hash},
        "factory_version": factory_version,
        "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "all green"},
            "security": {"verdict": "PASS", "rationale": "clean"},
        },
        "overall": overall,
        "waivers": [],
        "evidence_bundle_hash": evidence_bundle_hash,
    }


class MakeHistoryRecordTests(unittest.TestCase):
    def test_extracts_core_fields(self) -> None:
        gf = _make_gate_file()
        rec = make_history_record(gf, story_key="E1-001")
        self.assertEqual(rec["gate_id"], "g-001")
        self.assertEqual(rec["story_key"], "E1-001")
        self.assertEqual(rec["overall"], "PASS")
        self.assertEqual(rec["commit_sha"], "abc123")
        self.assertEqual(rec["profile_id"], "default")
        self.assertEqual(rec["profile_hash"], "aabb")
        self.assertEqual(rec["factory_version"], "1.15.0")
        self.assertEqual(rec["evidence_bundle_hash"], "eebb")
        self.assertIn("recorded_at", rec)

    def test_extracts_category_verdicts(self) -> None:
        gf = _make_gate_file(categories={
            "security": {"verdict": "FAIL", "rationale": "vuln found"},
        })
        rec = make_history_record(gf, story_key="E1-001")
        self.assertEqual(rec["categories"]["security"]["verdict"], "FAIL")

    def test_remediation_cycle_default(self) -> None:
        rec = make_history_record(_make_gate_file(), story_key="E1-001")
        self.assertEqual(rec["remediation_cycle"], 0)

    def test_remediation_cycle_explicit(self) -> None:
        rec = make_history_record(
            _make_gate_file(), story_key="E1-001", remediation_cycle=2,
        )
        self.assertEqual(rec["remediation_cycle"], 2)


class RecordGateResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persists_to_history_dir(self) -> None:
        gf = _make_gate_file()
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        self.assertTrue(path.is_file())
        self.assertIn("history", str(path))

    def test_persisted_record_is_valid_json(self) -> None:
        gf = _make_gate_file()
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["gate_id"], "g-001")

    def test_filename_contains_gate_id(self) -> None:
        gf = _make_gate_file(gate_id="my-gate-42")
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        self.assertIn("my-gate-42", path.name)
```

- [ ] **Step 2: Implement the production code**

Create `skills/bmad-story-automator/src/story_automator/core/gate_history.py`:

```python
"""Gate history store — persistent record of gate results for learning.

Records gate outcomes for cross-story/cross-sprint analysis, pattern
detection, and profile auto-tuning.  Storage layout:
    _bmad/gate/history/<timestamp>-<gate_id>.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic


_HISTORY_DIR = Path("_bmad") / "gate" / "history"


def make_history_record(
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> dict[str, Any]:
    """Extract learning-relevant fields from a gate file."""
    profile = gate_file.get("profile") or {}
    categories_raw = gate_file.get("categories") or {}
    categories = {}
    for cat, info in categories_raw.items():
        if isinstance(info, dict):
            categories[cat] = {
                "verdict": info.get("verdict", ""),
                "rationale": info.get("rationale", ""),
            }
    return {
        "gate_id": gate_file.get("gate_id", ""),
        "story_key": story_key,
        "commit_sha": gate_file.get("commit_sha", ""),
        "overall": gate_file.get("overall", ""),
        "categories": categories,
        "profile_id": profile.get("id", ""),
        "profile_hash": profile.get("hash", ""),
        "factory_version": gate_file.get("factory_version", ""),
        "recorded_at": iso_now(),
        "remediation_cycle": remediation_cycle,
        "evidence_bundle_hash": gate_file.get("evidence_bundle_hash", ""),
    }


def record_gate_result(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> Path:
    """Persist a gate result to the history store."""
    assert_host_context("record_gate_result")
    record = make_history_record(
        gate_file, story_key=story_key,
        remediation_cycle=remediation_cycle,
    )
    history_dir = Path(project_root) / _HISTORY_DIR
    ensure_dir(history_dir)
    timestamp = record["recorded_at"].replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    gate_id = record["gate_id"]
    filename = f"{timestamp}-{gate_id}.json"
    target = history_dir / filename
    write_atomic(target, canonical_json(record) + "\n")
    return target
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_history.py -v --tb=short
```

---

### Task 2: Gate History — Loading and Filtering

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_history.py`
- Modify: `tests/test_gate_history.py`

**Interfaces:**
- Produces:
  - `load_gate_history(project_root, *, since=None, profile_id=None, story_key=None, overall=None)` → `list[dict]` — load and filter history records
  - `count_gate_history(project_root)` → `int` — count total history entries (lightweight, no JSON parse)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_history.py`:

```python
from story_automator.core.gate_history import (
    load_gate_history,
    count_gate_history,
)


class LoadGateHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_history(self) -> None:
        records = load_gate_history(self.tmp)
        self.assertEqual(records, [])

    def test_loads_persisted_records(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-002"), story_key="E1-002")
        records = load_gate_history(self.tmp)
        self.assertEqual(len(records), 2)

    def test_sorted_chronologically(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-a"), story_key="E1-001")
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-b"), story_key="E1-002")
        records = load_gate_history(self.tmp)
        self.assertEqual(records[0]["gate_id"], "g-a")
        self.assertEqual(records[1]["gate_id"], "g-b")

    def test_filter_by_profile_id(self) -> None:
        record_gate_result(
            self.tmp, _make_gate_file(profile_id="default"), story_key="E1-001",
        )
        record_gate_result(
            self.tmp,
            _make_gate_file(gate_id="g-002", profile_id="msme-erp"),
            story_key="E1-002",
        )
        records = load_gate_history(self.tmp, profile_id="msme-erp")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["profile_id"], "msme-erp")

    def test_filter_by_story_key(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002"), story_key="E2-003",
        )
        records = load_gate_history(self.tmp, story_key="E1-001")
        self.assertEqual(len(records), 1)

    def test_filter_by_overall(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(overall="PASS"), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002", overall="FAIL"),
            story_key="E1-002",
        )
        records = load_gate_history(self.tmp, overall="FAIL")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["overall"], "FAIL")

    def test_filter_by_since(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        records = load_gate_history(self.tmp, since="2099-01-01T00:00:00Z")
        self.assertEqual(len(records), 0)
        records_all = load_gate_history(self.tmp, since="2000-01-01T00:00:00Z")
        self.assertEqual(len(records_all), 1)


class CountGateHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty(self) -> None:
        self.assertEqual(count_gate_history(self.tmp), 0)

    def test_counts_files(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002"), story_key="E1-002",
        )
        self.assertEqual(count_gate_history(self.tmp), 2)
```

- [ ] **Step 2: Implement `load_gate_history` and `count_gate_history`**

Append to `core/gate_history.py`:

```python
def load_gate_history(
    project_root: str | Path,
    *,
    since: str | None = None,
    profile_id: str | None = None,
    story_key: str | None = None,
    overall: str | None = None,
) -> list[dict[str, Any]]:
    """Load history records, optionally filtered."""
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if profile_id and data.get("profile_id") != profile_id:
            continue
        if story_key and data.get("story_key") != story_key:
            continue
        if overall and data.get("overall") != overall:
            continue
        if since and data.get("recorded_at", "") < since:
            continue
        records.append(data)
    return records


def count_gate_history(project_root: str | Path) -> int:
    """Count history entries without parsing JSON."""
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return 0
    return len(list(history_dir.glob("*.json")))
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_history.py -v --tb=short
```

---

### Task 3: Gate History — Pruning

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_history.py`
- Modify: `tests/test_gate_history.py`

**Interfaces:**
- Produces:
  - `prune_gate_history(project_root, *, max_age_days=90, max_records=1000)` → `int` — remove old entries, return count pruned

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_history.py`:

```python
from story_automator.core.gate_history import prune_gate_history


class PruneGateHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prune_empty(self) -> None:
        pruned = prune_gate_history(self.tmp, max_age_days=1)
        self.assertEqual(pruned, 0)

    def test_prune_old_records(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        # Nothing pruned when max_age_days is large
        pruned = prune_gate_history(self.tmp, max_age_days=365)
        self.assertEqual(pruned, 0)
        self.assertEqual(count_gate_history(self.tmp), 1)

    def test_prune_by_max_records(self) -> None:
        for i in range(5):
            record_gate_result(
                self.tmp, _make_gate_file(gate_id=f"g-{i:03d}"),
                story_key=f"E1-{i:03d}",
            )
        pruned = prune_gate_history(self.tmp, max_records=3)
        self.assertEqual(pruned, 2)
        self.assertEqual(count_gate_history(self.tmp), 3)

    def test_prune_keeps_newest(self) -> None:
        for i in range(5):
            record_gate_result(
                self.tmp, _make_gate_file(gate_id=f"g-{i:03d}"),
                story_key=f"E1-{i:03d}",
            )
        prune_gate_history(self.tmp, max_records=2)
        remaining = load_gate_history(self.tmp)
        gate_ids = [r["gate_id"] for r in remaining]
        self.assertIn("g-003", gate_ids)
        self.assertIn("g-004", gate_ids)
```

- [ ] **Step 2: Implement `prune_gate_history`**

Append to `core/gate_history.py`:

```python
def prune_gate_history(
    project_root: str | Path,
    *,
    max_age_days: int = 90,
    max_records: int = 1000,
) -> int:
    """Remove old history entries. Returns count pruned.

    Prunes entries older than max_age_days AND trims to max_records
    (keeping the newest). Age pruning runs first.
    """
    assert_host_context("prune_gate_history")
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return 0

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    files = sorted(history_dir.glob("*.json"))
    pruned = 0

    # Phase 1: age-based pruning
    surviving: list[Path] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            surviving.append(path)
            continue
        recorded = data.get("recorded_at", "") if isinstance(data, dict) else ""
        if recorded and recorded < cutoff_iso:
            path.unlink(missing_ok=True)
            pruned += 1
        else:
            surviving.append(path)

    # Phase 2: max-records pruning (keep newest)
    if len(surviving) > max_records:
        to_remove = surviving[:len(surviving) - max_records]
        for path in to_remove:
            path.unlink(missing_ok=True)
            pruned += 1

    return pruned
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_history.py -v --tb=short
```

---

### Task 4: Gate Metrics — Basic Rates

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_metrics.py`
- Create: `tests/test_gate_metrics.py`

**Interfaces:**
- Consumes: history records (list of dicts from `gate_history.load_gate_history`)
- Produces:
  - `compute_gate_metrics(history)` → `dict` — overall pass/fail/concerns/waived rates + per-category breakdown

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_metrics.py`:

```python
import unittest

from story_automator.core.gate_metrics import compute_gate_metrics


def _hist(
    gate_id="g-001",
    overall="PASS",
    categories=None,
    profile_id="default",
    story_key="E1-001",
):
    return {
        "gate_id": gate_id,
        "story_key": story_key,
        "overall": overall,
        "categories": categories or {},
        "profile_id": profile_id,
        "profile_hash": "aabb",
        "factory_version": "1.15.0",
        "recorded_at": "2026-06-20T12:00:00Z",
        "remediation_cycle": 0,
        "evidence_bundle_hash": "eebb",
        "commit_sha": "abc123",
    }


class ComputeGateMetricsTests(unittest.TestCase):
    def test_empty_history(self) -> None:
        m = compute_gate_metrics([])
        self.assertEqual(m["total_gates"], 0)
        self.assertEqual(m["pass_rate"], 0.0)

    def test_all_pass(self) -> None:
        history = [_hist(gate_id=f"g-{i}", overall="PASS") for i in range(5)]
        m = compute_gate_metrics(history)
        self.assertEqual(m["total_gates"], 5)
        self.assertAlmostEqual(m["pass_rate"], 1.0)
        self.assertAlmostEqual(m["fail_rate"], 0.0)

    def test_mixed_verdicts(self) -> None:
        history = [
            _hist(gate_id="g-0", overall="PASS"),
            _hist(gate_id="g-1", overall="FAIL"),
            _hist(gate_id="g-2", overall="CONCERNS"),
            _hist(gate_id="g-3", overall="WAIVED"),
        ]
        m = compute_gate_metrics(history)
        self.assertEqual(m["total_gates"], 4)
        self.assertAlmostEqual(m["pass_rate"], 0.25)
        self.assertAlmostEqual(m["fail_rate"], 0.25)
        self.assertAlmostEqual(m["concerns_rate"], 0.25)
        self.assertAlmostEqual(m["waived_rate"], 0.25)

    def test_per_category_counts(self) -> None:
        history = [
            _hist(gate_id="g-0", categories={
                "security": {"verdict": "PASS", "rationale": ""},
            }),
            _hist(gate_id="g-1", categories={
                "security": {"verdict": "FAIL", "rationale": "vuln"},
            }),
        ]
        m = compute_gate_metrics(history)
        self.assertEqual(m["per_category"]["security"]["pass_count"], 1)
        self.assertEqual(m["per_category"]["security"]["fail_count"], 1)
```

- [ ] **Step 2: Implement `compute_gate_metrics`**

Create `skills/bmad-story-automator/src/story_automator/core/gate_metrics.py`:

```python
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
        "flaky_categories": [],
        "timeout_categories": [],
    }
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_metrics.py -v --tb=short
```

---

### Task 5: Gate Metrics — Flaky and Timeout Detection

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_metrics.py`
- Modify: `tests/test_gate_metrics.py`

**Interfaces:**
- Produces:
  - `detect_flaky_categories(history, *, min_flips=3)` → `list[str]` — categories that alternate PASS/FAIL
  - `detect_timeout_categories(history, *, min_rate=0.3)` → `list[str]` — categories with recurring timeouts
  - The `compute_gate_metrics` function now populates `flaky_categories` and `timeout_categories` from these detectors

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_metrics.py`:

```python
from story_automator.core.gate_metrics import (
    detect_flaky_categories,
    detect_timeout_categories,
)


class DetectFlakyCategoriesTests(unittest.TestCase):
    def test_no_flaky_when_all_pass(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": "PASS", "rationale": ""},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_flaky_categories(history), [])

    def test_detects_alternating_pass_fail(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        result = detect_flaky_categories(history, min_flips=3)
        self.assertIn("correctness", result)

    def test_below_min_flips_not_flagged(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        result = detect_flaky_categories(history, min_flips=3)
        self.assertEqual(result, [])

    def test_ignores_na_categories(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "accessibility": {"verdict": "NA", "rationale": ""},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_flaky_categories(history), [])


class DetectTimeoutCategoriesTests(unittest.TestCase):
    def test_no_timeouts(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "PASS", "rationale": "clean"},
            })
            for i in range(5)
        ]
        self.assertEqual(detect_timeout_categories(history), [])

    def test_high_timeout_rate_detected(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            })
            for i in range(4)
        ] + [
            _hist(gate_id="g-4", categories={
                "performance": {"verdict": "PASS", "rationale": "ok"},
            })
        ]
        result = detect_timeout_categories(history, min_rate=0.3)
        self.assertIn("performance", result)

    def test_low_timeout_rate_not_flagged(self) -> None:
        history = [
            _hist(gate_id="g-0", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            }),
        ] + [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {"verdict": "PASS", "rationale": "ok"},
            })
            for i in range(1, 10)
        ]
        result = detect_timeout_categories(history, min_rate=0.3)
        self.assertEqual(result, [])
```

- [ ] **Step 2: Implement detection functions**

Append to `core/gate_metrics.py`:

```python
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
```

Update `compute_gate_metrics` to call the detectors — replace the hardcoded empty lists at the end of the function:

```python
    return {
        "total_gates": total,
        "pass_rate": counts["PASS"] / total,
        "fail_rate": counts["FAIL"] / total,
        "concerns_rate": counts["CONCERNS"] / total,
        "waived_rate": counts["WAIVED"] / total,
        "per_category": per_cat,
        "flaky_categories": detect_flaky_categories(history),
        "timeout_categories": detect_timeout_categories(history),
    }
```

Also add a test to `tests/test_gate_metrics.py` verifying `compute_gate_metrics` populates these fields:

```python
    def test_metrics_includes_flaky_from_detector(self) -> None:
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "correctness": {"verdict": v, "rationale": ""},
            })
            for i, v in enumerate(verdicts)
        ]
        m = compute_gate_metrics(history)
        self.assertIn("correctness", m["flaky_categories"])

    def test_metrics_includes_timeout_from_detector(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "performance": {
                    "verdict": "FAIL",
                    "rationale": "TIMEOUT: lighthouse exceeded 600s",
                },
            })
            for i in range(4)
        ]
        m = compute_gate_metrics(history)
        self.assertIn("performance", m["timeout_categories"])
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_metrics.py -v --tb=short
```

---

### Task 6: Gate Metrics — Category Trends

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_metrics.py`
- Modify: `tests/test_gate_metrics.py`

**Interfaces:**
- Produces:
  - `compute_category_trends(history, *, window=10)` → `dict[str, str]` — per-category trend direction: `"improving"`, `"stable"`, or `"degrading"`
  - Integrated into `compute_gate_metrics` via a `trends` key in `per_category`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_metrics.py`:

```python
from story_automator.core.gate_metrics import compute_category_trends


class ComputeCategoryTrendsTests(unittest.TestCase):
    def test_empty_history(self) -> None:
        self.assertEqual(compute_category_trends([]), {})

    def test_all_pass_is_stable(self) -> None:
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "PASS", "rationale": ""},
            })
            for i in range(10)
        ]
        trends = compute_category_trends(history)
        self.assertEqual(trends.get("security"), "stable")

    def test_improving_trend(self) -> None:
        # First half FAIL, second half PASS
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "FAIL" if i < 5 else "PASS", "rationale": ""},
            })
            for i in range(10)
        ]
        trends = compute_category_trends(history)
        self.assertEqual(trends.get("security"), "improving")

    def test_degrading_trend(self) -> None:
        # First half PASS, second half FAIL
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "PASS" if i < 5 else "FAIL", "rationale": ""},
            })
            for i in range(10)
        ]
        trends = compute_category_trends(history)
        self.assertEqual(trends.get("security"), "degrading")

    def test_window_limits_scope(self) -> None:
        # Old records all FAIL, recent all PASS — with window=3
        history = [
            _hist(gate_id=f"g-{i}", categories={
                "security": {"verdict": "FAIL" if i < 7 else "PASS", "rationale": ""},
            })
            for i in range(10)
        ]
        trends = compute_category_trends(history, window=3)
        # Last 3 are PASS, so improving or stable
        self.assertIn(trends.get("security"), ("improving", "stable"))
```

- [ ] **Step 2: Implement `compute_category_trends`**

Append to `core/gate_metrics.py`:

```python
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
        first_pass = sum(1 for v in first_half if v == "PASS") / len(first_half) if first_half else 0
        second_pass = sum(1 for v in second_half if v == "PASS") / len(second_half) if second_half else 0
        diff = second_pass - first_pass
        if diff > 0.1:
            trends[cat] = "improving"
        elif diff < -0.1:
            trends[cat] = "degrading"
        else:
            trends[cat] = "stable"
    return trends
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_metrics.py -v --tb=short
```

---

### Task 7: Profile Versioning — Version Model and Parsing

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/profile_versioning.py`
- Create: `tests/test_profile_versioning.py`

**Interfaces:**
- Produces:
  - `ProfileVersion` dataclass — `breaking: int`, `feature: int`
  - `parse_profile_version(profile)` → `ProfileVersion` — handles both integer and dict formats
  - `format_profile_version(version)` → `dict` — serialize to `{breaking: int, feature: int}`
  - `bump_profile_version(profile, change_type)` → `dict` — return updated profile with bumped version
  - `has_semver_profile(profile)` → `bool` — True if profile uses the dict version format

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_versioning.py`:

```python
import copy
import unittest

from story_automator.core.profile_versioning import (
    ProfileVersion,
    bump_profile_version,
    format_profile_version,
    has_semver_profile,
    parse_profile_version,
)


class ParseProfileVersionTests(unittest.TestCase):
    def test_integer_version(self) -> None:
        profile = {"version": 3, "id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 3)
        self.assertEqual(pv.feature, 0)

    def test_dict_version(self) -> None:
        profile = {"version": {"breaking": 2, "feature": 5}, "id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 2)
        self.assertEqual(pv.feature, 5)

    def test_missing_version_defaults(self) -> None:
        profile = {"id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 0)


class FormatProfileVersionTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        pv = ProfileVersion(breaking=2, feature=3)
        d = format_profile_version(pv)
        self.assertEqual(d, {"breaking": 2, "feature": 3})


class HasSemverProfileTests(unittest.TestCase):
    def test_integer_version(self) -> None:
        self.assertFalse(has_semver_profile({"version": 1}))

    def test_dict_version(self) -> None:
        self.assertTrue(has_semver_profile({"version": {"breaking": 1, "feature": 0}}))


class BumpProfileVersionTests(unittest.TestCase):
    def test_bump_feature(self) -> None:
        profile = {"version": {"breaking": 1, "feature": 2}, "id": "test",
                    "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]},
                               "P1": {"coverage_pct": 90, "levels": ["unit"]},
                               "P2": {"coverage_pct": 50, "levels": ["unit"]},
                               "P3": {"coverage_pct": 20, "levels": ["smoke"]}},
                    "categories": {"code": [], "system": []}}
        result = bump_profile_version(profile, "feature")
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 3)

    def test_bump_breaking_resets_feature(self) -> None:
        profile = {"version": {"breaking": 1, "feature": 5}, "id": "test",
                    "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]},
                               "P1": {"coverage_pct": 90, "levels": ["unit"]},
                               "P2": {"coverage_pct": 50, "levels": ["unit"]},
                               "P3": {"coverage_pct": 20, "levels": ["smoke"]}},
                    "categories": {"code": [], "system": []}}
        result = bump_profile_version(profile, "breaking")
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 2)
        self.assertEqual(pv.feature, 0)

    def test_bump_from_integer_upgrades_format(self) -> None:
        profile = {"version": 1, "id": "test",
                    "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]},
                               "P1": {"coverage_pct": 90, "levels": ["unit"]},
                               "P2": {"coverage_pct": 50, "levels": ["unit"]},
                               "P3": {"coverage_pct": 20, "levels": ["smoke"]}},
                    "categories": {"code": [], "system": []}}
        result = bump_profile_version(profile, "feature")
        self.assertTrue(has_semver_profile(result))
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 1)

    def test_original_not_mutated(self) -> None:
        profile = {"version": {"breaking": 1, "feature": 0}, "id": "test",
                    "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]},
                               "P1": {"coverage_pct": 90, "levels": ["unit"]},
                               "P2": {"coverage_pct": 50, "levels": ["unit"]},
                               "P3": {"coverage_pct": 20, "levels": ["smoke"]}},
                    "categories": {"code": [], "system": []}}
        original = copy.deepcopy(profile)
        bump_profile_version(profile, "feature")
        self.assertEqual(profile, original)
```

- [ ] **Step 2: Implement the production code**

Create `skills/bmad-story-automator/src/story_automator/core/profile_versioning.py`:

```python
"""Profile versioning — semver split for auto-tuning (§17).

Splits profile.version into {breaking, feature} so auto-tuning can
bump the feature version without forcing re-evaluation of existing
gate files. Breaking changes (matrix thresholds, categories, rules)
force re-gates; feature changes (timeouts, cost_tier) do not.
"""
from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any

from .utils import md5_hex8


@dataclasses.dataclass(frozen=True)
class ProfileVersion:
    breaking: int = 1
    feature: int = 0


def parse_profile_version(profile: dict[str, Any]) -> ProfileVersion:
    """Parse version from profile, handling both int and dict formats."""
    version = profile.get("version")
    if isinstance(version, dict):
        return ProfileVersion(
            breaking=int(version.get("breaking", 1)),
            feature=int(version.get("feature", 0)),
        )
    if isinstance(version, int) and not isinstance(version, bool):
        return ProfileVersion(breaking=version, feature=0)
    return ProfileVersion()


def format_profile_version(pv: ProfileVersion) -> dict[str, int]:
    """Serialize a ProfileVersion to a dict."""
    return {"breaking": pv.breaking, "feature": pv.feature}


def has_semver_profile(profile: dict[str, Any]) -> bool:
    """True if the profile uses the dict version format."""
    return isinstance(profile.get("version"), dict)


def bump_profile_version(
    profile: dict[str, Any],
    change_type: str,
) -> dict[str, Any]:
    """Return a copy of the profile with a bumped version.

    change_type="feature" bumps the feature version.
    change_type="breaking" bumps breaking and resets feature to 0.
    """
    result = copy.deepcopy(profile)
    pv = parse_profile_version(result)
    if change_type == "breaking":
        new_pv = ProfileVersion(breaking=pv.breaking + 1, feature=0)
    else:
        new_pv = ProfileVersion(breaking=pv.breaking, feature=pv.feature + 1)
    result["version"] = format_profile_version(new_pv)
    return result
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_profile_versioning.py -v --tb=short
```

---

### Task 8: Profile Versioning — Breaking-Change Detection + Breaking Hash

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/profile_versioning.py`
- Modify: `tests/test_profile_versioning.py`

**Interfaces:**
- Produces:
  - `BREAKING_FIELDS` — frozenset of top-level profile keys whose changes are breaking
  - `FEATURE_FIELDS` — frozenset of non-breaking fields
  - `is_breaking_change(old_profile, new_profile)` → `bool` — True if any breaking field changed
  - `classify_changes(old_profile, new_profile)` → `list[dict]` — list of changed fields with classification
  - `compute_breaking_hash(profile)` → `str` — hash only breaking-sensitive fields (for gate reuse)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_versioning.py`:

```python
from story_automator.core.profile_versioning import (
    BREAKING_FIELDS,
    FEATURE_FIELDS,
    classify_changes,
    compute_breaking_hash,
    is_breaking_change,
)


_BASE_PROFILE = {
    "version": {"breaking": 1, "feature": 0},
    "id": "test",
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": ["unit"]},
        "P1": {"coverage_pct": 90, "levels": ["unit"]},
        "P2": {"coverage_pct": 50, "levels": ["unit"]},
        "P3": {"coverage_pct": 20, "levels": ["smoke"]},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
    "rules": {"security": {"sast_max_high": 0}},
    "timeouts": {"security": 300},
    "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
    "forbidden_until": {},
    "invariants": {"registry_file": ""},
    "toolchain": {},
    "seed_template": {},
    "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
}


class IsBreakingChangeTests(unittest.TestCase):
    def test_no_change(self) -> None:
        self.assertFalse(is_breaking_change(_BASE_PROFILE, copy.deepcopy(_BASE_PROFILE)))

    def test_timeout_change_is_not_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        self.assertFalse(is_breaking_change(_BASE_PROFILE, new))

    def test_matrix_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_categories_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["categories"]["code"].append("docs")
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_rules_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["rules"]["security"]["sast_max_high"] = 1
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_cost_tier_change_is_not_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["cost_tier"]["arpu_monthly"] = 100
        self.assertFalse(is_breaking_change(_BASE_PROFILE, new))


class ClassifyChangesTests(unittest.TestCase):
    def test_no_changes(self) -> None:
        self.assertEqual(classify_changes(_BASE_PROFILE, copy.deepcopy(_BASE_PROFILE)), [])

    def test_classifies_timeout_as_feature(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        changes = classify_changes(_BASE_PROFILE, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["field"], "timeouts")
        self.assertEqual(changes[0]["change_type"], "feature")

    def test_classifies_matrix_as_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        changes = classify_changes(_BASE_PROFILE, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["field"], "matrix")
        self.assertEqual(changes[0]["change_type"], "breaking")


class ComputeBreakingHashTests(unittest.TestCase):
    def test_same_profile_same_hash(self) -> None:
        h1 = compute_breaking_hash(_BASE_PROFILE)
        h2 = compute_breaking_hash(copy.deepcopy(_BASE_PROFILE))
        self.assertEqual(h1, h2)

    def test_timeout_change_same_hash(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        self.assertEqual(
            compute_breaking_hash(_BASE_PROFILE),
            compute_breaking_hash(new),
        )

    def test_matrix_change_different_hash(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        self.assertNotEqual(
            compute_breaking_hash(_BASE_PROFILE),
            compute_breaking_hash(new),
        )
```

- [ ] **Step 2: Implement detection + breaking hash**

Append to `core/profile_versioning.py`:

```python
BREAKING_FIELDS: frozenset[str] = frozenset({
    "matrix", "categories", "categories_na", "rules",
    "invariants", "toolchain", "forbidden_until",
})

FEATURE_FIELDS: frozenset[str] = frozenset({
    "timeouts", "cost_tier", "snapshot", "seed_template",
})

# Fields excluded from both: "version", "id" (identity, not semantics)


def is_breaking_change(
    old_profile: dict[str, Any],
    new_profile: dict[str, Any],
) -> bool:
    """True if any breaking-sensitive field changed."""
    for field in BREAKING_FIELDS:
        old_val = json.dumps(old_profile.get(field), sort_keys=True)
        new_val = json.dumps(new_profile.get(field), sort_keys=True)
        if old_val != new_val:
            return True
    return False


def classify_changes(
    old_profile: dict[str, Any],
    new_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """List changed fields with their breaking/feature classification."""
    changes: list[dict[str, Any]] = []
    for field in sorted(BREAKING_FIELDS | FEATURE_FIELDS):
        old_val = json.dumps(old_profile.get(field), sort_keys=True)
        new_val = json.dumps(new_profile.get(field), sort_keys=True)
        if old_val != new_val:
            change_type = "breaking" if field in BREAKING_FIELDS else "feature"
            changes.append({
                "field": field,
                "change_type": change_type,
                "old_value": old_profile.get(field),
                "new_value": new_profile.get(field),
            })
    return changes


def compute_breaking_hash(profile: dict[str, Any]) -> str:
    """Hash only breaking-sensitive fields for gate reuse comparison."""
    breaking_data = {
        field: profile.get(field) for field in sorted(BREAKING_FIELDS)
    }
    canonical = json.dumps(breaking_data, sort_keys=True, separators=(",", ":"))
    return md5_hex8(canonical)
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_profile_versioning.py -v --tb=short
```

---

### Task 9: Profile Backward Compatibility — Accept Version Dict

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Modifies: `_validate_version_and_id` to accept both `int` and `dict` version formats
- Existing tests must pass unchanged (integer version remains valid)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_product_profile.py`. First add the `_make_valid_profile` helper near the top of the file (after imports, before any test class):

```python
def _make_valid_profile():
    """Minimal valid profile dict for unit tests that don't need file I/O."""
    return {
        "version": 1,
        "id": "test",
        "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [],
        "rules": {},
        "timeouts": {},
        "cost_tier": {},
        "forbidden_until": {},
        "invariants": {},
        "toolchain": {},
        "seed_template": {},
    }
```

Then add the test class:

```python
class VersionDictValidationTests(unittest.TestCase):
    """Verify that profile validation accepts both integer and dict version."""

    def test_integer_version_still_valid(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = 1
        # Should not raise
        from story_automator.core.product_profile import _validate_profile_shape
        _validate_profile_shape(profile)

    def test_dict_version_valid(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = {"breaking": 1, "feature": 0}
        from story_automator.core.product_profile import _validate_profile_shape
        _validate_profile_shape(profile)

    def test_dict_version_with_feature(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = {"breaking": 2, "feature": 5}
        from story_automator.core.product_profile import _validate_profile_shape
        _validate_profile_shape(profile)

    def test_dict_version_missing_breaking_rejected(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = {"feature": 1}
        from story_automator.core.product_profile import _validate_profile_shape, ProfileError
        with self.assertRaises(ProfileError):
            _validate_profile_shape(profile)

    def test_dict_version_non_positive_breaking_rejected(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = {"breaking": 0, "feature": 1}
        from story_automator.core.product_profile import _validate_profile_shape, ProfileError
        with self.assertRaises(ProfileError):
            _validate_profile_shape(profile)

    def test_string_version_rejected(self) -> None:
        profile = _make_valid_profile()
        profile["version"] = "1.0"
        from story_automator.core.product_profile import _validate_profile_shape, ProfileError
        with self.assertRaises(ProfileError):
            _validate_profile_shape(profile)
```

Where `_make_valid_profile` should be a helper already in the test file or added at the top (reuse existing test fixture pattern).

- [ ] **Step 2: Modify `_validate_version_and_id` in `product_profile.py`**

Replace `_validate_version_and_id` to accept both formats:

```python
def _validate_version_and_id(profile: dict[str, Any]) -> None:
    version = profile.get("version")
    if isinstance(version, dict):
        breaking = version.get("breaking")
        if not isinstance(breaking, int) or isinstance(breaking, bool) or breaking < 1:
            raise ProfileError(
                "profile.version.breaking must be a positive integer"
            )
        feature = version.get("feature")
        if not isinstance(feature, int) or isinstance(feature, bool) or feature < 0:
            raise ProfileError(
                "profile.version.feature must be a non-negative integer"
            )
    elif not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProfileError("profile.version must be a positive integer or {breaking, feature} dict")
    pid = profile.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ProfileError("profile.id must be a non-empty string")
```

- [ ] **Step 3: Run ALL tests to verify backward compatibility**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_product_profile.py tests/test_gate_orchestrator.py tests/test_verdict_engine.py -v --tb=short
```

---

### Task 10: Profile Calibrator — Proposal Model and Timeout Calibration

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/profile_calibrator.py`
- Create: `tests/test_profile_calibrator.py`

**Interfaces:**
- Consumes: metrics from `gate_metrics.compute_gate_metrics`, profile dict
- Produces:
  - `CalibrationProposal` dataclass — `category, field_path, old_value, new_value, rationale, confidence, change_type`
  - `propose_timeout_calibrations(metrics, profile)` → `list[CalibrationProposal]` — auto-adjust timeouts based on timeout patterns

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_calibrator.py`:

```python
import copy
import unittest

from story_automator.core.profile_calibrator import (
    CalibrationProposal,
    propose_timeout_calibrations,
)


_BASE_PROFILE = {
    "version": {"breaking": 1, "feature": 0},
    "id": "test",
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": ["unit"]},
        "P1": {"coverage_pct": 90, "levels": ["unit"]},
        "P2": {"coverage_pct": 50, "levels": ["unit"]},
        "P3": {"coverage_pct": 20, "levels": ["smoke"]},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
    "rules": {},
    "timeouts": {"security": 300},
    "cost_tier": {},
    "forbidden_until": {},
    "invariants": {},
    "toolchain": {},
    "seed_template": {},
    "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
}


class CalibrationProposalTests(unittest.TestCase):
    def test_dataclass_fields(self) -> None:
        p = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300,
            new_value=450,
            rationale="timeout rate 40%",
            confidence=0.85,
            change_type="feature",
        )
        self.assertEqual(p.category, "security")
        self.assertEqual(p.change_type, "feature")


class ProposeTimeoutCalibrationsTests(unittest.TestCase):
    def test_no_timeouts_no_proposals(self) -> None:
        metrics = {
            "timeout_categories": [],
            "per_category": {},
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])

    def test_timeout_category_gets_increase_proposal(self) -> None:
        metrics = {
            "timeout_categories": ["security"],
            "per_category": {
                "security": {
                    "timeout_count": 4,
                    "pass_count": 1,
                    "fail_count": 4,
                    "concerns_count": 0,
                    "na_count": 0,
                },
            },
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].category, "security")
        self.assertGreater(proposals[0].new_value, 300)
        self.assertEqual(proposals[0].change_type, "feature")

    def test_timeout_increase_capped(self) -> None:
        metrics = {
            "timeout_categories": ["security"],
            "per_category": {
                "security": {
                    "timeout_count": 10, "pass_count": 0,
                    "fail_count": 10, "concerns_count": 0, "na_count": 0,
                },
            },
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        # Capped at 2x current (300 * 2 = 600)
        self.assertLessEqual(proposals[0].new_value, 600)
```

- [ ] **Step 2: Implement the production code**

Create `skills/bmad-story-automator/src/story_automator/core/profile_calibrator.py`:

```python
"""Profile calibrator — auto-tuning proposals with safety bounds.

Analyzes gate metrics and proposes profile adjustments: timeout
increases for recurring timeouts, burn-in N for flaky tests,
coverage threshold tweaks. All proposals carry a confidence score
and change_type classification (feature vs breaking).

Safety: breaking changes are never auto-applied; max change bounds
prevent runaway calibration.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from .product_profile import DEFAULT_TIMEOUT_FALLBACK, DEFAULT_TIMEOUTS


MAX_TIMEOUT_MULTIPLIER = 2.0
TIMEOUT_INCREASE_FACTOR = 1.5
MIN_TIMEOUT = 30


@dataclasses.dataclass(frozen=True)
class CalibrationProposal:
    category: str
    field_path: str
    old_value: Any
    new_value: Any
    rationale: str
    confidence: float
    change_type: str  # "feature" or "breaking"


def propose_timeout_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Propose timeout increases for categories with recurring timeouts."""
    timeout_cats = metrics.get("timeout_categories", [])
    if not timeout_cats:
        return []

    profile_timeouts = profile.get("timeouts") or {}
    proposals: list[CalibrationProposal] = []
    for cat in timeout_cats:
        current = profile_timeouts.get(cat, DEFAULT_TIMEOUTS.get(cat, DEFAULT_TIMEOUT_FALLBACK))
        cat_stats = (metrics.get("per_category") or {}).get(cat, {})
        total = sum(cat_stats.get(k, 0) for k in
                    ("pass_count", "fail_count", "concerns_count"))
        timeout_count = cat_stats.get("timeout_count", 0)
        if total == 0:
            continue
        timeout_rate = timeout_count / total
        proposed = min(
            int(current * TIMEOUT_INCREASE_FACTOR),
            int(current * MAX_TIMEOUT_MULTIPLIER),
        )
        if proposed <= current:
            continue
        proposals.append(CalibrationProposal(
            category=cat,
            field_path=f"timeouts.{cat}",
            old_value=current,
            new_value=proposed,
            rationale=f"timeout rate {timeout_rate:.0%} over {total} runs",
            confidence=min(0.5 + timeout_rate, 0.95),
            change_type="feature",
        ))
    return proposals
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_profile_calibrator.py -v --tb=short
```

---

### Task 11: Profile Calibrator — Burn-in and Flaky Calibration

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/profile_calibrator.py`
- Modify: `tests/test_profile_calibrator.py`

**Interfaces:**
- Produces:
  - `propose_burnin_calibrations(metrics, profile)` → `list[CalibrationProposal]` — raise burn-in N when flaky tests detected
  - `propose_all_calibrations(metrics, profile)` → `list[CalibrationProposal]` — aggregate all calibration proposals

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_calibrator.py`:

```python
from story_automator.core.profile_calibrator import (
    propose_burnin_calibrations,
    propose_all_calibrations,
)


class ProposeBurninCalibrationsTests(unittest.TestCase):
    def test_no_flaky_no_proposals(self) -> None:
        metrics = {"flaky_categories": [], "per_category": {}}
        proposals = propose_burnin_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])

    def test_flaky_category_proposes_burnin_increase(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5, "max_flaky": 0}
        metrics = {
            "flaky_categories": ["correctness"],
            "per_category": {"correctness": {
                "pass_count": 5, "fail_count": 5,
                "concerns_count": 0, "na_count": 0, "timeout_count": 0,
            }},
        }
        proposals = propose_burnin_calibrations(metrics, profile)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].field_path, "rules.test_quality.burn_in_runs")
        self.assertGreater(proposals[0].new_value, 5)
        self.assertEqual(proposals[0].change_type, "breaking")

    def test_burnin_capped_at_max(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 18, "max_flaky": 0}
        metrics = {
            "flaky_categories": ["correctness"],
            "per_category": {"correctness": {
                "pass_count": 5, "fail_count": 5,
                "concerns_count": 0, "na_count": 0, "timeout_count": 0,
            }},
        }
        proposals = propose_burnin_calibrations(metrics, profile)
        if proposals:
            self.assertLessEqual(proposals[0].new_value, 20)


class ProposeAllCalibrationsTests(unittest.TestCase):
    def test_combines_timeout_and_burnin(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5, "max_flaky": 0}
        metrics = {
            "timeout_categories": ["security"],
            "flaky_categories": ["correctness"],
            "per_category": {
                "security": {
                    "timeout_count": 4, "pass_count": 1,
                    "fail_count": 4, "concerns_count": 0, "na_count": 0,
                },
                "correctness": {
                    "pass_count": 5, "fail_count": 5,
                    "concerns_count": 0, "na_count": 0, "timeout_count": 0,
                },
            },
        }
        proposals = propose_all_calibrations(metrics, profile)
        categories = [p.category for p in proposals]
        self.assertIn("security", categories)

    def test_empty_metrics_empty_proposals(self) -> None:
        metrics = {
            "timeout_categories": [],
            "flaky_categories": [],
            "per_category": {},
        }
        proposals = propose_all_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])
```

- [ ] **Step 2: Implement burn-in calibration + aggregator**

Append to `core/profile_calibrator.py`:

```python
MAX_BURNIN_RUNS = 20
BURNIN_INCREMENT = 2
DEFAULT_BURNIN_RUNS = 5


def propose_burnin_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Propose burn-in N increase when flaky tests detected."""
    flaky_cats = metrics.get("flaky_categories", [])
    if not flaky_cats:
        return []

    rules = profile.get("rules") or {}
    tq_rules = rules.get("test_quality") or {}
    current_burnin = tq_rules.get("burn_in_runs", DEFAULT_BURNIN_RUNS)
    proposed = min(current_burnin + BURNIN_INCREMENT, MAX_BURNIN_RUNS)
    if proposed <= current_burnin:
        return []

    return [CalibrationProposal(
        category=cat,
        field_path="rules.test_quality.burn_in_runs",
        old_value=current_burnin,
        new_value=proposed,
        rationale=f"flaky category {cat} detected; raising burn-in from {current_burnin} to {proposed}",
        confidence=0.8,
        change_type="breaking",
    ) for cat in flaky_cats]


def propose_all_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Aggregate all calibration proposals."""
    proposals: list[CalibrationProposal] = []
    proposals.extend(propose_timeout_calibrations(metrics, profile))
    proposals.extend(propose_burnin_calibrations(metrics, profile))
    return proposals
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_profile_calibrator.py -v --tb=short
```

---

### Task 12: Profile Calibrator — Apply Calibrations with Safety Bounds

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/profile_calibrator.py`
- Modify: `tests/test_profile_calibrator.py`

**Interfaces:**
- Produces:
  - `apply_calibrations(profile, proposals, *, auto_apply_breaking=False)` → `tuple[dict, list[CalibrationProposal], list[CalibrationProposal]]` — (updated_profile, applied, deferred)
  - Feature proposals auto-apply; breaking proposals deferred unless `auto_apply_breaking=True`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_calibrator.py`:

```python
from story_automator.core.profile_calibrator import apply_calibrations


class ApplyCalibrationsTests(unittest.TestCase):
    def test_apply_feature_change(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        proposal = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300, new_value=450,
            rationale="timeout rate", confidence=0.85,
            change_type="feature",
        )
        updated, applied, deferred = apply_calibrations(profile, [proposal])
        self.assertEqual(updated["timeouts"]["security"], 450)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(deferred), 0)

    def test_defer_breaking_change_by_default(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5}
        proposal = CalibrationProposal(
            category="correctness",
            field_path="rules.test_quality.burn_in_runs",
            old_value=5, new_value=7,
            rationale="flaky", confidence=0.8,
            change_type="breaking",
        )
        updated, applied, deferred = apply_calibrations(profile, [proposal])
        # Breaking change NOT applied
        self.assertEqual(updated["rules"]["test_quality"]["burn_in_runs"], 5)
        self.assertEqual(len(applied), 0)
        self.assertEqual(len(deferred), 1)

    def test_apply_breaking_when_allowed(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5}
        proposal = CalibrationProposal(
            category="correctness",
            field_path="rules.test_quality.burn_in_runs",
            old_value=5, new_value=7,
            rationale="flaky", confidence=0.8,
            change_type="breaking",
        )
        updated, applied, deferred = apply_calibrations(
            profile, [proposal], auto_apply_breaking=True,
        )
        self.assertEqual(updated["rules"]["test_quality"]["burn_in_runs"], 7)
        self.assertEqual(len(applied), 1)

    def test_original_not_mutated(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        proposal = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300, new_value=450,
            rationale="timeout", confidence=0.85,
            change_type="feature",
        )
        original = copy.deepcopy(profile)
        apply_calibrations(profile, [proposal])
        self.assertEqual(profile, original)

    def test_empty_proposals(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        updated, applied, deferred = apply_calibrations(profile, [])
        self.assertEqual(updated, profile)
        self.assertEqual(applied, [])
        self.assertEqual(deferred, [])
```

- [ ] **Step 2: Implement `apply_calibrations`**

Append to `core/profile_calibrator.py`:

```python
import copy as _copy


def apply_calibrations(
    profile: dict[str, Any],
    proposals: list[CalibrationProposal],
    *,
    auto_apply_breaking: bool = False,
) -> tuple[dict[str, Any], list[CalibrationProposal], list[CalibrationProposal]]:
    """Apply calibration proposals to a profile copy.

    Feature-type proposals auto-apply. Breaking-type proposals are
    deferred unless auto_apply_breaking is True. Returns
    (updated_profile, applied_proposals, deferred_proposals).
    """
    result = _copy.deepcopy(profile)
    applied: list[CalibrationProposal] = []
    deferred: list[CalibrationProposal] = []

    for proposal in proposals:
        if proposal.change_type == "breaking" and not auto_apply_breaking:
            deferred.append(proposal)
            continue
        _set_nested(result, proposal.field_path, proposal.new_value)
        applied.append(proposal)

    return result, applied, deferred


def _set_nested(obj: dict[str, Any], path: str, value: Any) -> None:
    """Set a value at a dotted path in a nested dict, creating intermediates."""
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in obj or not isinstance(obj[part], dict):
            obj[part] = {}
        obj = obj[part]
    obj[parts[-1]] = value
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_profile_calibrator.py -v --tb=short
```

---

### Task 13: GateCalibrationAudit Event

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing `emit_gate_audit` pattern, frozen dataclass protocol.
- Produces:
  - `GateCalibrationAudit` — emitted when the learning loop applies a calibration. Fields: `profile_id`, `proposals_applied`, `proposals_deferred`, `old_version`, `new_version`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
from story_automator.core.gate_audit import GateCalibrationAudit


class GateCalibrationAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateCalibrationAudit(
            profile_id="default",
            proposals_applied=2,
            proposals_deferred=1,
            old_version="1.0",
            new_version="1.1",
        )
        self.assertEqual(event.event_name, "GateCalibration")

    def test_to_dict_contains_all_fields(self) -> None:
        event = GateCalibrationAudit(
            profile_id="msme-erp",
            proposals_applied=3,
            proposals_deferred=0,
            old_version="1.2",
            new_version="1.3",
        )
        d = event.to_dict()
        self.assertEqual(d["profile_id"], "msme-erp")
        self.assertEqual(d["proposals_applied"], 3)
        self.assertEqual(d["proposals_deferred"], 0)

    def test_frozen(self) -> None:
        event = GateCalibrationAudit(profile_id="x")
        with self.assertRaises(AttributeError):
            event.profile_id = "y"
```

- [ ] **Step 2: Implement `GateCalibrationAudit`**

Add to `core/gate_audit.py` before the `_AuditEvent` union:

```python
@dataclasses.dataclass(frozen=True)
class GateCalibrationAudit:
    """Audit event: learning loop applied profile calibrations."""
    event_name: str = dataclasses.field(default="GateCalibration", init=False)
    profile_id: str = ""
    proposals_applied: int = 0
    proposals_deferred: int = 0
    old_version: str = ""
    new_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "proposals_applied": self.proposals_applied,
            "proposals_deferred": self.proposals_deferred,
            "old_version": self.old_version,
            "new_version": self.new_version,
        }
```

Update `__all__`, `_AuditEvent` union to include `GateCalibrationAudit`.

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v --tb=short
```

---

### Task 14: Retrospective Bridge

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/retrospective_bridge.py`
- Create: `tests/test_retrospective_bridge.py`

**Interfaces:**
- Consumes: metrics from `gate_metrics`, calibration proposals from `profile_calibrator`
- Produces:
  - `build_retrospective_summary(metrics, calibrations, *, deferred=None)` → `dict` — structured summary
  - `format_retrospective_markdown(summary)` → `str` — markdown-formatted retrospective section

- [ ] **Step 1: Write the failing tests**

Create `tests/test_retrospective_bridge.py`:

```python
import unittest

from story_automator.core.retrospective_bridge import (
    build_retrospective_summary,
    format_retrospective_markdown,
)
from story_automator.core.profile_calibrator import CalibrationProposal


class BuildRetrospectiveSummaryTests(unittest.TestCase):
    def test_empty_inputs(self) -> None:
        summary = build_retrospective_summary(
            {"total_gates": 0, "pass_rate": 0.0, "fail_rate": 0.0,
             "concerns_rate": 0.0, "waived_rate": 0.0,
             "per_category": {}, "flaky_categories": [],
             "timeout_categories": []},
            [],
        )
        self.assertEqual(summary["total_gates"], 0)
        self.assertEqual(summary["calibrations_applied"], 0)

    def test_includes_key_metrics(self) -> None:
        metrics = {
            "total_gates": 10, "pass_rate": 0.7, "fail_rate": 0.2,
            "concerns_rate": 0.1, "waived_rate": 0.0,
            "per_category": {"security": {"fail_count": 2, "pass_count": 8}},
            "flaky_categories": ["correctness"],
            "timeout_categories": ["performance"],
        }
        summary = build_retrospective_summary(metrics, [])
        self.assertEqual(summary["total_gates"], 10)
        self.assertAlmostEqual(summary["pass_rate"], 0.7)
        self.assertIn("correctness", summary["flaky_categories"])
        self.assertIn("performance", summary["timeout_categories"])

    def test_includes_calibration_count(self) -> None:
        metrics = {
            "total_gates": 5, "pass_rate": 0.8, "fail_rate": 0.2,
            "concerns_rate": 0.0, "waived_rate": 0.0,
            "per_category": {}, "flaky_categories": [],
            "timeout_categories": [],
        }
        proposals = [
            CalibrationProposal("s", "timeouts.s", 300, 450, "r", 0.9, "feature"),
        ]
        summary = build_retrospective_summary(metrics, proposals)
        self.assertEqual(summary["calibrations_applied"], 1)


class FormatRetrospectiveMarkdownTests(unittest.TestCase):
    def test_produces_markdown(self) -> None:
        summary = {
            "total_gates": 10, "pass_rate": 0.7,
            "fail_rate": 0.2, "concerns_rate": 0.1,
            "waived_rate": 0.0,
            "flaky_categories": ["correctness"],
            "timeout_categories": [],
            "calibrations_applied": 1,
            "calibrations_deferred": 0,
            "top_failing_categories": [("security", 2)],
        }
        md = format_retrospective_markdown(summary)
        self.assertIn("Gate Quality Summary", md)
        self.assertIn("70.0%", md)
        self.assertIn("correctness", md)

    def test_empty_summary(self) -> None:
        summary = {
            "total_gates": 0, "pass_rate": 0.0,
            "fail_rate": 0.0, "concerns_rate": 0.0,
            "waived_rate": 0.0,
            "flaky_categories": [],
            "timeout_categories": [],
            "calibrations_applied": 0,
            "calibrations_deferred": 0,
            "top_failing_categories": [],
        }
        md = format_retrospective_markdown(summary)
        self.assertIsInstance(md, str)
        self.assertIn("No gate evaluations", md)
```

- [ ] **Step 2: Implement the production code**

Create `skills/bmad-story-automator/src/story_automator/core/retrospective_bridge.py`:

```python
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
        return "## Gate Quality Summary\n\nNo gate evaluations recorded in this period.\n"

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
        lines.append(f"**Calibrations:** {applied} applied, {deferred} deferred (breaking)")
        lines.append("")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_retrospective_bridge.py -v --tb=short
```

---

### Task 15: Learning Loop — Full Pipeline

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/learning_loop.py`
- Create: `tests/test_learning_loop.py`

**Interfaces:**
- Consumes: `gate_history`, `gate_metrics`, `profile_calibrator`, `profile_versioning`, `retrospective_bridge`, `gate_audit`
- Produces:
  - `run_learning_loop(project_root, *, profile=None, auto_apply_breaking=False, audit_policy=None, audit_path=None)` → `dict` — full pipeline result
  - `record_gate_for_learning(project_root, gate_file, *, story_key, remediation_cycle=0)` → `Path` — hook called after each gate evaluation

- [ ] **Step 1: Write the failing tests**

Create `tests/test_learning_loop.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.learning_loop import (
    record_gate_for_learning,
    run_learning_loop,
)


def _make_gate_file(
    gate_id="g-001", overall="PASS", profile_id="default",
    profile_hash="aabb", categories=None,
):
    return {
        "gate_id": gate_id,
        "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code",
        "commit_sha": "abc123",
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": profile_hash},
        "factory_version": "1.15.0",
        "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "ok"},
        },
        "overall": overall,
        "waivers": [],
        "evidence_bundle_hash": "eebb",
    }


def _make_profile():
    return {
        "version": 1, "id": "default",
        "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [], "rules": {}, "timeouts": {},
        "cost_tier": {}, "forbidden_until": {},
        "invariants": {}, "toolchain": {}, "seed_template": {},
    }


class RecordGateForLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_records_to_history(self) -> None:
        gf = _make_gate_file()
        path = record_gate_for_learning(self.tmp, gf, story_key="E1-001")
        self.assertTrue(path.is_file())


class RunLearningLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_history_returns_summary(self) -> None:
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["metrics"]["total_gates"], 0)
        self.assertEqual(result["calibrations_applied"], [])

    def test_with_history_computes_metrics(self) -> None:
        for i in range(3):
            record_gate_for_learning(
                self.tmp, _make_gate_file(gate_id=f"g-{i}"),
                story_key=f"E1-{i:03d}",
            )
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["metrics"]["total_gates"], 3)

    def test_returns_retrospective_markdown(self) -> None:
        record_gate_for_learning(
            self.tmp, _make_gate_file(), story_key="E1-001",
        )
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertIn("Gate Quality Summary", result["retrospective_md"])
```

- [ ] **Step 2: Implement the production code**

Create `skills/bmad-story-automator/src/story_automator/core/learning_loop.py`:

```python
"""Learning loop orchestrator — gate telemetry → metrics → calibrate → retro.

Ties together the learning loop pipeline: loads gate history, computes
metrics, proposes calibrations, applies safe changes, and generates
retrospective summaries for BMAD consumption.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .gate_history import load_gate_history, record_gate_result
from .gate_metrics import compute_gate_metrics
from .profile_calibrator import apply_calibrations, propose_all_calibrations
from .profile_versioning import (
    bump_profile_version,
    format_profile_version,
    parse_profile_version,
)
from .retrospective_bridge import (
    build_retrospective_summary,
    format_retrospective_markdown,
)


def record_gate_for_learning(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> Path:
    """Hook called after each gate evaluation to record for learning."""
    return record_gate_result(
        project_root, gate_file,
        story_key=story_key, remediation_cycle=remediation_cycle,
    )


def run_learning_loop(
    project_root: str | Path,
    *,
    profile: dict[str, Any] | None = None,
    auto_apply_breaking: bool = False,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full learning loop pipeline.

    1. Load gate history
    2. Compute aggregate metrics
    3. Propose calibrations
    4. Apply safe (feature) calibrations
    5. Build retrospective summary + markdown
    6. Emit audit event for calibrations (if any applied)
    """
    history = load_gate_history(project_root)
    metrics = compute_gate_metrics(history)

    calibrations_applied: list[Any] = []
    calibrations_deferred: list[Any] = []
    updated_profile = profile

    if profile is not None:
        proposals = propose_all_calibrations(metrics, profile)
        if proposals:
            updated_profile, calibrations_applied, calibrations_deferred = (
                apply_calibrations(
                    profile, proposals,
                    auto_apply_breaking=auto_apply_breaking,
                )
            )

            if calibrations_applied:
                has_breaking_applied = any(
                    p.change_type == "breaking" for p in calibrations_applied
                )
                bump_type = "breaking" if has_breaking_applied else "feature"
                updated_profile = bump_profile_version(updated_profile, bump_type)

            if calibrations_applied and audit_policy is not None and audit_path is not None:
                from .gate_audit import GateCalibrationAudit, emit_gate_audit
                old_pv = parse_profile_version(profile)
                new_pv = parse_profile_version(updated_profile)
                emit_gate_audit(
                    audit_policy, audit_path,
                    GateCalibrationAudit(
                        profile_id=profile.get("id", ""),
                        proposals_applied=len(calibrations_applied),
                        proposals_deferred=len(calibrations_deferred),
                        old_version=f"{old_pv.breaking}.{old_pv.feature}",
                        new_version=f"{new_pv.breaking}.{new_pv.feature}",
                    ),
                )

    summary = build_retrospective_summary(
        metrics, calibrations_applied,
        calibrations_deferred=calibrations_deferred,
    )
    retro_md = format_retrospective_markdown(summary)

    return {
        "metrics": metrics,
        "calibrations_applied": calibrations_applied,
        "calibrations_deferred": calibrations_deferred,
        "updated_profile": updated_profile,
        "retrospective_summary": summary,
        "retrospective_md": retro_md,
    }
```

- [ ] **Step 3: Run tests and verify**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_learning_loop.py -v --tb=short
```

---

### Task 16: Gate Orchestrator — Learning Hook and Breaking-Hash Reuse

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`

**Interfaces:**
- Modifies: `route_gate_verdict` — after verdict routing, call `record_gate_for_learning` to persist history
- Modifies: `check_gate_reuse` — when profile hash mismatch but breaking hash matches (semver profile), treat gate as reusable

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_orchestrator.py`:

```python
class LearningHookTests(unittest.TestCase):
    """Verify that route_gate_verdict records gate results for learning."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_orchestrator.assert_host_context",
        )
        self.mock_host = self.patcher.start()
        self.history_patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.history_patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.history_patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pass_verdict_records_history(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        from story_automator.core.gate_history import count_gate_history
        gate_file = {
            "gate_id": "g-001", "overall": "PASS",
            "categories": {}, "commit_sha": "abc",
            "profile": {"id": "default", "version": 1, "hash": "h"},
            "factory_version": "1.0.0", "evidence_bundle_hash": "e",
            "schema_version": 1, "target": {"kind": "story", "id": "s1"},
            "waivers": [],
        }
        route_gate_verdict(
            self.tmp, gate_file, story_key="E1-001",
        )
        self.assertEqual(count_gate_history(self.tmp), 1)


class BreakingHashReuseTests(unittest.TestCase):
    """Verify that semver profiles use breaking hash for reuse."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_orchestrator.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_feature_only_change_still_reusable(self) -> None:
        from story_automator.core.gate_orchestrator import check_gate_reuse
        from story_automator.core.evidence_io import persist_gate_file
        from story_automator.core.profile_versioning import compute_breaking_hash
        from story_automator.core.product_profile import compute_profile_hash
        from unittest.mock import patch as mpatch

        profile_v1 = {
            "version": {"breaking": 1, "feature": 0},
            "id": "test",
            "matrix": {"P0": {"coverage_pct": 100, "levels": ["u"]},
                       "P1": {"coverage_pct": 90, "levels": ["u"]},
                       "P2": {"coverage_pct": 50, "levels": ["u"]},
                       "P3": {"coverage_pct": 20, "levels": ["s"]}},
            "categories": {"code": [], "system": []},
            "categories_na": [], "rules": {},
            "timeouts": {"security": 300},
            "cost_tier": {}, "forbidden_until": {},
            "invariants": {}, "toolchain": {},
            "seed_template": {},
            "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        }
        # Store a gate file with v1 profile
        with mpatch("story_automator.core.evidence_io.assert_host_context"):
            persist_gate_file(self.tmp, {
                "gate_id": "g-001", "schema_version": 1,
                "target": {"kind": "story", "id": "s1"},
                "tier": "code", "commit_sha": "abc123",
                "scanner_data_snapshot": "",
                "profile": {
                    "id": "test", "version": {"breaking": 1, "feature": 0},
                    "hash": compute_profile_hash(profile_v1),
                    "breaking_hash": compute_breaking_hash(profile_v1),
                },
                "factory_version": "1.15.0",
                "risk_profile_ref": "",
                "categories": {"correctness": {"verdict": "PASS"}},
                "overall": "PASS", "waivers": [],
                "evidence_bundle_hash": "eebb",
            })

        # v2 has different timeouts (feature change only)
        import copy
        profile_v2 = copy.deepcopy(profile_v1)
        profile_v2["version"] = {"breaking": 1, "feature": 1}
        profile_v2["timeouts"]["security"] = 600

        gate_file, reason = check_gate_reuse(
            self.tmp, "g-001", "abc123", profile_v2, "1.15.0",
        )
        self.assertIsNotNone(gate_file, f"Expected reuse, got rejection: {reason}")
```

- [ ] **Step 2: Modify `gate_orchestrator.py`**

Add the learning hook to `route_gate_verdict` and the breaking-hash fallback to `check_gate_reuse`:

In `route_gate_verdict`, add after the existing logic (before any return that has `action`), import and call:
```python
from .learning_loop import record_gate_for_learning
# At the top of route_gate_verdict, before the verdict routing logic:
record_gate_for_learning(
    project_root, gate_file,
    story_key=story_key, remediation_cycle=remediation_cycle,
)
```

In `check_gate_reuse`, add breaking-hash fallback after `can_reuse_gate_file` returns False:
```python
if not reusable and "profile.hash mismatch" in reason:
    from .profile_versioning import compute_breaking_hash, has_semver_profile
    if has_semver_profile(profile):
        current_bh = compute_breaking_hash(profile)
        old_bh = (gate_file.get("profile") or {}).get("breaking_hash", "")
        if old_bh and current_bh == old_bh:
            return gate_file, ""
```

In `run_production_gate`, after `evaluate_gate` returns the gate_file and before the final `return gate_file`, enrich the persisted gate file with `breaking_hash` so the reuse fallback above can find it on future runs:
```python
from .profile_versioning import compute_breaking_hash, has_semver_profile
from .evidence_io import persist_gate_file as _re_persist

if has_semver_profile(profile):
    gate_file["profile"]["breaking_hash"] = compute_breaking_hash(profile)
    _re_persist(project_root, gate_file)
```

Also add `persist_gate_file` to the existing `evidence_io` import block at the top of the file. This adds a second write for semver profiles, which is acceptable given the gate evaluation is the expensive part.

- [ ] **Step 3: Run ALL tests to verify no regressions**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_orchestrator.py tests/test_gate_history.py tests/test_learning_loop.py -v --tb=short
```

---

### Task 17: End-to-End Integration Tests

**Files:**
- Create: `tests/test_learning_loop_integration.py`

**Interfaces:**
- Full pipeline: gate results → history → metrics → calibration → retrospective

- [ ] **Step 1: Write the integration tests**

Create `tests/test_learning_loop_integration.py`:

```python
"""End-to-end integration tests for the learning loop pipeline."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_history import (
    count_gate_history,
    load_gate_history,
    record_gate_result,
)
from story_automator.core.gate_metrics import compute_gate_metrics
from story_automator.core.learning_loop import (
    record_gate_for_learning,
    run_learning_loop,
)
from story_automator.core.profile_calibrator import propose_all_calibrations
from story_automator.core.profile_versioning import (
    bump_profile_version,
    compute_breaking_hash,
    has_semver_profile,
    is_breaking_change,
    parse_profile_version,
)
from story_automator.core.retrospective_bridge import (
    build_retrospective_summary,
    format_retrospective_markdown,
)


def _make_gate_file(
    gate_id="g-001", overall="PASS",
    categories=None, profile_id="default",
):
    return {
        "gate_id": gate_id, "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code", "commit_sha": "abc123",
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": "aabb"},
        "factory_version": "1.15.0", "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "ok"},
        },
        "overall": overall, "waivers": [],
        "evidence_bundle_hash": "eebb",
    }


def _make_profile():
    return {
        "version": 1, "id": "default",
        "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {"code": ["correctness", "security", "performance"], "system": []},
        "categories_na": [], "rules": {"test_quality": {"burn_in_runs": 5, "max_flaky": 0}},
        "timeouts": {"security": 300, "performance": 600},
        "cost_tier": {}, "forbidden_until": {},
        "invariants": {}, "toolchain": {}, "seed_template": {},
    }


class LearningLoopIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_pipeline_with_timeouts(self) -> None:
        """Simulate repeated timeouts -> learning loop proposes timeout increase."""
        profile = _make_profile()
        # Record gates where performance times out
        for i in range(5):
            gf = _make_gate_file(
                gate_id=f"g-{i}",
                overall="FAIL",
                categories={
                    "correctness": {"verdict": "PASS", "rationale": "ok"},
                    "performance": {
                        "verdict": "FAIL",
                        "rationale": "TIMEOUT: lighthouse exceeded 600s",
                    },
                },
            )
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")

        result = run_learning_loop(self.tmp, profile=profile)
        self.assertEqual(result["metrics"]["total_gates"], 5)
        self.assertIn("performance", result["metrics"]["timeout_categories"])
        # Should have proposed a timeout increase
        timeout_proposals = [
            p for p in result["calibrations_applied"]
            if "timeout" in p.field_path
        ]
        self.assertGreater(len(timeout_proposals), 0)

    def test_full_pipeline_with_flaky(self) -> None:
        """Simulate flaky tests -> learning loop proposes burn-in increase."""
        profile = _make_profile()
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS", "FAIL", "PASS"]
        for i, v in enumerate(verdicts):
            gf = _make_gate_file(
                gate_id=f"g-{i}", overall=v,
                categories={
                    "correctness": {"verdict": v, "rationale": ""},
                },
            )
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")

        result = run_learning_loop(self.tmp, profile=profile)
        self.assertIn("correctness", result["metrics"]["flaky_categories"])
        # Burn-in is a breaking change — should be deferred
        self.assertGreater(len(result["calibrations_deferred"]), 0)

    def test_retrospective_output_is_valid_markdown(self) -> None:
        for i in range(3):
            gf = _make_gate_file(gate_id=f"g-{i}")
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")
        result = run_learning_loop(self.tmp, profile=_make_profile())
        md = result["retrospective_md"]
        self.assertIn("##", md)
        self.assertIn("Gate Quality Summary", md)

    def test_profile_versioning_roundtrip(self) -> None:
        """Feature bump -> different hash -> same breaking hash."""
        profile = _make_profile()
        profile["version"] = {"breaking": 1, "feature": 0}
        bumped = bump_profile_version(profile, "feature")
        pv = parse_profile_version(bumped)
        self.assertEqual(pv.feature, 1)
        self.assertFalse(is_breaking_change(profile, bumped))
        self.assertEqual(
            compute_breaking_hash(profile),
            compute_breaking_hash(bumped),
        )

    def test_breaking_change_different_breaking_hash(self) -> None:
        profile = _make_profile()
        modified = copy.deepcopy(profile)
        modified["matrix"]["P0"]["coverage_pct"] = 95
        self.assertTrue(is_breaking_change(profile, modified))
        self.assertNotEqual(
            compute_breaking_hash(profile),
            compute_breaking_hash(modified),
        )

    def test_history_pruning_preserves_recent(self) -> None:
        from story_automator.core.gate_history import prune_gate_history
        for i in range(10):
            gf = _make_gate_file(gate_id=f"g-{i:03d}")
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")
        pruned = prune_gate_history(self.tmp, max_records=5)
        self.assertEqual(pruned, 5)
        self.assertEqual(count_gate_history(self.tmp), 5)
        remaining = load_gate_history(self.tmp)
        gate_ids = [r["gate_id"] for r in remaining]
        self.assertIn("g-009", gate_ids)
        self.assertNotIn("g-000", gate_ids)

    def test_empty_history_produces_no_calibrations(self) -> None:
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["calibrations_applied"], [])
        self.assertEqual(result["calibrations_deferred"], [])
```

- [ ] **Step 2: Run the full test suite**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_learning_loop_integration.py tests/test_learning_loop.py tests/test_gate_history.py tests/test_gate_metrics.py tests/test_profile_versioning.py tests/test_profile_calibrator.py tests/test_retrospective_bridge.py -v --tb=short
```

- [ ] **Step 3: Run ALL project tests to verify no regressions**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short
```

---

## Summary of Changes

| Module | LOC (est) | New/Modified | Purpose |
|---|---|---|---|
| `core/gate_history.py` | ~150 | New | Gate result history store |
| `core/gate_metrics.py` | ~200 | New | Metrics computation, flaky/timeout/trend detection |
| `core/profile_versioning.py` | ~150 | New | Semver split, breaking-change classification, breaking hash |
| `core/profile_calibrator.py` | ~200 | New | Auto-tuning proposals + application with safety bounds |
| `core/retrospective_bridge.py` | ~100 | New | BMAD retrospective integration |
| `core/learning_loop.py` | ~100 | New | Learning loop orchestration |
| `core/gate_orchestrator.py` | +30 | Modified | Learning hook + breaking-hash reuse fallback |
| `core/gate_audit.py` | +25 | Modified | `GateCalibrationAudit` event |
| `core/product_profile.py` | +20 | Modified | Accept version dict format |
| Tests (7 new files + 3 modified) | ~2000 | New+Modified | Unit + integration tests |
