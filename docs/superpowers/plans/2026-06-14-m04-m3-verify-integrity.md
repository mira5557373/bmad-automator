# M04 Milestone 3: Audit-Trail Chain Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `AuditLog.verify() -> tuple[bool, int]` to `core/audit.py` that streams the JSONL log line-by-line, recomputes each record's HMAC chain tag, and returns `(True, last_seq)` for an intact log or `(False, last_valid_seq)` on the first detected anomaly — mutation, missing field, malformed JSON, or non-contiguous seq — without ever buffering more than one record in memory.

**Architecture:** `verify()` opens `self.path` in binary read mode (or skips the open entirely when the file is missing or empty per REQ-09), then iterates with a generator helper `_iter_record_lines(handle)` that yields one stripped non-blank bytes line at a time. For each line we parse JSON, validate the five-field shape, check that `seq == prev_seq + 1` (or `seq == 1` for the first record), recompute `canonical = _canonical_record_bytes(...)`, recompute `expected_tag = _compute_tag(key=self.key, prev_tag_hex=prev_tag, canonical=canonical)`, and compare to the record's `tag`. Any failure returns `(False, last_valid_seq)`; success advances `last_valid_seq = seq; prev_tag = tag` and continues. The chain key is the same `self.key` already on the dataclass — there is no parallel key path. The memory invariant is enforced by reading bytes one line at a time and never holding a list of records.

**Tech Stack:** Python 3.11+, standard library only (`json`, `pathlib`, `typing`, `threading` for the concurrent QA test). The verify path reuses the M2 helpers `_canonical_record_bytes`, `_compute_tag`, `_ZERO_TAG`. Tests use `unittest` and run with `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py"`. Lint with `ruff check` and `ruff format --check`. Coverage is measured via `coverage run -m unittest && coverage report --include='*/audit.py'`.

---

## Spec Coverage Map

| Spec ID | Requirement | Tasks |
|---|---|---|
| REQ-08 | `verify()` walks chain, returns `(True, last_seq)` clean or `(False, last_valid_seq)` on first mismatch / missing field / malformed JSON / non-contiguous seq | Tasks 2, 4, 5, 6, 7, 8 |
| REQ-09 | `verify()` returns `(True, 0)` for missing or empty file, does not create the file | Tasks 1, 3 |
| NFR-streaming-memory | At most one record + running tag in memory | Tasks 2, 10 |
| QA-tamper-test | Mutate one byte of mid-chain `payload` field on disk, assert `verify() == (False, n-1)` | Task 6 |
| QA-truncation-test | Remove trailing record, assert `verify() == (True, n-1)` | Task 7 |
| QA-concurrent-test | Two threads × 50 records each → chain verifies with 100 contiguous seqs | Task 9 |
| QA-coverage-85 | `coverage run -m unittest && coverage report --include='*/audit.py' --fail-under=85` passes | Task 12 |
| NFR-500-line-cap | Module ≤ 500 lines | Task 11 |

Out of scope for M3 (later M04 slices): `audit_for_policy()`, the three call-site integrations (`commands/orchestrator.py`, `commands/state.py`, `commands/orchestrator_epic_agents.py`), and the `security.audit_trail` policy gate. Those land in M4.

---

## File Structure

- **Modify:** `skills/bmad-story-automator/src/story_automator/core/audit.py` — add the `verify` method, the `_iter_record_lines` streaming helper, and the five required-field constant. No existing helper is renamed or rewritten; M2's `_canonical_record_bytes`, `_compute_tag`, and `_ZERO_TAG` are reused unchanged.
- **Create:** `tests/test_audit_verify.py` — new `unittest.TestCase` suite covering verify happy path, every documented failure mode (tamper, truncation, malformed JSON, missing field, non-contiguous seq, wrong starting seq), the missing-file / empty-file edge cases, the two-thread concurrent QA test, and the streaming-memory structural assertion.

No call-site files (`commands/*`) are touched. No new third-party dependency.

---

## Task 1: `verify()` returns `(True, 0)` when the log file is missing

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_verify.py` with:

```python
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path


