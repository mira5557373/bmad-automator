# M04 Milestone 2: Audit-Trail Append + Hash Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `AuditLog` dataclass and its `append(event)` method to `core/audit.py`, producing an append-only, hash-chained JSONL log under a `filelock`-guarded 5-second-timeout critical section. Verification, policy gating, and call-site integration land in later M04 milestones.

**Architecture:** Extend the existing `core/audit.py` module with one new dataclass (`AuditLog`) and one new public method (`append`). Records are JSON objects on a single line each (`{"seq","ts","event","payload","tag"}`). The `tag` is `hex(HMAC-SHA256(key, prev_tag_bytes + canonical_record_bytes))` where `prev_tag_bytes = bytes.fromhex(prev_record.tag)` or 32 zero bytes for the first record; `canonical_record_bytes = compact_json({"seq","ts","event","payload"}).encode("utf-8")`. The append path acquires a `filelock.FileLock` at `path.with_suffix(path.suffix + ".lock")` with a 5-second timeout (raises `AuditLockTimeout` already declared in M01), reads only the last line of the existing file to obtain `prev_seq` and `prev_tag`, then writes the new record atomically by `open("ab")` + `write(line)` + `fsync`. The `Event` contract is duck-typed: any object with `event_name: str` and `to_dict() -> Mapping[str, Any]` is acceptable; a `Protocol` documents the surface without adding a runtime dependency on the (not-yet-ported) `telemetry_events` module.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `pathlib`, `hmac`, `hashlib`, `json`, `os`, `typing`) plus `filelock` for the per-log mutex. Tests use `unittest`. Run with `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py"`. Lint with `ruff check` and `ruff format --check`.

---

## Spec Coverage Map

| Spec ID | Requirement | Tasks |
|---|---|---|
| REQ-02 | `AuditLog` `@dataclass(kw_only=True)` with `path`, `key`, internal `_lock_path` | Tasks 1, 2 |
| REQ-05 | `AuditLog.append(event)` serialises with `compact_json`, assigns sequential `seq` (starting at 1), stamps `ts` via `iso_now()`, writes one newline-terminated JSON object | Tasks 4, 5, 6, 7 |
| REQ-06 | Record fields are exactly `seq`, `ts`, `event`, `payload`, `tag` where `event = event_name` and `payload = to_dict()` | Tasks 4, 5 |
| REQ-07 | `tag = hex(HMAC-SHA256(key, prev_tag_bytes + canonical_record_bytes))`; `prev_tag_bytes = bytes.fromhex(prev.tag)` or `b"\x00"*32` for seq=1; canonical record excludes `tag` | Tasks 3, 4, 5 |
| REQ-07a | All FS mutation inside `filelock.FileLock(self._lock_path)` with 5-second timeout; raises `AuditLockTimeout` on timeout | Tasks 6, 8 |
| NFR-500-line-cap | Module ≤ 500 lines | Task 9 (test exists from M01; re-asserted) |
| NFR-append-latency | 100-record batch completes in < 500 ms wall time | Task 10 |
| QA-wc-l-assertion | `wc -l`-style assertion on module file | Task 9 (already in M01 test; verified to still pass) |

Out of scope for this milestone (later M04 slices): `AuditLog.verify()`, `audit_for_policy()`, the `BMAD_AUDIT_KEY` policy gate, the three call-site integrations (`commands/orchestrator.py`, `commands/state.py`, `commands/orchestrator_epic_agents.py`), tamper / truncation / concurrent-append QA gates (those require `verify()` to assert outcomes). The two-thread concurrent test from the spec's QA gates is deferred to M3 since it depends on `verify()`; we cover the lock-acquisition contract here directly.

---

## File Structure

- **Modify:** `skills/bmad-story-automator/src/story_automator/core/audit.py` — add `AuditLog` dataclass, the `Event` Protocol, the canonicalisation helper, and the `append` method. The existing module header, `__all__`, exception classes, and HKDF surface are untouched except for adding `AuditLog` to `__all__`.
- **Create:** `tests/test_audit_append.py` — new `unittest.TestCase` suite that exercises the dataclass shape, hash-chain math against hand-computed vectors, file format invariants, the filelock contract, and the latency NFR. The M01 file `tests/test_audit_foundations.py` is **not** modified.

No other source files are touched. No new third-party dependency: `filelock` is already in the allow-list.

---

## Task 1: Add `AuditLog` dataclass scaffold (path/key/_lock_path)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_append.py` with:

