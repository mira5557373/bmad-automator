# Foundation M2: Evidence Schemas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the evidence record, gate file, and waiver schema layer so M17 (Evidence Collectors) and M18 (Adjudicator) have a stable, forward-compatible data foundation — with LLM evidence support, schema migration, persistence I/O, gate reuse logic, and crash-safe markers.

**Architecture:** Extends M1's `gate_schema.py` (factories + validators) with LLM evidence fields and schema version guards. New `evidence_io.py` module handles all persistence (evidence records, gate files, markers), evidence bundle hashing, schema migration, and gate reuse validation. Pure data + I/O — no subprocess or orchestration logic. Dependency graph: `utils.py ← gate_schema.py ← evidence_io.py` (no coupling to `gate_rules.py` or `adjudicator.py`).

**Tech Stack:** Python 3.11+, stdlib only (`json`, `hashlib`, `pathlib`, `os`); existing `utils.write_atomic`, `utils.read_text`, `utils.ensure_dir`; `unittest`; existing `gate_schema` factories/validators from M1.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** New `GateDecision`/`GateRendered` events land in a later milestone.
- **500-LOC soft limit per Python module.** `evidence_io.py` target ~300 LOC; `gate_schema.py` stays ≤ 320 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py tests/test_gate_rules.py tests/test_evidence_io.py -v` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` — evidence + gate file persistence, bundle hash, migration shim, gate reuse logic, gate-in-progress marker (~300 LOC)
- `tests/test_evidence_io.py` — unit tests for evidence I/O (~400 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/gate_schema.py` — add `make_llm_evidence_record`, `validate_schema_version` (~+50 LOC → ~320 total)
- `skills/bmad-story-automator/src/story_automator/core/gate_rules.py` — add `verdict_for_llm_confidence` (~+15 LOC → ~190 total)
- `tests/test_gate_schema.py` — add LLM evidence + schema version tests (~+60 LOC → ~375 total)
- `tests/test_gate_rules.py` — add LLM confidence verdict tests (~+25 LOC → ~195 total)

**Untouched (explicit):** `core/telemetry_events.py`, `core/telemetry_emitter.py`, `core/audit.py`, `core/adjudicator.py`, `core/product_profile.py`, `core/profile_bridge.py`.

---

### Task 1: LLM Evidence Record Factory + Validation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_schema.py`
- Modify: `tests/test_gate_schema.py`

**Interfaces:**
- Consumes: `EVIDENCE_SCHEMA_VERSION`, `make_evidence_record`, `validate_evidence_record`, `GateSchemaError` (all from M1 `gate_schema.py`)
- Produces: `make_llm_evidence_record(*, collector: str, tool: str, tool_version: str = "", category: str, tier: str = "code", status: str, metrics: dict | None = None, findings: list[str] | None = None, raw_output_ref: str = "", exit_code: int = 0, duration_ms: int = 0, confidence: int, rationale: str) -> dict[str, Any]`; `VALID_CONFIDENCE_RANGE = range(1, 11)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_schema.py`:

```python
class MakeLlmEvidenceRecordTests(unittest.TestCase):
    def test_creates_record_with_confidence_and_rationale(self) -> None:
        record = make_llm_evidence_record(
            collector="llm-reviewer",
            tool="claude",
            category="test_quality",
            status="ok",
            confidence=8,
            rationale="Tests cover all edge cases",
        )
        self.assertEqual(record["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(record["confidence"], 8)
        self.assertEqual(record["rationale"], "Tests cover all edge cases")
        self.assertFalse(record["deterministic"])

    def test_deterministic_always_false(self) -> None:
        record = make_llm_evidence_record(
            collector="llm-reviewer",
            tool="claude",
            category="security",
            status="ok",
            confidence=9,
            rationale="No vulnerabilities found",
        )
        self.assertFalse(record["deterministic"])

    def test_confidence_below_range_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "confidence"):
            make_llm_evidence_record(
                collector="x", tool="x", category="x",
                status="ok", confidence=0, rationale="test",
            )

    def test_confidence_above_range_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "confidence"):
            make_llm_evidence_record(
                collector="x", tool="x", category="x",
                status="ok", confidence=11, rationale="test",
            )

    def test_empty_rationale_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "rationale"):
            make_llm_evidence_record(
                collector="x", tool="x", category="x",
                status="ok", confidence=5, rationale="",
            )

    def test_confidence_boundary_1_accepted(self) -> None:
        record = make_llm_evidence_record(
            collector="x", tool="x", category="x",
            status="ok", confidence=1, rationale="low confidence",
        )
        self.assertEqual(record["confidence"], 1)

    def test_confidence_boundary_10_accepted(self) -> None:
        record = make_llm_evidence_record(
            collector="x", tool="x", category="x",
            status="ok", confidence=10, rationale="high confidence",
        )
        self.assertEqual(record["confidence"], 10)
```

Update the import block at the top of `tests/test_gate_schema.py` to add `make_llm_evidence_record` to the import from `story_automator.core.gate_schema`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py::MakeLlmEvidenceRecordTests -v`
Expected: ImportError — `make_llm_evidence_record` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/gate_schema.py`, after the `VALID_INVARIANT_SEVERITIES` constant:

```python
VALID_CONFIDENCE_RANGE = range(1, 11)  # 1–10 inclusive
```

Add after `make_timeout_evidence`:

```python
def make_llm_evidence_record(
    *,
    collector: str,
    tool: str,
    tool_version: str = "",
    category: str,
    tier: str = "code",
    status: str,
    metrics: dict[str, Any] | None = None,
    findings: list[str] | None = None,
    raw_output_ref: str = "",
    exit_code: int = 0,
    duration_ms: int = 0,
    confidence: int,
    rationale: str,
) -> dict[str, Any]:
    if not isinstance(confidence, int) or isinstance(confidence, bool):
        raise GateSchemaError("evidence.confidence must be an integer")
    if confidence not in VALID_CONFIDENCE_RANGE:
        raise GateSchemaError(
            f"evidence.confidence must be 1..10; got {confidence}"
        )
    if not isinstance(rationale, str) or not rationale.strip():
        raise GateSchemaError("evidence.rationale must be a non-empty string")
    record = make_evidence_record(
        collector=collector,
        tool=tool,
        tool_version=tool_version,
        category=category,
        tier=tier,
        status=status,
        metrics=metrics,
        findings=findings,
        raw_output_ref=raw_output_ref,
        exit_code=exit_code,
        duration_ms=duration_ms,
        deterministic=False,
    )
    record["confidence"] = confidence
    record["rationale"] = rationale
    return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py -v`
Expected: All tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_gate_schema.py skills/bmad-story-automator/src/story_automator/core/gate_schema.py
git commit -m "feat(gate): add LLM evidence record factory with confidence and rationale" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Schema Version Guard

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_schema.py`
- Modify: `tests/test_gate_schema.py`

**Interfaces:**
- Consumes: `GateSchemaError`, `EVIDENCE_SCHEMA_VERSION`, `GATE_SCHEMA_VERSION` (from M1)
- Produces: `validate_schema_version(record: dict[str, Any], max_known: int, label: str) -> None` — raises `GateSchemaError` if `schema_version > max_known` or `< 1`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_schema.py`:

```python
class ValidateSchemaVersionTests(unittest.TestCase):
    def test_current_version_passes(self) -> None:
        validate_schema_version({"schema_version": 1}, max_known=1, label="test")

    def test_older_version_passes(self) -> None:
        validate_schema_version({"schema_version": 1}, max_known=3, label="test")

    def test_future_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "test.schema_version"):
            validate_schema_version(
                {"schema_version": 99}, max_known=1, label="test",
            )

    def test_zero_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "test.schema_version"):
            validate_schema_version(
                {"schema_version": 0}, max_known=1, label="test",
            )

    def test_missing_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "test.schema_version"):
            validate_schema_version({}, max_known=1, label="test")

    def test_non_int_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "test.schema_version"):
            validate_schema_version(
                {"schema_version": "1"}, max_known=1, label="test",
            )
```

Add `validate_schema_version` to the import block.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py::ValidateSchemaVersionTests -v`
Expected: ImportError — `validate_schema_version` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_schema.py` in the Validation section, before the Helpers section:

```python
def validate_schema_version(
    record: dict[str, Any], max_known: int, label: str,
) -> None:
    version = record.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise GateSchemaError(
            f"{label}.schema_version must be an integer"
        )
    if version < 1:
        raise GateSchemaError(
            f"{label}.schema_version must be >= 1; got {version}"
        )
    if version > max_known:
        raise GateSchemaError(
            f"{label}.schema_version {version} exceeds max known "
            f"version {max_known}; upgrade the factory"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_gate_schema.py skills/bmad-story-automator/src/story_automator/core/gate_schema.py
git commit -m "feat(gate): add schema version guard for forward-compat" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: LLM Confidence Verdict Logic

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_rules.py`
- Modify: `tests/test_gate_rules.py`

**Interfaces:**
- Consumes: None from prior tasks (standalone logic).
- Produces: `verdict_for_llm_confidence(confidence: int) -> str` — returns `"CONCERNS"` if confidence < 5, `"PASS"` if >= 5. §6.4: confidence `<5` forces CONCERNS/needs-human.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_rules.py`:

```python
class LlmConfidenceVerdictTests(unittest.TestCase):
    def test_high_confidence_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(8), "PASS")

    def test_low_confidence_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(3), "CONCERNS")

    def test_boundary_5_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(5), "PASS")

    def test_boundary_4_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(4), "CONCERNS")

    def test_minimum_1_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(1), "CONCERNS")

    def test_maximum_10_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(10), "PASS")