class VerifyMissingFileTests(unittest.TestCase):
    KEY = b"\x55" * 32

    def test_returns_true_zero_when_file_does_not_exist(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            self.assertFalse(p.exists())
            log = AuditLog(path=p, key=self.KEY)
            self.assertEqual(log.verify(), (True, 0))

    def test_verify_does_not_create_the_file_as_side_effect(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.verify()
            self.assertFalse(
                p.exists(),
                "verify() must not create the audit log file (REQ-09)",
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify -v`
Expected: FAIL with `AttributeError: 'AuditLog' object has no attribute 'verify'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, add a method to the `AuditLog` dataclass body (immediately after `append`):

```python
    def verify(self) -> tuple[bool, int]:
        """Walk the log and recompute every chain tag.

        Returns ``(True, last_seq)`` when the chain is intact, or
        ``(False, last_valid_seq)`` on the first detected anomaly:
        malformed JSON, missing field, non-contiguous seq, or tag
        mismatch. Returns ``(True, 0)`` when the log file does not
        exist or is empty (REQ-09). Streams the file line by line and
        never buffers more than one record at a time.
        """
        if not self.path.exists():
            return (True, 0)
        return (True, 0)  # placeholder — extended in subsequent tasks
```

> Note: This is a deliberately incomplete first cut. Each subsequent task adds one branch and the test that drives it. The "placeholder returning `(True, 0)` for an existing file" line will be replaced in Task 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyMissingFileTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): verify returns (True, 0) when log missing"
```

---

## Task 2: Add `_iter_record_lines` streaming helper

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_verify.py`

> Rationale: NFR-streaming-memory requires `verify()` to hold at most one record + running tag in memory. We extract the line iteration into a tiny pure generator so the verify body never accidentally accumulates a list of records, and so a structural test (Task 10) can verify the surface.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_verify.py`:

```python
class IterRecordLinesTests(unittest.TestCase):
    def test_returns_empty_iterator_on_empty_file(self) -> None:
        from story_automator.core.audit import _iter_record_lines

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            with p.open("rb") as handle:
                self.assertEqual(list(_iter_record_lines(handle)), [])

    def test_yields_bytes_lines_in_order(self) -> None:
        from story_automator.core.audit import _iter_record_lines

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text(
                '{"seq":1}\n{"seq":2}\n{"seq":3}\n', encoding="utf-8"
            )
            with p.open("rb") as handle:
                lines = list(_iter_record_lines(handle))
            self.assertEqual(
                lines, [b'{"seq":1}', b'{"seq":2}', b'{"seq":3}']
            )

    def test_skips_blank_lines(self) -> None:
        from story_automator.core.audit import _iter_record_lines

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text(
                '{"seq":1}\n\n{"seq":2}\n\n', encoding="utf-8"
            )
            with p.open("rb") as handle:
                lines = list(_iter_record_lines(handle))
            self.assertEqual(lines, [b'{"seq":1}', b'{"seq":2}'])

    def test_is_a_generator_not_a_list(self) -> None:
        # Structural NFR check: the helper must be lazy. A list
        # comprehension would defeat the streaming-memory invariant.
        import types
        from story_automator.core.audit import _iter_record_lines

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text("{}\n", encoding="utf-8")
            with p.open("rb") as handle:
                result = _iter_record_lines(handle)
                self.assertIsInstance(result, types.GeneratorType)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.IterRecordLinesTests -v`
Expected: FAIL with `ImportError: cannot import name '_iter_record_lines'`.

- [ ] **Step 3: Write minimal implementation**

In `core/audit.py`, add this generator just above the `AuditLog` dataclass declaration (next to `_read_last_record`):

```python
def _iter_record_lines(handle: Any) -> "Iterator[bytes]":
    """Yield each non-blank line from an open binary file handle, in order.

    The handle is consumed lazily: only one line is held in memory at a
    time. Trailing or interior blank lines are skipped. The caller is
    responsible for keeping the handle open across iteration; closing
    it mid-loop raises ``ValueError`` from the underlying read.
    """
    for raw in handle:
        line = raw.rstrip(b"\r\n")
        if not line:
            continue
        yield line
```

Also extend the typing import at the top of the module to include `Iterator`:

```python
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.IterRecordLinesTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): streaming line iterator for verify"
```

---

## Task 3: `verify()` returns `(True, 0)` on an empty file (file exists, zero records)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyEmptyFileTests(unittest.TestCase):
    KEY = b"\x55" * 32

    def test_returns_true_zero_when_file_is_empty(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            p.write_text("", encoding="utf-8")
            log = AuditLog(path=p, key=self.KEY)
            self.assertEqual(log.verify(), (True, 0))

    def test_returns_true_zero_on_blank_lines_only(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            p.write_text("\n\n\n", encoding="utf-8")
            log = AuditLog(path=p, key=self.KEY)
            self.assertEqual(log.verify(), (True, 0))
```

- [ ] **Step 2: Run test to verify it fails or already passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyEmptyFileTests -v`
Expected: The first test PASSES already (the Task 1 placeholder returns `(True, 0)` for any file path). The second test PASSES too. If both pass we still want the Task 4 changes to keep these passing — proceed.

> No commit yet — these tests will be re-asserted alongside the Task 4 implementation rewrite.

- [ ] **Step 3: Commit the tests now to lock the contract**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): pin verify (True, 0) for empty file"
```

---

## Task 4: `verify()` happy path — single record chain verifies clean

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_verify.py`:

```python
class _FakeEvent:
    """Minimal duck-typed event for verify tests."""

    def __init__(self, name: str, payload: dict) -> None:
        self.event_name = name
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class VerifySingleRecordHappyPathTests(unittest.TestCase):
    KEY = b"\x66" * 32

    def test_single_appended_record_verifies_clean(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("EscalationRaised", {"reason": "block"}))
            self.assertEqual(log.verify(), (True, 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifySingleRecordHappyPathTests -v`
Expected: FAIL — the Task 1 placeholder still returns `(True, 0)` regardless of file contents.

- [ ] **Step 3: Write the real `verify` body**

In `core/audit.py`, replace the existing `verify` method body with the streaming implementation. Add the required-field tuple as a module-level constant just above the `AuditLog` dataclass:

```python
_REQUIRED_RECORD_FIELDS = ("seq", "ts", "event", "payload", "tag")
```

Then replace the entire `verify` method on `AuditLog` with:

```python
    def verify(self) -> tuple[bool, int]:
        """Walk the log and recompute every chain tag.

        Returns ``(True, last_seq)`` when the chain is intact, or
        ``(False, last_valid_seq)`` on the first detected anomaly:
        malformed JSON, missing field, non-contiguous seq, or tag
        mismatch. Returns ``(True, 0)`` when the log file does not
        exist or is empty (REQ-09). Streams the file line by line and
        never buffers more than one record at a time.
        """
        if not self.path.exists():
            return (True, 0)

        last_valid_seq = 0
        prev_tag_hex: str | None = None
        with self.path.open("rb") as handle:
            for raw_line in _iter_record_lines(handle):
                try:
                    record = _json.loads(raw_line.decode("utf-8"))
                except _json.JSONDecodeError:
                    return (False, last_valid_seq)
                if not isinstance(record, dict):
                    return (False, last_valid_seq)
                for field in _REQUIRED_RECORD_FIELDS:
                    if field not in record:
                        return (False, last_valid_seq)
                seq = record["seq"]
                if not isinstance(seq, int) or seq != last_valid_seq + 1:
                    return (False, last_valid_seq)
                canonical = _canonical_record_bytes(
                    seq=seq,
                    ts=record["ts"],
                    event=record["event"],
                    payload=record["payload"],
                )
                expected_tag = _compute_tag(
                    key=self.key,
                    prev_tag_hex=prev_tag_hex,
                    canonical=canonical,
                )
                if not hmac.compare_digest(expected_tag, record["tag"]):
                    return (False, last_valid_seq)
                last_valid_seq = seq
                prev_tag_hex = record["tag"]
        return (True, last_valid_seq)
```

> Note: `hmac.compare_digest` is a constant-time string comparison and is already imported at the top of the module (M1 uses it for HKDF). Using it here is defence-in-depth — the verify path is offline so timing-attack risk is low, but it costs nothing.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifySingleRecordHappyPathTests -v`
Expected: PASS (1 test).

Then re-run the missing-file and empty-file tests to confirm no regression:

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyMissingFileTests tests.test_audit_verify.VerifyEmptyFileTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): verify recomputes chain tags streaming"
```

---

## Task 5: `verify()` happy path — multi-record chain

**Files:**
- Test: `tests/test_audit_verify.py` (no code change — Task 4 impl already covers this; we lock in the contract)

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyMultiRecordHappyPathTests(unittest.TestCase):
    KEY = b"\x77" * 32

    def test_three_records_verify_clean(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(3):
                log.append(_FakeEvent("E", {"i": i}))
            self.assertEqual(log.verify(), (True, 3))

    def test_hundred_records_verify_clean(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(100):
                log.append(_FakeEvent("E", {"i": i, "note": "x" * 16}))
            self.assertEqual(log.verify(), (True, 100))

    def test_verify_after_fresh_instance_reads_chain_from_disk(self) -> None:
        # A fresh AuditLog (no in-memory cache) must verify a chain that
        # an earlier instance wrote. This guards against verify accidentally
        # relying on the M2 append cache fields.
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            writer = AuditLog(path=p, key=self.KEY)
            for i in range(5):
                writer.append(_FakeEvent("E", {"i": i}))
            verifier = AuditLog(path=p, key=self.KEY)
            self.assertEqual(verifier.verify(), (True, 5))
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyMultiRecordHappyPathTests -v`
Expected: PASS (3 tests).

> If `test_verify_after_fresh_instance_reads_chain_from_disk` fails, the Task 4 implementation likely consults `self._cached_seq` somewhere instead of streaming from disk — fix that before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): verify happy path across multi-record chains"
```

---

## Task 6: QA-tamper-test — mutated payload byte breaks the chain

**Files:**
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyTamperDetectionTests(unittest.TestCase):
    KEY = b"\x88" * 32

    def _mutate_payload_byte(self, path: Path, target_seq: int) -> None:
        """Flip one byte inside the payload field of the target seq's line."""
        lines = path.read_bytes().splitlines(keepends=True)
        idx = target_seq - 1
        line = lines[idx]
        # Locate the payload value's first character (the '{' after
        # `"payload":`) and flip its byte to '['. The structural change
        # keeps the line as valid JSON but mutates the canonical bytes.
        marker = b'"payload":'
        pos = line.index(marker) + len(marker)
        # Flip the payload-opening byte (a '{') to '[': still parseable
        # but produces a different canonical record.
        original = line[pos:pos + 1]
        replacement = b"[" if original == b"{" else b"{"
        mutated = line[:pos] + replacement + line[pos + 1 :]
        # We must also flip the matching closer to keep JSON valid. The
        # mutated payload becomes an empty list/object, but the tag
        # comparison fires first so JSON validity past `payload` is
        # immaterial — still, be conservative and balance braces.
        if original == b"{":
            close_pos = mutated.index(b"}", pos)
            mutated = mutated[:close_pos] + b"]" + mutated[close_pos + 1 :]
        else:
            close_pos = mutated.index(b"]", pos)
            mutated = mutated[:close_pos] + b"}" + mutated[close_pos + 1 :]
        lines[idx] = mutated
        path.write_bytes(b"".join(lines))

    def test_mutated_payload_returns_false_at_previous_seq(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(5):
                log.append(_FakeEvent("E", {"i": i}))
            # Mutate record seq=3.
            self._mutate_payload_byte(p, target_seq=3)
            self.assertEqual(log.verify(), (False, 2))

    def test_mutated_first_record_returns_false_zero(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(3):
                log.append(_FakeEvent("E", {"i": i}))
            self._mutate_payload_byte(p, target_seq=1)
            self.assertEqual(log.verify(), (False, 0))

    def test_mutated_tag_field_returns_false_at_previous_seq(self) -> None:
        # Even if the payload is intact, flipping a single byte of the
        # tag itself must be caught.
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(3):
                log.append(_FakeEvent("E", {"i": i}))
            text = p.read_text(encoding="utf-8")
            recs = [json.loads(line) for line in text.splitlines() if line]
            # Replace the second record's tag with a tag of the right
            # shape but wrong value.
            recs[1]["tag"] = "f" * 64
            from story_automator.core.common import compact_json

            p.write_text(
                "\n".join(compact_json(r) for r in recs) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(log.verify(), (False, 1))
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyTamperDetectionTests -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): tamper detection at the mutated record's seq-1"
```

---

## Task 7: QA-truncation-test — truncation is distinguishable from mutation

**Files:**
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyTruncationDistinguishableTests(unittest.TestCase):
    KEY = b"\x99" * 32

    def test_trailing_record_removed_returns_true_n_minus_1(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(5):
                log.append(_FakeEvent("E", {"i": i}))
            lines = p.read_bytes().splitlines(keepends=True)
            # Drop the last line (seq=5).
            p.write_bytes(b"".join(lines[:-1]))
            self.assertEqual(log.verify(), (True, 4))

    def test_multiple_trailing_records_removed_returns_true_at_last_remaining(
        self,
    ) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            for i in range(5):
                log.append(_FakeEvent("E", {"i": i}))
            lines = p.read_bytes().splitlines(keepends=True)
            # Drop the last three lines (keep seq=1, seq=2).
            p.write_bytes(b"".join(lines[:2]))
            self.assertEqual(log.verify(), (True, 2))

    def test_truncation_and_mutation_differ(self) -> None:
        # The whole point of the QA gate: truncation yields (True, n-k),
        # mutation yields (False, n-1). Verify both outcomes from the
        # same starting log to make the distinction explicit.
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p_a = Path(d) / "a.jsonl"
            p_b = Path(d) / "b.jsonl"
            for p in (p_a, p_b):
                log = AuditLog(path=p, key=self.KEY)
                for i in range(4):
                    log.append(_FakeEvent("E", {"i": i}))

            # Truncate p_a's last record.
            lines = p_a.read_bytes().splitlines(keepends=True)
            p_a.write_bytes(b"".join(lines[:-1]))
            # Mutate p_b's last record (flip one byte of payload).
            lines = p_b.read_bytes().splitlines(keepends=True)
            line = lines[-1].replace(b'"i":3', b'"i":7', 1)
            lines[-1] = line
            p_b.write_bytes(b"".join(lines))

            log_a = AuditLog(path=p_a, key=self.KEY)
            log_b = AuditLog(path=p_b, key=self.KEY)
            self.assertEqual(log_a.verify(), (True, 3))
            self.assertEqual(log_b.verify(), (False, 3))
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyTruncationDistinguishableTests -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): truncation distinguishable from mutation"
```

---

## Task 8: REQ-08 corner cases — malformed JSON, missing field, non-contiguous seq

**Files:**
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyMalformedJsonTests(unittest.TestCase):
    KEY = b"\xaa" * 32

    def _write_lines(self, path: Path, lines: list[bytes]) -> None:
        path.write_bytes(b"\n".join(lines) + b"\n")

    def test_malformed_json_on_first_line_returns_false_zero(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            self._write_lines(p, [b"not-json"])
            self.assertEqual(AuditLog(path=p, key=self.KEY).verify(), (False, 0))

    def test_malformed_json_on_third_line_returns_false_at_two(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            log.append(_FakeEvent("E", {"i": 1}))
            with p.open("ab") as handle:
                handle.write(b"{not valid json}\n")
            self.assertEqual(log.verify(), (False, 2))

    def test_non_dict_top_level_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            with p.open("ab") as handle:
                handle.write(b"[1, 2, 3]\n")
            self.assertEqual(log.verify(), (False, 1))


class VerifyMissingFieldTests(unittest.TestCase):
    KEY = b"\xbb" * 32

    def test_missing_tag_field_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            log.append(_FakeEvent("E", {"i": 1}))
            # Append a record missing the `tag` field.
            broken = {
                "seq": 3, "ts": "2026-06-14T00:00:00Z",
                "event": "E", "payload": {},
            }
            with p.open("ab") as handle:
                handle.write((compact_json(broken) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 2))

    def test_missing_payload_field_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            broken = {
                "seq": 2, "ts": "t", "event": "E",
                "tag": "0" * 64,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(broken) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))


class VerifyNonContiguousSeqTests(unittest.TestCase):
    KEY = b"\xcc" * 32

    def test_first_record_with_seq_not_one_returns_false_zero(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            # Hand-craft a record whose seq is 2 but file is otherwise empty.
            rec = {
                "seq": 2, "ts": "t", "event": "E",
                "payload": {}, "tag": "0" * 64,
            }
            p.write_bytes((compact_json(rec) + "\n").encode("utf-8"))
            self.assertEqual(AuditLog(path=p, key=self.KEY).verify(), (False, 0))

    def test_seq_gap_returns_false_at_last_contiguous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))  # seq=1
            log.append(_FakeEvent("E", {"i": 1}))  # seq=2
            # Append seq=4 (skipping seq=3).
            jump = {
                "seq": 4, "ts": "t", "event": "E",
                "payload": {}, "tag": "0" * 64,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(jump) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 2))

    def test_seq_not_an_int_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            bad = {
                "seq": "two", "ts": "t", "event": "E",
                "payload": {}, "tag": "0" * 64,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(bad) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyMalformedJsonTests tests.test_audit_verify.VerifyMissingFieldTests tests.test_audit_verify.VerifyNonContiguousSeqTests -v`
Expected: PASS (8 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): malformed json / missing field / seq gap detection"
```

---

## Task 9: QA-concurrent-test — two threads × 50 records verify clean

**Files:**
- Test: `tests/test_audit_verify.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyConcurrentAppendTests(unittest.TestCase):
    KEY = b"\xdd" * 32

    def test_two_threads_each_appending_50_yields_clean_chain_of_100(
        self,
    ) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)

            barrier = threading.Barrier(2)
            errors: list[BaseException] = []

            def worker(label: str) -> None:
                try:
                    barrier.wait()
                    for i in range(50):
                        log.append(_FakeEvent(f"E-{label}", {"i": i, "w": label}))
                except BaseException as exc:  # noqa: BLE001 - record and rethrow
                    errors.append(exc)

            t1 = threading.Thread(target=worker, args=("a",))
            t2 = threading.Thread(target=worker, args=("b",))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
            self.assertFalse(
                t1.is_alive() or t2.is_alive(),
                "concurrent append workers did not finish within 30s",
            )
            self.assertEqual(errors, [], f"worker raised: {errors!r}")

            ok, last_seq = log.verify()
            self.assertTrue(
                ok, f"chain failed verification after concurrent writes: {last_seq}"
            )
            self.assertEqual(
                last_seq, 100,
                "expected 100 contiguous records after 2 × 50 concurrent appends",
            )

            # Spot-check that the file actually has 100 lines.
            line_count = sum(
                1 for line in p.read_text(encoding="utf-8").splitlines() if line
            )
            self.assertEqual(line_count, 100)

            # Spot-check that worker labels are interleaved (not strictly
            # required, but if all 50 a's preceded all 50 b's the test
            # would be much weaker as a concurrency exercise).
            labels = [
                json.loads(line)["payload"]["w"]
                for line in p.read_text(encoding="utf-8").splitlines() if line
            ]
            self.assertEqual(set(labels), {"a", "b"})
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyConcurrentAppendTests -v`
Expected: PASS (1 test).

> If the chain fails verification, the bug is in M2's `append`. Likely culprit: the in-memory cache (`_cached_seq` / `_cached_tag` / `_cached_size`) is stale because two threads share the same `AuditLog` instance and both hold the FileLock serially but the cache is not re-read. Diagnose by checking whether `verify()` succeeds when run from a *fresh* `AuditLog` instance — if it does, the bug is in the cache; if it doesn't, the bug is in the chain itself.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): two-thread concurrent append verifies clean"
```