```python
from __future__ import annotations

import unittest
from dataclasses import fields, is_dataclass
from pathlib import Path


class AuditLogDataclassShapeTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        from story_automator.core.audit import AuditLog

        self.assertTrue(is_dataclass(AuditLog))

    def test_required_fields_present(self) -> None:
        from story_automator.core.audit import AuditLog

        names = {f.name for f in fields(AuditLog)}
        self.assertIn("path", names)
        self.assertIn("key", names)
        self.assertIn("_lock_path", names)

    def test_path_field_is_kw_only(self) -> None:
        from story_automator.core.audit import AuditLog

        # Positional construction must fail because the dataclass is kw_only.
        with self.assertRaises(TypeError):
            AuditLog(Path("/tmp/x.jsonl"), b"\x00" * 32)  # type: ignore[misc]

    def test_lock_path_derived_from_path(self) -> None:
        from story_automator.core.audit import AuditLog

        log = AuditLog(path=Path("/tmp/audit.jsonl"), key=b"\x00" * 32)
        self.assertEqual(log._lock_path, Path("/tmp/audit.jsonl.lock"))

    def test_lock_path_default_overridable(self) -> None:
        from story_automator.core.audit import AuditLog

        custom = Path("/tmp/override.lock")
        log = AuditLog(
            path=Path("/tmp/audit.jsonl"), key=b"\x00" * 32, _lock_path=custom
        )
        self.assertEqual(log._lock_path, custom)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append -v`
Expected: FAIL with `ImportError: cannot import name 'AuditLog' from 'story_automator.core.audit'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, add (below the existing `load_key_from_env` definition):

```python
import dataclasses
import pathlib


@dataclasses.dataclass(kw_only=True)
class AuditLog:
    """Append-only, hash-chained JSONL audit log.

    Fields:
      - ``path``: target JSONL file (one record per line).
      - ``key``: 32-byte HMAC-SHA256 chain key (typically from ``derive_key``).
      - ``_lock_path``: per-log advisory lock file. Defaults to
        ``path.with_suffix(path.suffix + ".lock")``; override only for tests.

    The dataclass is ``kw_only`` to keep call sites readable and to prevent
    accidental positional swaps of ``path`` and ``key`` (one a path, the other
    raw secret bytes).
    """

    path: pathlib.Path
    key: bytes
    _lock_path: pathlib.Path = dataclasses.field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock_path is None:
            self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
```

Also extend `__all__` near the top of the module:

```python
__all__ = [
    "AuditKeyMissing",
    "AuditLockTimeout",
    "AuditLog",
    "derive_key",
    "load_key_from_env",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): add AuditLog dataclass scaffold"
```

---

## Task 2: Pin `AuditLog` exported in `__all__`

**Files:**
- Modify: `tests/test_audit_foundations.py` (extend allow-list assertion)

> Rationale: Task 1 already added `AuditLog` to `__all__`, but the M01 test pinned the exact set. We extend the existing assertion so the M01 test continues to enforce surface area precisely.

- [ ] **Step 1: Inspect the existing M01 test for the pinned set**

Open `tests/test_audit_foundations.py` and locate `class AuditPublicApiTests` (around line 57). Its assertion compares `sorted(audit.__all__)` to a pinned list of four names. We extend that list.

- [ ] **Step 2: Write the failing test by tightening the existing pin**

Edit `tests/test_audit_foundations.py`, replacing the body of `AuditPublicApiTests.test_all_lists_milestone_surface` with:

```python
    def test_all_lists_milestone_surface(self) -> None:
        import story_automator.core.audit as audit

        self.assertEqual(
            sorted(audit.__all__),
            sorted(
                [
                    "AuditKeyMissing",
                    "AuditLockTimeout",
                    "AuditLog",
                    "derive_key",
                    "load_key_from_env",
                ]
            ),
        )
```

- [ ] **Step 3: Run the test to verify the new assertion holds**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditPublicApiTests -v`
Expected: PASS (the Task 1 implementation already includes `AuditLog`).

- [ ] **Step 4: Run the full audit test suite to verify no regression**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: PASS for every test in `test_audit_foundations.py` and `test_audit_append.py`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): pin AuditLog in public surface"
```

---

## Task 3: Document the `Event` protocol contract

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

> Rationale: M04 spec REQ-05/REQ-06 say `append(event)` uses `event.event_name` and `event.to_dict()`. The `telemetry_events` module has not been ported yet (deferred to a later milestone outside M04). We document the duck-typed contract via a `typing.Protocol` so future call sites and tests can target the same interface without importing a not-yet-existing module.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class EventProtocolTests(unittest.TestCase):
    def test_protocol_exists_and_is_typing_protocol(self) -> None:
        from story_automator.core.audit import Event
        import typing

        # ``Event`` must be a runtime-checkable Protocol so we can structurally
        # match telemetry events when they arrive in a later milestone.
        self.assertTrue(hasattr(Event, "_is_runtime_protocol")
                        or hasattr(Event, "_is_protocol"),
                        "Event must be a typing.Protocol")
        self.assertTrue(issubclass(type(Event), type(typing.Protocol)) or
                        getattr(Event, "_is_protocol", False))

    def test_duck_typed_event_satisfies_contract(self) -> None:
        # We do NOT depend on telemetry_events. The contract is structural:
        # any object with ``event_name: str`` and ``to_dict()`` is an Event.
        from story_automator.core.audit import Event

        class FakeEvent:
            event_name = "Fake"

            def to_dict(self) -> dict:
                return {"k": "v"}

        ev: Event = FakeEvent()  # type: ignore[assignment]
        self.assertEqual(ev.event_name, "Fake")
        self.assertEqual(ev.to_dict(), {"k": "v"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.EventProtocolTests -v`