```

Add `verdict_for_llm_confidence` to the import from `story_automator.core.gate_rules`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_rules.py::LlmConfidenceVerdictTests -v`
Expected: ImportError — `verdict_for_llm_confidence` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_rules.py` after `verdict_for_collector_status`:

```python
def verdict_for_llm_confidence(confidence: int) -> str:
    """§6.4: LLM confidence < 5 forces CONCERNS/needs-human."""
    if confidence < 5:
        return "CONCERNS"
    return "PASS"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_gate_rules.py skills/bmad-story-automator/src/story_automator/core/gate_rules.py
git commit -m "feat(gate): add LLM confidence verdict logic" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Evidence Migration Shim + evidence_io.py Scaffold

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Create: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `EVIDENCE_SCHEMA_VERSION`, `GateSchemaError`, `canonical_json` (from `gate_schema.py`)
- Produces: `evidence_migrate(record: dict[str, Any], target_version: int = EVIDENCE_SCHEMA_VERSION) -> dict[str, Any]` — deep-copy passthrough for v1→v1; raises on downgrade or unknown target.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evidence_io.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest

from story_automator.core.gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GateSchemaError,
    make_evidence_record,
)
from story_automator.core.evidence_io import (
    evidence_migrate,
)


class EvidenceMigrateTests(unittest.TestCase):
    def _v1_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_v1_to_v1_passthrough(self) -> None:
        original = self._v1_record()
        migrated = evidence_migrate(original)
        self.assertEqual(migrated, original)

    def test_returns_deep_copy(self) -> None:
        original = self._v1_record()
        migrated = evidence_migrate(original)
        migrated["collector"] = "mutated"
        self.assertEqual(original["collector"], "test-collector")

    def test_explicit_target_v1(self) -> None:
        record = self._v1_record()
        migrated = evidence_migrate(record, target_version=1)
        self.assertEqual(migrated["schema_version"], 1)

    def test_downgrade_raises(self) -> None:
        record = self._v1_record()
        record["schema_version"] = 2
        with self.assertRaisesRegex(GateSchemaError, "cannot downgrade"):
            evidence_migrate(record, target_version=1)

    def test_unknown_target_raises(self) -> None:
        record = self._v1_record()
        with self.assertRaisesRegex(GateSchemaError, "unknown target"):
            evidence_migrate(record, target_version=999)

    def test_invalid_schema_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "schema_version"):
            evidence_migrate({"schema_version": "bad"})

    def test_zero_schema_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "schema_version"):
            evidence_migrate({"schema_version": 0})

    def test_llm_evidence_preserves_confidence_and_rationale(self) -> None:
        from story_automator.core.gate_schema import make_llm_evidence_record
        original = make_llm_evidence_record(
            collector="llm-reviewer", tool="claude",
            category="test_quality", status="ok",
            confidence=7, rationale="Good coverage",
        )
        migrated = evidence_migrate(original)
        self.assertEqual(migrated["confidence"], 7)
        self.assertEqual(migrated["rationale"], "Good coverage")
        self.assertFalse(migrated["deterministic"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::EvidenceMigrateTests -v`
Expected: ModuleNotFoundError — `evidence_io` not found.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`:

```python
"""Evidence I/O, migration, and gate lifecycle helpers (§6.4, §9.2, §18).

Handles persistence of evidence records and gate files to
_bmad/gate/{evidence,verdicts}/, evidence bundle hashing,
schema migration shims, gate reuse validation, and
gate-in-progress crash-safety markers.

Artifact layout: _bmad/gate/{risk,evidence,verdicts}/
"""
from __future__ import annotations

import json
from typing import Any

from .gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GateSchemaError,
    canonical_json,
)


def _validate_gate_id(gate_id: str) -> None:
    """Reject gate_ids that could escape the artifact directory."""
    if not gate_id or not isinstance(gate_id, str):
        raise GateSchemaError("gate_id must be a non-empty string")
    if "/" in gate_id or "\\" in gate_id or ".." in gate_id:
        raise GateSchemaError(
            f"gate_id contains invalid path characters: {gate_id!r}"
        )


def evidence_migrate(
    record: dict[str, Any],
    target_version: int = EVIDENCE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """§6.4/§18: migrate evidence record to target schema version.

    v1 is the only known version; returns a deep copy.
    Future versions add elif branches here.
    """
    current = record.get("schema_version")
    if not isinstance(current, int) or isinstance(current, bool) or current < 1:
        raise GateSchemaError(
            "evidence.schema_version must be a positive integer"
        )
    if target_version < 1 or target_version > EVIDENCE_SCHEMA_VERSION:
        raise GateSchemaError(
            f"unknown target evidence schema version: {target_version}"
        )
    if current > target_version:
        raise GateSchemaError(
            f"cannot downgrade evidence from v{current} to v{target_version}"
        )
    return json.loads(json.dumps(record))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add evidence migration shim and evidence_io module" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Evidence Bundle Hash

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `canonical_json` (from `gate_schema.py`), `make_evidence_record` (for test fixtures)
- Produces: `compute_evidence_bundle_hash(records: list[dict[str, Any]]) -> str` — deterministic 16-char hex hash over sorted canonical JSON. §18: same inputs → same verdict, byte-identical.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_evidence_io.py` imports: `compute_evidence_bundle_hash` from `evidence_io`. Then append:

```python
class ComputeEvidenceBundleHashTests(unittest.TestCase):
    def _record(self, category: str, collector: str, tool: str) -> dict:
        return make_evidence_record(
            collector=collector, tool=tool, category=category, status="ok",
        )

    def test_deterministic_same_input(self) -> None:
        records = [
            self._record("correctness", "test-runner", "pytest"),
            self._record("security", "scanner", "semgrep"),
        ]
        hash1 = compute_evidence_bundle_hash(records)
        hash2 = compute_evidence_bundle_hash(records)
        self.assertEqual(hash1, hash2)

    def test_order_independent(self) -> None:
        r1 = self._record("correctness", "test-runner", "pytest")
        r2 = self._record("security", "scanner", "semgrep")
        hash_ab = compute_evidence_bundle_hash([r1, r2])
        hash_ba = compute_evidence_bundle_hash([r2, r1])
        self.assertEqual(hash_ab, hash_ba)

    def test_returns_16_char_hex(self) -> None:
        records = [self._record("correctness", "runner", "pytest")]
        result = compute_evidence_bundle_hash(records)
        self.assertEqual(len(result), 16)
        int(result, 16)

    def test_empty_list_returns_deterministic_hash(self) -> None:
        h1 = compute_evidence_bundle_hash([])
        h2 = compute_evidence_bundle_hash([])
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_different_records_different_hash(self) -> None:
        r1 = [self._record("correctness", "runner", "pytest")]
        r2 = [self._record("security", "scanner", "semgrep")]
        self.assertNotEqual(
            compute_evidence_bundle_hash(r1),
            compute_evidence_bundle_hash(r2),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::ComputeEvidenceBundleHashTests -v`
Expected: ImportError — `compute_evidence_bundle_hash` not defined.

- [ ] **Step 3: Write minimal implementation**

Add `import hashlib` at the top of `evidence_io.py` (after `import json`).

Add after `evidence_migrate`:

```python
def compute_evidence_bundle_hash(records: list[dict[str, Any]]) -> str:
    """§18: deterministic hash over the full evidence bundle.

    Sorts by (category, collector, tool) so order of collection
    does not affect the hash. Returns 16-char hex prefix.
    """
    sorted_records = sorted(
        records,
        key=lambda r: (
            r.get("category", ""),
            r.get("collector", ""),
            r.get("tool", ""),
        ),
    )
    payload = "[" + ",".join(canonical_json(r) for r in sorted_records) + "]"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add deterministic evidence bundle hash" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Evidence Record Persistence (Write)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `validate_evidence_record`, `validate_schema_version`, `EVIDENCE_SCHEMA_VERSION`, `gate_artifact_dir` (from `gate_schema.py`); `write_atomic` (from `utils.py`); `canonical_json` (from `gate_schema.py`)
- Produces: `evidence_filename(record: dict[str, Any]) -> str` — `{category}--{collector}--{tool}.json`; `persist_evidence_record(project_root: str | Path, gate_id: str, record: dict[str, Any]) -> Path` — writes record to `_bmad/gate/evidence/<gate_id>/<filename>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_evidence_io.py` imports: `evidence_filename`, `persist_evidence_record` from `evidence_io`; `Path` from `pathlib`. Then append:

```python
class EvidenceFilenameTests(unittest.TestCase):
    def test_simple_names(self) -> None:
        record = make_evidence_record(
            collector="test-runner", tool="pytest",
            category="correctness", status="ok",
        )
        self.assertEqual(
            evidence_filename(record),
            "correctness--test-runner--pytest.json",
        )

    def test_sanitizes_slashes(self) -> None:
        record = make_evidence_record(
            collector="my/collector", tool="some/tool",
            category="security", status="ok",
        )
        name = evidence_filename(record)
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".json"))