---

## Task 10: NFR-streaming-memory — structural test that verify does not buffer records

**Files:**
- Test: `tests/test_audit_verify.py`

> Rationale: The NFR is hard to assert directly (we'd need `tracemalloc` + a 1 GiB file). We assert two structural properties that together rule out the obvious buffering anti-patterns: (a) the verify method's source must not contain `readlines()` or `read_text()` calls; (b) running `verify()` against a 5000-record log must complete without holding a list-shaped buffer, measured by a `tracemalloc` peak under a generous bound (1 MiB) that a buffered implementation would blow past.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class VerifyStreamingMemoryTests(unittest.TestCase):
    KEY = b"\xee" * 32

    def test_verify_source_avoids_buffering_calls(self) -> None:
        # Static check: the verify method body must not call
        # readlines() or read_text() — both load the whole file at once.
        import inspect
        from story_automator.core.audit import AuditLog

        source = inspect.getsource(AuditLog.verify)
        for forbidden in ("readlines()", ".read_text(", ".read_bytes("):
            self.assertNotIn(
                forbidden, source,
                f"verify() must stream — {forbidden} loads the whole file",
            )

    def test_verify_uses_iter_record_lines(self) -> None:
        # Verify must dispatch to our streaming generator helper.
        import inspect
        from story_automator.core.audit import AuditLog

        source = inspect.getsource(AuditLog.verify)
        self.assertIn(
            "_iter_record_lines", source,
            "verify() must use the streaming generator helper",
        )

    def test_verify_peak_memory_stays_bounded_on_5000_records(self) -> None:
        import tracemalloc
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            payload_blob = "x" * 512  # ~512 B payload per record
            for i in range(5000):
                log.append(_FakeEvent("E", {"i": i, "blob": payload_blob}))

            # Re-open a fresh verifier so the M2 append-cache fields do
            # not pollute the measurement.
            verifier = AuditLog(path=p, key=self.KEY)
            tracemalloc.start()
            ok, last_seq = verifier.verify()
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertTrue(ok)
            self.assertEqual(last_seq, 5000)
            # A buffered implementation (read all 5000 lines into a list)
            # would peak ~2.5 MiB+. A streaming implementation peaks well
            # under 1 MiB even with Python's per-string allocator overhead.
            self.assertLess(
                peak, 1_048_576,
                f"verify() peaked at {peak} bytes — expected <1 MiB streaming",
            )
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.VerifyStreamingMemoryTests -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): structural + tracemalloc check on verify streaming"
```

---

## Task 11: Re-affirm 500-line module budget

**Files:**
- Test: `tests/test_audit_verify.py`

> Rationale: The M01 and M2 test files already pin `≤ 500` lines. We add a sibling assertion in the M3 file so a developer running only `tests.test_audit_verify` will still catch a size regression introduced by `verify`.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
class AuditModuleSizeBudgetM3Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
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

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.AuditModuleSizeBudgetM3Tests -v`
Expected: PASS. (The implemented module ends M3 well under 500 lines.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): pin 500-line budget in M3 suite"
```

---

## Task 12: QA-coverage-85 — coverage gate for `core/audit.py`

**Files:**
- Test: `tests/test_audit_verify.py`

> Rationale: The spec requires `≥ 85%` statement coverage for `core/audit.py` measured by `coverage run -m unittest`. Programmatic in-process measurement is unreliable because the harness's own test loader has already imported the module and forcing a re-import + inline re-exercise misses many branches (lock-timeout, cache-miss, `_hkdf_expand` length cap, `_scan_last_line` chunk walks, `_compute_tag` with non-None prev). The canonical and reproducible measurement is to spawn `coverage run -m unittest discover -p test_audit*.py` as a subprocess and parse the report — that's exactly what CI does. The test gracefully `skipTest`s when the `coverage` CLI is not on `PATH` so the suite still passes on minimal sandboxes; the canonical CI invocation (Task 14) is the gate of record.

- [ ] **Step 1: Write the test**

Append to `tests/test_audit_verify.py`:

```python
import re as _re
import shutil as _shutil
import subprocess as _subprocess
import sys as _sys