Expected: FAIL with `ImportError: cannot import name 'Event'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, add near the top (below the existing `from typing import Mapping` line, extending the import to include `Any`, `Protocol`, and `runtime_checkable`):

```python
from typing import Any, Mapping, Protocol, runtime_checkable
```

Then, just above the `AuditLog` dataclass declaration, add:

```python
@runtime_checkable
class Event(Protocol):
    """Structural interface that ``AuditLog.append`` requires.

    The audit module never imports the concrete telemetry-events module; any
    object exposing ``event_name`` (a string class identifier) and
    ``to_dict()`` (a JSON-serialisable mapping) is acceptable. Documenting
    the contract here keeps the call-site integrations forward-compatible
    with the telemetry refactor that ships in a later milestone.
    """

    event_name: str

    def to_dict(self) -> Mapping[str, Any]: ...
```

Note: `Event` is intentionally **not** added to `__all__` — it is a typing aid, not a runtime export.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.EventProtocolTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): declare Event protocol for append callers"
```

---

## Task 4: Implement `_canonical_record_bytes` helper

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

> Rationale: REQ-07 fixes the canonical byte representation that feeds the HMAC. Extract this into a tiny pure helper so both `append` and the future `verify` can call it identically.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class CanonicalRecordBytesTests(unittest.TestCase):
    def test_excludes_tag_field(self) -> None:
        from story_automator.core.audit import _canonical_record_bytes

        b = _canonical_record_bytes(
            seq=1, ts="2026-06-14T00:00:00Z", event="X", payload={"a": 1}
        )
        self.assertNotIn(b"tag", b)

    def test_matches_compact_json_byte_for_byte(self) -> None:
        from story_automator.core.audit import _canonical_record_bytes
        from story_automator.core.common import compact_json

        expected = compact_json(
            {"seq": 7, "ts": "2026-06-14T01:02:03Z",
             "event": "EscalationRaised", "payload": {"reason": "block"}}
        ).encode("utf-8")
        self.assertEqual(
            _canonical_record_bytes(
                seq=7, ts="2026-06-14T01:02:03Z",
                event="EscalationRaised", payload={"reason": "block"},
            ),
            expected,
        )

    def test_field_order_is_fixed(self) -> None:
        # Field order must be seq, ts, event, payload regardless of payload
        # iteration order. Two payloads with the same keys-in-different-order
        # must produce identical canonical bytes only when the payload mapping
        # itself preserves order (Python 3.7+ dicts do).
        from story_automator.core.audit import _canonical_record_bytes

        b = _canonical_record_bytes(
            seq=1, ts="t", event="E", payload={"a": 1, "b": 2}
        )
        # Ensure "seq" appears before "ts" appears before "event" appears
        # before "payload" in the canonical byte stream.
        s = b.decode("utf-8")
        i_seq, i_ts, i_event, i_payload = (
            s.index("seq"), s.index("ts"),
            s.index("event"), s.index("payload"),
        )
        self.assertLess(i_seq, i_ts)
        self.assertLess(i_ts, i_event)
        self.assertLess(i_event, i_payload)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.CanonicalRecordBytesTests -v`
Expected: FAIL with `ImportError: cannot import name '_canonical_record_bytes'`.

- [ ] **Step 3: Write minimal implementation**

First, add a **relative** import for the helpers we need from `common`. In `core/audit.py`, near the existing imports at the top of the module, add:

```python
from .common import compact_json, ensure_dir, iso_now
```

This is a relative `ImportFrom` (`node.level == 1`). The M01 import-allowlist test in `test_audit_foundations.AuditImportAllowlistTests._collect_top_level_modules` explicitly skips relative imports (`if node.level and node.level > 0: continue`), so this addition is allow-list-clean. We use relative — not `from story_automator.core.common import ...` — because a top-level absolute import would surface `story_automator` to the allow-list walker and fail the test.

Then, just above the `AuditLog` dataclass (and below the `Event` Protocol), add:

```python
def _canonical_record_bytes(
    *, seq: int, ts: str, event: str, payload: Mapping[str, Any]
) -> bytes:
    """Return the canonical byte representation hashed into ``tag``.

    The canonical form is ``compact_json({"seq","ts","event","payload"})``
    encoded as UTF-8, with the field order fixed to ``seq, ts, event,
    payload``. The ``tag`` field is intentionally excluded — including it
    would create a cyclic dependency between the record's contents and its
    own integrity tag.
    """
    return compact_json(
        {"seq": seq, "ts": ts, "event": event, "payload": payload}
    ).encode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.CanonicalRecordBytesTests -v`
Expected: PASS (3 tests).

Then re-run the import-allowlist test:

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditImportAllowlistTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): canonical record bytes helper"
```