class PersistEvidenceRecordTests(unittest.TestCase):
    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-001", record)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["collector"], "runner")

    def test_file_lives_under_gate_id_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-002", record)
            self.assertIn("gate-002", str(path))

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-003", record)
            self.assertTrue(path.parent.is_dir())

    def test_rejects_path_traversal_gate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            with self.assertRaisesRegex(GateSchemaError, "invalid path"):
                persist_evidence_record(tmp, "../../etc", record)

    def test_rejects_empty_gate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            with self.assertRaisesRegex(GateSchemaError, "gate_id"):
                persist_evidence_record(tmp, "", record)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::PersistEvidenceRecordTests -v`
Expected: ImportError — `persist_evidence_record` not defined.

- [ ] **Step 3: Write minimal implementation**

Update the imports at top of `evidence_io.py` — replace the existing partial imports with:

```python
from pathlib import Path

from .gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GateSchemaError,
    canonical_json,
    validate_evidence_record,
    validate_schema_version,
)
from .utils import ensure_dir, write_atomic
```

Add after `compute_evidence_bundle_hash`:

```python
def evidence_filename(record: dict[str, Any]) -> str:
    """Deterministic filename for an evidence record."""
    category = record.get("category", "unknown")
    collector = record.get("collector", "unknown")
    tool = record.get("tool", "unknown")
    safe = lambda s: s.replace("/", "_").replace("\\", "_")
    return f"{safe(category)}--{safe(collector)}--{safe(tool)}.json"