class AuditCoverageGateTests(unittest.TestCase):
    """Assert >=85% statement coverage for core/audit.py via subprocess.

    Runs the canonical CI invocation:
        coverage run --source=<core> -m unittest discover -s tests -p test_audit*.py
        coverage report --include='*/audit.py'

    and parses the percentage off the last line of ``coverage report`` output.
    Skipped when ``coverage`` is not on PATH.
    """

    REPO_ROOT = Path(__file__).resolve().parents[1]

    def _coverage_executable(self) -> str | None:
        return _shutil.which("coverage")

    def test_audit_coverage_at_least_85_percent(self) -> None:
        coverage_exe = self._coverage_executable()
        if coverage_exe is None:
            self.skipTest("coverage CLI not on PATH in this environment")

        import os as _os

        src_root = self.REPO_ROOT / "skills" / "bmad-story-automator" / "src"
        audit_dir = src_root / "story_automator" / "core"

        env = dict(_os.environ)
        env["PYTHONPATH"] = str(src_root) + _os.pathsep + env.get("PYTHONPATH", "")

        # Use a private coverage data file so parallel runs and the
        # external CI gate don't fight over .coverage.
        data_file = str(self.REPO_ROOT / ".coverage.m3-gate")
        env["COVERAGE_FILE"] = data_file

        run = _subprocess.run(
            [
                coverage_exe, "run",
                f"--source={audit_dir}",
                "-m", "unittest", "discover",
                "-s", str(self.REPO_ROOT / "tests"),
                "-p", "test_audit*.py",
            ],
            cwd=str(self.REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            run.returncode, 0,
            f"coverage run failed:\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}",
        )

        report = _subprocess.run(
            [coverage_exe, "report", "--include=*/audit.py"],
            cwd=str(self.REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Clean up the private data file regardless of outcome.
        try:
            _os.unlink(data_file)
        except FileNotFoundError:
            pass

        self.assertEqual(
            report.returncode, 0,
            f"coverage report failed:\nSTDOUT:\n{report.stdout}\n"
            f"STDERR:\n{report.stderr}",
        )

        # The TOTAL line ends with the overall percentage, e.g.:
        #   TOTAL    150    10    93%
        match = _re.search(r"TOTAL.*?(\d+)%", report.stdout)
        self.assertIsNotNone(
            match,
            f"could not parse TOTAL line from coverage report:\n{report.stdout}",
        )
        assert match is not None  # narrow for type-checker
        percent = int(match.group(1))
        self.assertGreaterEqual(
            percent, 85,
            f"audit.py coverage = {percent}% (gate: 85%)\n{report.stdout}",
        )
```

- [ ] **Step 2: Install the `coverage` CLI locally if not present**

Run: `python -c "import coverage" 2>&1 || python -m pip install coverage`
Expected: `coverage` CLI on PATH. (If `pip install` is not available in the sandbox, the test will `skipTest` and the gate must be enforced via the external invocation documented in Task 14.)

- [ ] **Step 3: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_verify.AuditCoverageGateTests -v`
Expected: PASS (when coverage is installed) or SKIP (when not). If FAIL with `coverage = X%`, the report output lists per-module lines; identify uncovered branches in `audit.py` and add tests until the percentage clears 85.

- [ ] **Step 4: Commit**

```bash
git add tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): assert >=85% statement coverage via subprocess"
```

---

## Task 13: Ruff lint + format pass

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py` (formatting only)
- Modify: `tests/test_audit_verify.py` (formatting only)

- [ ] **Step 1: Run ruff check**

Run: `ruff check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py`
Expected: zero findings. If any findings appear, fix them inline.

- [ ] **Step 2: Run ruff format --check**

Run: `ruff format --check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py`
Expected: zero diffs. If diffs appear, run `ruff format skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py` and re-stage.

- [ ] **Step 3: Re-run the full audit test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: PASS for every test.

- [ ] **Step 4: Commit only if formatting changed anything**

```bash
git status --short
# If audit.py or test_audit_verify.py shows modifications:
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_verify.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(audit): ruff format pass"
# Otherwise: no commit needed for this task.
```

---

## Task 14: Full-suite regression + external coverage gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full repo test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v`
Expected: PASS for every test across the repo (M01 foundations + M2 append + M3 verify).

- [ ] **Step 2: Run the external coverage gate**

Run:
```bash
coverage run --source=skills/bmad-story-automator/src/story_automator/core/audit \
    -m unittest discover -s tests -p "test_audit*.py"
coverage report --include='*/audit.py' --fail-under=85
```
Expected: `coverage report` exits 0 with `audit.py` at ≥ 85%.

> If coverage is below the gate, the report output lists the uncovered line numbers — add a test that exercises them and re-run.

- [ ] **Step 3: Spot-check git log to confirm conventional commits**

Run: `git log --oneline -n 25`
Expected: every M3 commit follows `feat(audit): …` / `test(audit): …` / `style(audit): …` conventions with the `Generated-By` trailer.

> No commit step — this task is a quality gate only.

---

## Notes for the Implementing Engineer

- **`verify()` reuses `self.key`.** There is no parallel key-loading path in M3. Call sites in M4 will construct the `AuditLog` with the env-derived key and then call `verify()` directly.
- **`hmac.compare_digest` over `==`.** Although this code path is offline, using constant-time compare is the cheap and correct default and matches the broader audit-module posture of never leaking key-shaped bytes through behaviour.
- **`_iter_record_lines` is private.** It is not added to `__all__` and is not exposed to callers; tests import it directly to enforce streaming semantics.
- **`_REQUIRED_RECORD_FIELDS` is a module-level constant.** Defining it once (not per-call) keeps the verify loop tight and gives a single place to update if the schema gains a field.
- **The concurrent test depends on M2's filelock contract.** If it fails, do *not* edit `verify()` to paper over the bug — the chain itself is broken on disk and the test is doing exactly what it should.
- **Coverage gate is enforced both inline (Task 12) and externally (Task 14).** The inline test gracefully skips when `coverage` is not installed; the external invocation in `npm run verify` is the canonical CI gate.
- **No call-site integration here.** `audit_for_policy()` and the three call-site hooks are M4. Do not touch `commands/*` in this milestone.