---

## Task 5: Implement `_compute_tag` helper

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
import hashlib
import hmac


class ComputeTagTests(unittest.TestCase):
    KEY = b"\xaa" * 32

    def test_seq1_uses_32_zero_bytes_as_prev_tag(self) -> None:
        from story_automator.core.audit import (
            _canonical_record_bytes, _compute_tag,
        )

        canonical = _canonical_record_bytes(
            seq=1, ts="2026-06-14T00:00:00Z", event="E", payload={}
        )
        expected = hmac.new(
            self.KEY, b"\x00" * 32 + canonical, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            _compute_tag(key=self.KEY, prev_tag_hex=None, canonical=canonical),
            expected,
        )

    def test_seq_gt_1_decodes_prev_tag_hex(self) -> None:
        from story_automator.core.audit import (
            _canonical_record_bytes, _compute_tag,
        )

        prev_hex = "ab" * 32  # 32 bytes
        canonical = _canonical_record_bytes(
            seq=2, ts="2026-06-14T00:00:01Z", event="E", payload={"x": 1}
        )
        expected = hmac.new(
            self.KEY, bytes.fromhex(prev_hex) + canonical, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            _compute_tag(
                key=self.KEY, prev_tag_hex=prev_hex, canonical=canonical
            ),
            expected,
        )

    def test_returns_lowercase_hex(self) -> None:
        from story_automator.core.audit import (
            _canonical_record_bytes, _compute_tag,
        )

        canonical = _canonical_record_bytes(
            seq=1, ts="t", event="E", payload={}
        )
        tag = _compute_tag(
            key=self.KEY, prev_tag_hex=None, canonical=canonical
        )
        self.assertEqual(tag, tag.lower())
        self.assertEqual(len(tag), 64)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.ComputeTagTests -v`
Expected: FAIL with `ImportError: cannot import name '_compute_tag'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, just below `_canonical_record_bytes`, add:

```python
_ZERO_TAG = b"\x00" * 32


def _compute_tag(*, key: bytes, prev_tag_hex: str | None, canonical: bytes) -> str:
    """Return the lowercase hex HMAC-SHA256 chain tag for one record.

    ``prev_tag_hex`` is the hex tag of the previous record, or ``None`` when
    appending seq=1 (in which case 32 zero bytes are prepended). The HMAC
    input is ``prev_tag_bytes + canonical_record_bytes`` per REQ-07.

    The key bytes are passed straight to ``hmac.new`` and never logged.
    """
    prev_bytes = _ZERO_TAG if prev_tag_hex is None else bytes.fromhex(prev_tag_hex)
    return hmac.new(key, prev_bytes + canonical, hashlib.sha256).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.ComputeTagTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): compute_tag helper for hash chain"
```

---

## Task 6: Implement `_read_last_record` helper (seq + tag of last line)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

> Rationale: Before appending we need `prev_seq` and `prev_tag`. We must not load the whole file — the NFR for `verify()` requires streaming, and `append` should follow the same posture. This helper scans line-by-line and returns only the last parsed record.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
import json
import tempfile


class ReadLastRecordTests(unittest.TestCase):
    def test_returns_none_on_missing_file(self) -> None:
        from story_automator.core.audit import _read_last_record

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(_read_last_record(Path(d) / "missing.jsonl"))

    def test_returns_none_on_empty_file(self) -> None:
        from story_automator.core.audit import _read_last_record

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            self.assertIsNone(_read_last_record(p))

    def test_returns_last_line_record(self) -> None:
        from story_automator.core.audit import _read_last_record

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text(
                json.dumps({"seq": 1, "tag": "a" * 64}) + "\n"
                + json.dumps({"seq": 2, "tag": "b" * 64}) + "\n",
                encoding="utf-8",
            )
            rec = _read_last_record(p)
            self.assertEqual(rec, {"seq": 2, "tag": "b" * 64})

    def test_ignores_trailing_blank_lines(self) -> None:
        from story_automator.core.audit import _read_last_record

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text(
                json.dumps({"seq": 1, "tag": "c" * 64}) + "\n\n",
                encoding="utf-8",
            )
            rec = _read_last_record(p)
            self.assertEqual(rec, {"seq": 1, "tag": "c" * 64})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.ReadLastRecordTests -v`
Expected: FAIL with `ImportError: cannot import name '_read_last_record'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, just below `_compute_tag`, add:

```python
import json as _json


def _read_last_record(path: pathlib.Path) -> dict[str, Any] | None:
    """Return the last parsed JSON record in ``path``, or ``None``.

    Streams the file line by line, keeping only the most recent successfully
    parsed object in memory. Blank trailing lines are ignored. Returns
    ``None`` when the file does not exist, is empty, or contains only blank
    lines. Malformed JSON on the last non-blank line raises
    ``json.JSONDecodeError`` — the append path treats that as a fatal
    corruption signal and propagates it.
    """
    if not path.exists():
        return None
    last: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            last = _json.loads(line)
    return last
```

The `json` module is imported with the `_json` alias to keep it private and to avoid colliding with any future top-level `json` usage that tests might inspect via the import-allowlist walk. (`json` is stdlib, so this is purely a style choice.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.ReadLastRecordTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): read_last_record helper for prev tag lookup"
```

---

## Task 7: Implement `AuditLog.append` — first record (seq=1)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class AppendFirstRecordTests(unittest.TestCase):
    KEY = b"\x11" * 32

    def _fake_event(self, name: str = "EscalationRaised",
                    payload: dict | None = None):
        class FakeEvent:
            event_name = name

            def __init__(self, p: dict) -> None:
                self._p = p

            def to_dict(self) -> dict:
                return self._p
        return FakeEvent(payload or {"reason": "blocked"})

    def test_seq_starts_at_1_and_writes_one_line(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            text = p.read_text(encoding="utf-8")
            self.assertEqual(text.count("\n"), 1)
            rec = json.loads(text.strip())
            self.assertEqual(rec["seq"], 1)

    def test_record_has_exactly_five_fields(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            self.assertEqual(
                set(rec.keys()), {"seq", "ts", "event", "payload", "tag"}
            )

    def test_event_name_and_payload_copied_from_event(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event(
                name="StoryStateChanged", payload={"from": "draft", "to": "qa"}
            ))
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["event"], "StoryStateChanged")
            self.assertEqual(rec["payload"], {"from": "draft", "to": "qa"})

    def test_ts_matches_iso_now_format(self) -> None:
        import re
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_tag_matches_compute_tag_with_zero_prev(self) -> None:
        from story_automator.core.audit import (
            AuditLog, _canonical_record_bytes, _compute_tag,
        )

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event(payload={"k": 1}))
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            expected_tag = _compute_tag(
                key=self.KEY,
                prev_tag_hex=None,
                canonical=_canonical_record_bytes(
                    seq=rec["seq"], ts=rec["ts"],
                    event=rec["event"], payload=rec["payload"],
                ),
            )
            self.assertEqual(rec["tag"], expected_tag)

    def test_record_line_is_compact_json(self) -> None:
        # No spaces between separators (compact_json invariant).
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            text = p.read_text(encoding="utf-8").rstrip("\n")
            self.assertNotIn(", ", text)
            self.assertNotIn(": ", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendFirstRecordTests -v`
Expected: FAIL with `AttributeError: 'AuditLog' object has no attribute 'append'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, add a method to the `AuditLog` dataclass body (inside the class, after `__post_init__`):

```python
    def append(self, event: "Event") -> None:
        """Append one record to the chain, computing the tag and bumping seq.

        ``event`` is duck-typed: any object with ``event_name`` and
        ``to_dict()`` works. The serialised line is:

            {"seq": N, "ts": ISO, "event": NAME, "payload": {...}, "tag": HEX}

        followed by a single ``\\n``. All filesystem mutation is performed
        under the per-log ``filelock.FileLock`` acquired with a 5-second
        timeout — on timeout this method raises ``AuditLockTimeout``.
        """
        ensure_dir(self.path.parent)

        prev = _read_last_record(self.path)
        if prev is None:
            seq = 1
            prev_tag_hex: str | None = None
        else:
            seq = int(prev["seq"]) + 1
            prev_tag_hex = prev["tag"]

        ts = iso_now()
        event_name = event.event_name
        payload = event.to_dict()
        canonical = _canonical_record_bytes(
            seq=seq, ts=ts, event=event_name, payload=payload
        )
        tag = _compute_tag(
            key=self.key, prev_tag_hex=prev_tag_hex, canonical=canonical
        )

        record = {
            "seq": seq, "ts": ts, "event": event_name,
            "payload": payload, "tag": tag,
        }
        line = compact_json(record) + "\n"

        with self.path.open("ab") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
```

Note: filelock guarding is added in Task 9 — this task lands a working single-writer `append`. The `ensure_dir` call here covers the case where the audit log path includes a parent directory that doesn't exist yet (a real-world call site, even though M2 tests use `tempfile` which always provides an existing parent).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendFirstRecordTests -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): append first record to the chain"
```

---