def persist_evidence_record(
    project_root: str | Path,
    gate_id: str,
    record: dict[str, Any],
) -> Path:
    """Write a validated evidence record to _bmad/gate/evidence/<gate_id>/."""
    _validate_gate_id(gate_id)
    validate_evidence_record(record)
    evidence_dir = Path(project_root) / "_bmad" / "gate" / "evidence" / gate_id
    ensure_dir(evidence_dir)
    filename = evidence_filename(record)
    target = evidence_dir / filename
    write_atomic(target, canonical_json(record) + "\n")
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add evidence record persistence" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Evidence Bundle Loading (Read)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `validate_schema_version`, `EVIDENCE_SCHEMA_VERSION` (from `gate_schema.py`); `read_text` (from `utils.py`); `persist_evidence_record` (from Task 6)
- Produces: `load_evidence_bundle(project_root: str | Path, gate_id: str) -> list[dict[str, Any]]` — reads all `*.json` files in evidence dir, validates schema version, returns sorted list.

- [ ] **Step 1: Write the failing tests**

Add `load_evidence_bundle` to the import from `evidence_io`. Then append to `tests/test_evidence_io.py`:

```python
class LoadEvidenceBundleTests(unittest.TestCase):
    def test_loads_persisted_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r1 = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            r2 = make_evidence_record(
                collector="scanner", tool="semgrep",
                category="security", status="ok",
            )
            persist_evidence_record(tmp, "gate-010", r1)
            persist_evidence_record(tmp, "gate-010", r2)
            bundle = load_evidence_bundle(tmp, "gate-010")
            self.assertEqual(len(bundle), 2)
            categories = {r["category"] for r in bundle}
            self.assertEqual(categories, {"correctness", "security"})

    def test_empty_dir_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = load_evidence_bundle(tmp, "nonexistent-gate")
            self.assertEqual(bundle, [])

    def test_sorted_by_category_collector_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r_sec = make_evidence_record(
                collector="scanner", tool="semgrep",
                category="security", status="ok",
            )
            r_cor = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            persist_evidence_record(tmp, "gate-011", r_sec)
            persist_evidence_record(tmp, "gate-011", r_cor)
            bundle = load_evidence_bundle(tmp, "gate-011")
            self.assertEqual(bundle[0]["category"], "correctness")
            self.assertEqual(bundle[1]["category"], "security")

    def test_rejects_future_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            record["schema_version"] = 999
            evidence_dir = (
                Path(tmp) / "_bmad" / "gate" / "evidence" / "gate-012"
            )
            evidence_dir.mkdir(parents=True)
            target = evidence_dir / "correctness--runner--pytest.json"
            target.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(GateSchemaError, "schema_version"):
                load_evidence_bundle(tmp, "gate-012")

    def test_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = (
                Path(tmp) / "_bmad" / "gate" / "evidence" / "gate-013"
            )
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "bad.json").write_text(
                "not valid json", encoding="utf-8",
            )
            with self.assertRaisesRegex(GateSchemaError, "invalid JSON"):
                load_evidence_bundle(tmp, "gate-013")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::LoadEvidenceBundleTests -v`
Expected: ImportError — `load_evidence_bundle` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `evidence_io.py` after `persist_evidence_record`:

```python
def load_evidence_bundle(
    project_root: str | Path,
    gate_id: str,
) -> list[dict[str, Any]]:
    """Load all evidence records for a gate, sorted deterministically."""
    _validate_gate_id(gate_id)
    evidence_dir = Path(project_root) / "_bmad" / "gate" / "evidence" / gate_id
    if not evidence_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GateSchemaError(
                f"invalid JSON in evidence file {path.name}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise GateSchemaError(
                f"evidence file {path.name} must contain an object"
            )
        validate_schema_version(data, EVIDENCE_SCHEMA_VERSION, "evidence")
        records.append(data)
    records.sort(
        key=lambda r: (
            r.get("category", ""),
            r.get("collector", ""),
            r.get("tool", ""),
        ),
    )
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add evidence bundle loading with schema version guard" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Gate File Persistence (Write + Read)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `validate_gate_file`, `validate_schema_version`, `GATE_SCHEMA_VERSION`, `canonical_json` (from `gate_schema.py`); `write_atomic`, `read_text` (from `utils.py`)
- Produces: `persist_gate_file(project_root: str | Path, gate_file: dict[str, Any]) -> Path`; `load_gate_file(project_root: str | Path, gate_id: str) -> dict[str, Any]`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_evidence_io.py` imports: `persist_gate_file`, `load_gate_file` from `evidence_io`; `GATE_SCHEMA_VERSION`, `make_gate_file` from `gate_schema`. Then append:

```python
class PersistGateFileTests(unittest.TestCase):
    def _valid_gate(self) -> dict:
        return make_gate_file(
            gate_id="gate-100",
            target={"kind": "story", "id": "E1.S1"},
            commit_sha="abc123def456",
            profile={"id": "default", "version": 1, "hash": "aabbccdd"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )

    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._valid_gate()
            path = persist_gate_file(tmp, gate)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["gate_id"], "gate-100")

    def test_file_in_verdicts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._valid_gate()
            path = persist_gate_file(tmp, gate)
            self.assertIn("verdicts", str(path))
            self.assertEqual(path.name, "gate-100.json")


class LoadGateFileTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = make_gate_file(
                gate_id="gate-200",
                target={"kind": "story", "id": "E1.S2"},
                commit_sha="deadbeef",
                profile={"id": "default", "version": 1, "hash": "11223344"},
                factory_version="0.2.0",
                categories={"security": {"verdict": "FAIL"}},
                overall="FAIL",
            )
            persist_gate_file(tmp, gate)
            loaded = load_gate_file(tmp, "gate-200")
            self.assertEqual(loaded["gate_id"], "gate-200")
            self.assertEqual(loaded["overall"], "FAIL")

    def test_missing_gate_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(GateSchemaError, "not found"):
                load_gate_file(tmp, "nonexistent")

    def test_rejects_future_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verdicts_dir = Path(tmp) / "_bmad" / "gate" / "verdicts"
            verdicts_dir.mkdir(parents=True)
            bad_gate = {
                "gate_id": "gate-300",
                "schema_version": 999,
                "target": {"kind": "story"},
                "commit_sha": "abc",
                "profile": {"id": "x"},
                "factory_version": "0.1",
                "categories": {},
                "overall": "PASS",
                "waivers": [],
            }
            (verdicts_dir / "gate-300.json").write_text(
                json.dumps(bad_gate), encoding="utf-8",
            )
            with self.assertRaisesRegex(GateSchemaError, "schema_version"):
                load_gate_file(tmp, "gate-300")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::PersistGateFileTests -v`
Expected: ImportError — `persist_gate_file` not defined.

- [ ] **Step 3: Write minimal implementation**

Extend the `gate_schema` imports at top of `evidence_io.py` to add `GATE_SCHEMA_VERSION` and `validate_gate_file`:

```python
from .gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GATE_SCHEMA_VERSION,
    GateSchemaError,
    canonical_json,
    validate_evidence_record,
    validate_gate_file,
    validate_schema_version,
)
```

Add after `load_evidence_bundle`:

```python
def persist_gate_file(
    project_root: str | Path,
    gate_file: dict[str, Any],
) -> Path:
    """Write a validated gate file to _bmad/gate/verdicts/<gate_id>.json."""
    validate_gate_file(gate_file)
    gate_id = gate_file["gate_id"]
    _validate_gate_id(gate_id)
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    ensure_dir(verdicts_dir)
    target = verdicts_dir / f"{gate_id}.json"
    write_atomic(target, canonical_json(gate_file) + "\n")
    return target


def load_gate_file(
    project_root: str | Path,
    gate_id: str,
) -> dict[str, Any]:
    """Load a gate file from _bmad/gate/verdicts/<gate_id>.json."""
    _validate_gate_id(gate_id)
    path = Path(project_root) / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    if not path.is_file():
        raise GateSchemaError(f"gate file not found: {gate_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateSchemaError(
            f"invalid JSON in gate file {gate_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise GateSchemaError(f"gate file {gate_id} must contain an object")
    validate_schema_version(data, GATE_SCHEMA_VERSION, "gate")
    validate_gate_file(data)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add gate file persistence with schema version guard" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Gate File Reuse Validation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: None from prior tasks beyond the gate file dict shape (uses only dict field access).
- Produces: `can_reuse_gate_file(gate_file: dict[str, Any], *, commit_sha: str, profile_hash: str, factory_version: str) -> tuple[bool, str]` — §9.2: all three must match for reuse. Returns `(True, "")` on match, `(False, "reason")` on mismatch.

- [ ] **Step 1: Write the failing tests**

Add `can_reuse_gate_file` to the import from `evidence_io`. Then append to `tests/test_evidence_io.py`:

```python
class CanReuseGateFileTests(unittest.TestCase):
    def _gate(self) -> dict:
        return {
            "gate_id": "gate-400",
            "commit_sha": "abc123",
            "profile": {"id": "default", "version": 1, "hash": "aabbccdd"},
            "factory_version": "0.1.0",
        }

    def test_all_match_returns_true(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_commit_sha_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="different",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("commit_sha", reason)

    def test_profile_hash_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="different",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("profile", reason)

    def test_factory_version_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.2.0",
        )
        self.assertFalse(ok)
        self.assertIn("factory_version", reason)

    def test_multiple_mismatches_reports_first(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="wrong",
            profile_hash="wrong",
            factory_version="wrong",
        )
        self.assertFalse(ok)
        self.assertTrue(len(reason) > 0)

    def test_missing_profile_hash_reports_mismatch(self) -> None:
        gate = self._gate()
        gate["profile"] = {"id": "x"}
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("profile", reason)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::CanReuseGateFileTests -v`
Expected: ImportError — `can_reuse_gate_file` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `evidence_io.py` after `load_gate_file`:

```python
def can_reuse_gate_file(
    gate_file: dict[str, Any],
    *,
    commit_sha: str,
    profile_hash: str,
    factory_version: str,
) -> tuple[bool, str]:
    """§9.2: gate file reusable only if all three match."""
    gate_sha = gate_file.get("commit_sha", "")
    if gate_sha != commit_sha:
        return False, (
            f"commit_sha mismatch: gate={gate_sha!r}, current={commit_sha!r}"
        )
    gate_profile_hash = (gate_file.get("profile") or {}).get("hash", "")
    if gate_profile_hash != profile_hash:
        return False, (
            f"profile.hash mismatch: gate={gate_profile_hash!r}, "
            f"current={profile_hash!r}"
        )
    gate_fv = gate_file.get("factory_version", "")
    if gate_fv != factory_version:
        return False, (
            f"factory_version mismatch: gate={gate_fv!r}, "
            f"current={factory_version!r}"
        )
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add gate file reuse validation per §9.2" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Gate-in-Progress Marker Lifecycle

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `write_atomic`, `ensure_dir` (from `utils.py`); `canonical_json` (from `gate_schema.py`); `iso_now` (from `utils.py`)
- Produces: `write_gate_marker(project_root: str | Path, gate_id: str, commit_sha: str) -> Path`; `read_gate_marker(project_root: str | Path) -> dict[str, Any] | None`; `clear_gate_marker(project_root: str | Path) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_evidence_io.py` imports: `write_gate_marker`, `read_gate_marker`, `clear_gate_marker` from `evidence_io`. Then append:

```python
class GateMarkerLifecycleTests(unittest.TestCase):
    def test_write_creates_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gate_marker(tmp, "gate-500", "sha123")
            self.assertTrue(path.is_file())

    def test_read_returns_marker_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-501", "sha456")
            marker = read_gate_marker(tmp)
            self.assertIsNotNone(marker)
            self.assertEqual(marker["gate_id"], "gate-501")
            self.assertEqual(marker["commit_sha"], "sha456")
            self.assertIn("started_at", marker)

    def test_read_returns_none_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = read_gate_marker(tmp)
            self.assertIsNone(marker)

    def test_clear_removes_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-502", "sha789")
            clear_gate_marker(tmp)
            self.assertIsNone(read_gate_marker(tmp))

    def test_clear_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clear_gate_marker(tmp)
            self.assertIsNone(read_gate_marker(tmp))

    def test_marker_file_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gate_marker(tmp, "gate-503", "shaabc")
            self.assertEqual(path.name, "gate-in-progress.json")
            self.assertIn("gate", str(path.parent))

    def test_marker_overwrites_previous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-old", "sha-old")
            write_gate_marker(tmp, "gate-new", "sha-new")
            marker = read_gate_marker(tmp)
            self.assertEqual(marker["gate_id"], "gate-new")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::GateMarkerLifecycleTests -v`
Expected: ImportError — `write_gate_marker` not defined.

- [ ] **Step 3: Write minimal implementation**

Add `iso_now` to the imports from `utils` in `evidence_io.py`:

```python
from .utils import ensure_dir, iso_now, write_atomic
```

Add after `can_reuse_gate_file`:

```python
_GATE_MARKER_NAME = "gate-in-progress.json"


def _gate_marker_path(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _GATE_MARKER_NAME


def write_gate_marker(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
) -> Path:
    """§9.2: atomic marker before collector loop starts."""
    marker = {
        "gate_id": gate_id,
        "commit_sha": commit_sha,
        "started_at": iso_now(),
    }
    path = _gate_marker_path(project_root)
    ensure_dir(path.parent)
    write_atomic(path, canonical_json(marker) + "\n")
    return path


def read_gate_marker(
    project_root: str | Path,
) -> dict[str, Any] | None:
    """Read gate-in-progress marker; returns None if absent."""
    path = _gate_marker_path(project_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def clear_gate_marker(project_root: str | Path) -> None:
    """§9.2: remove marker after verdict is written (or on crash recovery)."""
    path = _gate_marker_path(project_root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add gate-in-progress marker for crash-safety" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Round-Trip Determinism + Integration Tests

**Files:**
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `persist_evidence_record`, `load_evidence_bundle`, `persist_gate_file`, `load_gate_file`, `compute_evidence_bundle_hash` (all from prior tasks); `make_evidence_record`, `make_gate_file`, `make_llm_evidence_record` (from `gate_schema.py`)
- Produces: No new code — validates §18 determinism guarantees across the full persist→load→hash pipeline.

- [ ] **Step 1: Write the round-trip and integration tests**

Add `make_llm_evidence_record` to the import from `gate_schema`. Then append to `tests/test_evidence_io.py`:

```python
class RoundTripDeterminismTests(unittest.TestCase):
    def test_evidence_round_trip_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_evidence_record(
                collector="runner", tool="pytest", tool_version="8.2.0",
                category="correctness", status="ok",
                metrics={"line_coverage": 95.5},
                findings=[], exit_code=0, duration_ms=1234,
            )
            persist_evidence_record(tmp, "rt-gate", original)
            bundle = load_evidence_bundle(tmp, "rt-gate")
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0], original)

    def test_gate_file_round_trip_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_gate_file(
                gate_id="rt-gate-2",
                target={"kind": "story", "id": "E1.S1"},
                commit_sha="abc123",
                profile={"id": "default", "version": 1, "hash": "aabb"},
                factory_version="0.1.0",
                categories={
                    "correctness": {"verdict": "PASS", "required": {}, "actual": {}},
                    "security": {"verdict": "CONCERNS", "required": {}, "actual": {}},
                },
                overall="CONCERNS",
                evidence_bundle_hash="1234567890abcdef",
            )
            persist_gate_file(tmp, original)
            loaded = load_gate_file(tmp, "rt-gate-2")
            self.assertEqual(loaded, original)

    def test_bundle_hash_stable_across_persist_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                make_evidence_record(
                    collector="runner", tool="pytest",
                    category="correctness", status="ok",
                ),
                make_evidence_record(
                    collector="scanner", tool="semgrep",
                    category="security", status="violation",
                    findings=["CVE-2026-0001"],
                ),
            ]
            hash_before = compute_evidence_bundle_hash(records)
            for r in records:
                persist_evidence_record(tmp, "hash-gate", r)
            loaded = load_evidence_bundle(tmp, "hash-gate")
            hash_after = compute_evidence_bundle_hash(loaded)
            self.assertEqual(hash_before, hash_after)

    def test_llm_evidence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_llm_evidence_record(
                collector="llm-reviewer", tool="claude",
                category="test_quality", status="ok",
                confidence=7, rationale="Good coverage patterns",
            )
            persist_evidence_record(tmp, "llm-gate", original)
            bundle = load_evidence_bundle(tmp, "llm-gate")
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0]["confidence"], 7)
            self.assertEqual(bundle[0]["rationale"], "Good coverage patterns")
            self.assertFalse(bundle[0]["deterministic"])