## Task 8: Extend `AuditLog.append` — chain subsequent records (seq>1)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py` (no code change — the Task 7 implementation already handles seq>1; this task adds the test coverage)
- Test: `tests/test_audit_append.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class AppendChainTests(unittest.TestCase):
    KEY = b"\x22" * 32

    def _fake_event(self, name: str, payload: dict):
        class FakeEvent:
            event_name = name

            def __init__(self, p: dict) -> None:
                self._p = p

            def to_dict(self) -> dict:
                return self._p
        return FakeEvent(payload)

    def test_three_records_have_contiguous_seqs(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(3):
                log.append(self._fake_event("E", {"i": i}))
            recs = [
                json.loads(line)
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([r["seq"] for r in recs], [1, 2, 3])

    def test_each_tag_chains_from_previous(self) -> None:
        from story_automator.core.audit import (
            AuditLog, _canonical_record_bytes, _compute_tag,
        )

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(3):
                log.append(self._fake_event("E", {"i": i}))
            recs = [
                json.loads(line)
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            prev_tag: str | None = None
            for rec in recs:
                expected = _compute_tag(
                    key=self.KEY,
                    prev_tag_hex=prev_tag,
                    canonical=_canonical_record_bytes(
                        seq=rec["seq"], ts=rec["ts"],
                        event=rec["event"], payload=rec["payload"],
                    ),
                )
                self.assertEqual(rec["tag"], expected)
                prev_tag = rec["tag"]

    def test_file_is_pure_jsonl_no_extra_whitespace(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(5):
                log.append(self._fake_event("E", {"i": i}))
            text = p.read_text(encoding="utf-8")
            # Exactly 5 newlines, file ends with a newline, no double newlines.
            self.assertEqual(text.count("\n"), 5)
            self.assertTrue(text.endswith("\n"))
            self.assertNotIn("\n\n", text)
```

- [ ] **Step 2: Run test to verify it passes (Task 7 impl already covers this)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendChainTests -v`
Expected: PASS (3 tests).

> If any test fails, the bug is in the Task 7 `append` implementation — fix it before proceeding. Likely culprit: `prev_tag_hex` not being threaded into the new HMAC input correctly.

- [ ] **Step 3: Commit the new tests**

```bash
git add tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): chain three appended records and verify tag continuity"
```

---

## Task 9: Wrap `AuditLog.append` in `filelock.FileLock` with 5-second timeout

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_append.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class AppendFileLockContractTests(unittest.TestCase):
    KEY = b"\x33" * 32

    def _fake_event(self):
        class FakeEvent:
            event_name = "E"

            def to_dict(self) -> dict:
                return {}
        return FakeEvent()

    def test_timeout_raises_audit_lock_timeout(self) -> None:
        import filelock
        from story_automator.core.audit import AuditLog, AuditLockTimeout

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            held = filelock.FileLock(str(log._lock_path))
            held.acquire(timeout=1)
            try:
                with self.assertRaises(AuditLockTimeout):
                    log.append(self._fake_event())
            finally:
                held.release()

    def test_lock_released_after_successful_append(self) -> None:
        # After a successful append, the same FileLock instance can be
        # acquired by an outside caller immediately (non-blocking).
        import filelock
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            outside = filelock.FileLock(str(log._lock_path))
            outside.acquire(timeout=0)
            try:
                pass
            finally:
                outside.release()

    def test_lock_released_even_when_append_raises(self) -> None:
        # If append raises mid-write (simulated by passing an event whose
        # to_dict raises), the lock must be released.
        import filelock
        from story_automator.core.audit import AuditLog

        class Boom:
            event_name = "Boom"

            def to_dict(self) -> dict:
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            with self.assertRaises(RuntimeError):
                log.append(Boom())
            outside = filelock.FileLock(str(log._lock_path))
            outside.acquire(timeout=0)
            try:
                pass
            finally:
                outside.release()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendFileLockContractTests -v`
Expected: FAIL (the test that holds the lock will hang for the default unbounded acquire, or fail when `append` succeeds despite the lock being held).

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`:

3a. Add a top-level `import filelock` near the other imports (this is the first time `filelock` is imported in the module — it is on the allow-list).

3b. Replace the body of `AuditLog.append` with the lock-guarded version:

```python
    def append(self, event: "Event") -> None:
        """Append one record to the chain, computing the tag and bumping seq.

        ``event`` is duck-typed: any object with ``event_name`` and
        ``to_dict()`` works. The serialised line is:

            {"seq": N, "ts": ISO, "event": NAME, "payload": {...}, "tag": HEX}

        followed by a single ``\\n``. All filesystem mutation is performed
        under the per-log ``filelock.FileLock`` acquired with a 5-second
        timeout — on timeout this method raises ``AuditLockTimeout``.
        """
        ensure_dir(self.path.parent)
        ensure_dir(self._lock_path.parent)

        lock = filelock.FileLock(str(self._lock_path))
        try:
            lock.acquire(timeout=5)
        except filelock.Timeout as exc:
            raise AuditLockTimeout(
                f"could not acquire audit lock within 5s: {self._lock_path}"
            ) from exc

        try:
            prev = _read_last_record(self.path)
            if prev is None:
                seq = 1
                prev_tag_hex: str | None = None
            else:
                seq = int(prev["seq"]) + 1
                prev_tag_hex = prev["tag"]

            ts = iso_now()
            event_name = event.event_name
            payload = event.to_dict()
            canonical = _canonical_record_bytes(
                seq=seq, ts=ts, event=event_name, payload=payload
            )
            tag = _compute_tag(
                key=self.key, prev_tag_hex=prev_tag_hex, canonical=canonical
            )

            record = {
                "seq": seq, "ts": ts, "event": event_name,
                "payload": payload, "tag": tag,
            }
            line = compact_json(record) + "\n"

            with self.path.open("ab") as handle:
                handle.write(line.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            lock.release()
```

> Note: `AuditLockTimeout`'s message references only `self._lock_path` (a derived filesystem path), never `self.key`. The secrets-never-leak test from M01 verifies the module source for forbidden calls (`print(`, `logging.`, `warnings.`) — we use neither, so that test still passes.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendFileLockContractTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full audit test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: PASS for every test, no regressions.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): guard append with filelock and 5s timeout"
```

---

## Task 10: Re-affirm 500-line module budget (NFR-500-line-cap, QA-wc-l-assertion)

**Files:**
- Modify: `tests/test_audit_append.py` (add a redundant but self-contained assertion)

> Rationale: The M01 test `AuditModuleSizeBudgetTests` already enforces `≤ 500` lines. We add a sibling assertion in the M2 test file so the M2 milestone is self-checking: a developer can run only `tests.test_audit_append` and still detect a size regression.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_append.py`:

```python
class AuditModuleSizeBudgetM2Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
        from pathlib import Path

        audit_path = (
            Path(__file__).resolve().parents[1]
            / "skills" / "bmad-story-automator" / "src"
            / "story_automator" / "core" / "audit.py"
        )
        line_count = sum(
            1 for _ in audit_path.read_text(encoding="utf-8").splitlines()
        )
        self.assertLessEqual(
            line_count, 500,
            f"audit.py is {line_count} lines (budget: 500 per NFR-500-line-cap)",
        )
```

- [ ] **Step 2: Run the test to confirm the current module fits**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AuditModuleSizeBudgetM2Tests -v`
Expected: PASS. (The implemented module is well under 500 lines; this guards against future bloat in the same milestone.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): pin 500-line budget in M2 suite"
```

---

## Task 11: Enforce NFR-append-latency (100 records < 500 ms)

**Files:**
- Modify: `tests/test_audit_append.py`

> Rationale: The spec mandates a `unittest` micro-benchmark — 100 records must complete in under 500 ms wall time. We do not benchmark median latency directly (variance on shared CI hosts is too high); the spec's batch wall-time gate is the canonical assertion.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_append.py`:

```python
import time as _time


class AppendLatencyTests(unittest.TestCase):
    KEY = b"\x44" * 32

    def test_100_record_batch_under_500ms(self) -> None:
        from story_automator.core.audit import AuditLog

        class Fake:
            event_name = "E"

            def __init__(self, i: int) -> None:
                self._i = i

            def to_dict(self) -> dict:
                # ~64 bytes payload — well under the 4 KiB cap in the NFR.
                return {"i": self._i, "note": "abcdefghijklmnopqrstuvwxyz" * 1}

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            start = _time.perf_counter()
            for i in range(100):
                log.append(Fake(i))
            elapsed = _time.perf_counter() - start

        self.assertLess(
            elapsed, 0.5,
            f"100-record batch took {elapsed:.3f}s; NFR cap is 0.500s",
        )
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.AppendLatencyTests -v`
Expected: PASS on any reasonable warm filesystem.

> If it fails: investigate `_read_last_record` — re-streaming the entire file on every append is O(N) per record. The spec accepts this for 100 records, but if the bench fails on CI we may need to cache the last record in the dataclass. **Do not** add a cache yet — landing it without `verify()` semantics risks divergence; treat any failure as a perf bug to investigate, not silently fix.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): assert 100-record append batch under 500ms"
```

---

## Task 12: Enforce that `append` never leaks the key in tracebacks or repr

**Files:**
- Modify: `tests/test_audit_append.py`

> Rationale: The M01 secrets-never-leak test covers `derive_key` and `load_key_from_env`. Now that `AuditLog` carries the key as a field, we add an M2-specific assertion: the dataclass `repr` must not expose `key` bytes, and the timeout exception's `str()` must not embed them either.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_append.py`:

```python
class KeyNeverLeaksTests(unittest.TestCase):
    SECRET_KEY = b"super-secret-canary-key-9c7c9c7c"

    def test_dataclass_repr_does_not_contain_key_bytes(self) -> None:
        from story_automator.core.audit import AuditLog

        log = AuditLog(path=Path("/tmp/x.jsonl"), key=self.SECRET_KEY)
        r = repr(log)
        self.assertNotIn("super-secret-canary-key", r)
        self.assertNotIn(self.SECRET_KEY.hex(), r)

    def test_lock_timeout_message_does_not_contain_key(self) -> None:
        import filelock
        from story_automator.core.audit import AuditLog, AuditLockTimeout

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.SECRET_KEY)
            held = filelock.FileLock(str(log._lock_path))
            held.acquire(timeout=1)
            try:
                with self.assertRaises(AuditLockTimeout) as ctx:
                    class Fake:
                        event_name = "E"

                        def to_dict(self) -> dict:
                            return {}
                    log.append(Fake())
                self.assertNotIn("super-secret-canary-key", str(ctx.exception))
                self.assertNotIn(self.SECRET_KEY.hex(), str(ctx.exception))
            finally:
                held.release()
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.KeyNeverLeaksTests -v`
Expected: FAIL on `test_dataclass_repr_does_not_contain_key_bytes` — the default dataclass `repr` includes every field.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, mark `key` as `repr=False` on the dataclass field. Replace the `AuditLog` field declarations:

```python
    path: pathlib.Path
    key: bytes = dataclasses.field(repr=False)
    _lock_path: pathlib.Path = dataclasses.field(default=None, repr=False)  # type: ignore[assignment]
```

- [ ] **Step 4: Run the test to confirm pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_append.KeyNeverLeaksTests -v`
Expected: PASS (2 tests).

Then re-run the full audit suite to confirm no regression in the shape tests:

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: PASS for every test.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): hide key from AuditLog repr"
```

---

## Task 13: Ruff lint + format pass

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py` (formatting only)
- Modify: `tests/test_audit_append.py` (formatting only)

- [ ] **Step 1: Run ruff check**

Run: `ruff check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py`
Expected: zero findings. If any findings appear, fix them inline (typical fix: trailing whitespace, unused imports, line length).

- [ ] **Step 2: Run ruff format --check**

Run: `ruff format --check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py`
Expected: zero diffs. If diffs appear, run `ruff format skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py` and re-stage.

- [ ] **Step 3: Re-run the full audit test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: PASS for every test.

- [ ] **Step 4: Commit only if formatting changed anything**

```bash
git status --short
# If audit.py or test_audit_append.py shows modifications:
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_append.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(audit): ruff format pass"
# Otherwise: no commit needed for this task.
```

---

## Task 14: Full-suite regression run

**Files:** none

- [ ] **Step 1: Run the full repo test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v`
Expected: PASS — every test across the repo, including the M01 audit-foundations suite and the new M2 append suite.

- [ ] **Step 2: Spot-check git log to confirm conventional commits**

Run: `git log --oneline -n 20`
Expected: every M2 commit follows `feat(audit): …` / `test(audit): …` / `style(audit): …` conventions with the `Generated-By` trailer.

> No commit step — this task is a quality gate only.

---

## Notes for the Implementing Engineer

- **`filelock.FileLock` semantics:** `acquire(timeout=5)` raises `filelock.Timeout` when the timeout elapses; we translate that to our module's `AuditLockTimeout` for caller stability.
- **`prev_tag_hex` is the hex string, not bytes.** Tests in Task 5 hand-decode it with `bytes.fromhex` to verify the boundary. If you accidentally HMAC the hex *string* you'll get a wrong-but-deterministic tag, and `AppendChainTests.test_each_tag_chains_from_previous` will catch it.
- **`json.loads` on a malformed last line raises `json.JSONDecodeError`.** `_read_last_record` deliberately does not swallow it — a malformed last line is a corruption signal and the append path lets it propagate. Verification semantics (returning `(False, last_valid_seq)`) belong to M3's `verify()`, not M2's `append`.
- **No call-site integration here.** `commands/orchestrator.py`, `commands/state.py`, and `commands/orchestrator_epic_agents.py` are out of scope for M2 — they are wired up in a later M04 milestone alongside `audit_for_policy()` and the `telemetry_events` port.
- **Concurrent-append QA gate:** the two-thread test from the spec asserts `verify()` returns `(True, 100)`. Because `verify()` does not exist yet, that test lands in M3. Task 9 above covers the prerequisite (lock acquired with 5s timeout, released on success and on raise).
- **`Event` Protocol is documentation, not enforcement.** `append` never `isinstance`-checks the event. We rely on attribute access; a missing `event_name` or `to_dict()` raises `AttributeError`, which is the right signal for a programming bug at the call site.