class EvidenceToGatePipelineTests(unittest.TestCase):
    def test_full_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                make_evidence_record(
                    collector="runner", tool="pytest",
                    category="correctness", status="ok",
                ),
                make_evidence_record(
                    collector="scanner", tool="semgrep",
                    category="security", status="ok",
                ),
                make_llm_evidence_record(
                    collector="llm-reviewer", tool="claude",
                    category="test_quality", status="ok",
                    confidence=8, rationale="Solid test design",
                ),
            ]
            for r in records:
                persist_evidence_record(tmp, "pipe-gate", r)
            bundle = load_evidence_bundle(tmp, "pipe-gate")
            bundle_hash = compute_evidence_bundle_hash(bundle)
            gate = make_gate_file(
                gate_id="pipe-gate",
                target={"kind": "story", "id": "E2.S3"},
                commit_sha="deadbeef",
                profile={"id": "msme-erp", "version": 1, "hash": "eeff0011"},
                factory_version="0.3.0",
                categories={
                    "correctness": {"verdict": "PASS"},
                    "security": {"verdict": "PASS"},
                    "test_quality": {"verdict": "PASS"},
                },
                overall="PASS",
                evidence_bundle_hash=bundle_hash,
            )
            persist_gate_file(tmp, gate)
            loaded_gate = load_gate_file(tmp, "pipe-gate")
            self.assertEqual(loaded_gate["evidence_bundle_hash"], bundle_hash)
            ok, _ = can_reuse_gate_file(
                loaded_gate,
                commit_sha="deadbeef",
                profile_hash="eeff0011",
                factory_version="0.3.0",
            )
            self.assertTrue(ok)
```

- [ ] **Step 2: Run all tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py tests/test_gate_schema.py tests/test_gate_rules.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_evidence_io.py
git commit -m "test(gate): add round-trip determinism and pipeline integration tests" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Final Verification + LOC Check

**Files:**
- None created or modified — verification only.

**Interfaces:**
- Consumes: All files from Tasks 1–11.
- Produces: Confidence that all constraints are met.

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_schema.py tests/test_gate_rules.py tests/test_evidence_io.py -v`
Expected: All tests PASS with zero failures.

- [ ] **Step 2: Verify LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/gate_schema.py skills/bmad-story-automator/src/story_automator/core/gate_rules.py skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
Expected: `gate_schema.py` ≤ 320 LOC, `gate_rules.py` ≤ 200 LOC, `evidence_io.py` ≤ 350 LOC.

- [ ] **Step 3: Verify no trailing whitespace**

Run: `grep -rn ' $' skills/bmad-story-automator/src/story_automator/core/evidence_io.py skills/bmad-story-automator/src/story_automator/core/gate_schema.py skills/bmad-story-automator/src/story_automator/core/gate_rules.py; echo "exit: $?"`
Expected: No matches, exit 1.

- [ ] **Step 4: Verify no new deps**

Run: `grep -n '^import\|^from' skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
Expected: Only stdlib imports (`json`, `hashlib`, `pathlib`, `typing`) + local imports (`.gate_schema`, `.utils`).

- [ ] **Step 5: Run existing tests to confirm no regressions**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: All tests PASS. No test from other modules broken.
