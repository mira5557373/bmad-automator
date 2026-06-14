from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
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


class EventProtocolTests(unittest.TestCase):
    def test_protocol_exists_and_is_typing_protocol(self) -> None:
        from story_automator.core.audit import Event
        import typing

        # ``Event`` must be a runtime-checkable Protocol so we can structurally
        # match telemetry events when they arrive in a later milestone.
        self.assertTrue(
            hasattr(Event, "_is_runtime_protocol") or hasattr(Event, "_is_protocol"),
            "Event must be a typing.Protocol",
        )
        self.assertTrue(
            issubclass(type(Event), type(typing.Protocol))
            or getattr(Event, "_is_protocol", False)
        )

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
            {
                "seq": 7,
                "ts": "2026-06-14T01:02:03Z",
                "event": "EscalationRaised",
                "payload": {"reason": "block"},
            }
        ).encode("utf-8")
        self.assertEqual(
            _canonical_record_bytes(
                seq=7,
                ts="2026-06-14T01:02:03Z",
                event="EscalationRaised",
                payload={"reason": "block"},
            ),
            expected,
        )

    def test_field_order_is_fixed(self) -> None:
        # Field order must be seq, ts, event, payload regardless of payload
        # iteration order. Two payloads with the same keys-in-different-order
        # must produce identical canonical bytes only when the payload mapping
        # itself preserves order (Python 3.7+ dicts do).
        from story_automator.core.audit import _canonical_record_bytes

        b = _canonical_record_bytes(seq=1, ts="t", event="E", payload={"a": 1, "b": 2})
        # Ensure "seq" appears before "ts" appears before "event" appears
        # before "payload" in the canonical byte stream.
        s = b.decode("utf-8")
        i_seq, i_ts, i_event, i_payload = (
            s.index("seq"),
            s.index("ts"),
            s.index("event"),
            s.index("payload"),
        )
        self.assertLess(i_seq, i_ts)
        self.assertLess(i_ts, i_event)
        self.assertLess(i_event, i_payload)


class ComputeTagTests(unittest.TestCase):
    KEY = b"\xaa" * 32

    def test_seq1_uses_32_zero_bytes_as_prev_tag(self) -> None:
        from story_automator.core.audit import (
            _canonical_record_bytes,
            _compute_tag,
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
            _canonical_record_bytes,
            _compute_tag,
        )

        prev_hex = "ab" * 32  # 32 bytes
        canonical = _canonical_record_bytes(
            seq=2, ts="2026-06-14T00:00:01Z", event="E", payload={"x": 1}
        )
        expected = hmac.new(
            self.KEY, bytes.fromhex(prev_hex) + canonical, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            _compute_tag(key=self.KEY, prev_tag_hex=prev_hex, canonical=canonical),
            expected,
        )

    def test_returns_lowercase_hex(self) -> None:
        from story_automator.core.audit import (
            _canonical_record_bytes,
            _compute_tag,
        )

        canonical = _canonical_record_bytes(seq=1, ts="t", event="E", payload={})
        tag = _compute_tag(key=self.KEY, prev_tag_hex=None, canonical=canonical)
        self.assertEqual(tag, tag.lower())
        self.assertEqual(len(tag), 64)


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
                json.dumps({"seq": 1, "tag": "a" * 64})
                + "\n"
                + json.dumps({"seq": 2, "tag": "b" * 64})
                + "\n",
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


class AppendFirstRecordTests(unittest.TestCase):
    KEY = b"\x11" * 32

    def _fake_event(self, name: str = "EscalationRaised", payload: dict | None = None):
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
            self.assertEqual(set(rec.keys()), {"seq", "ts", "event", "payload", "tag"})

    def test_event_name_and_payload_copied_from_event(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(
                self._fake_event(
                    name="StoryStateChanged", payload={"from": "draft", "to": "qa"}
                )
            )
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["event"], "StoryStateChanged")
            self.assertEqual(rec["payload"], {"from": "draft", "to": "qa"})

    def test_ts_matches_iso_now_format(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(self._fake_event())
            rec = json.loads(p.read_text(encoding="utf-8").strip())
            self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_tag_matches_compute_tag_with_zero_prev(self) -> None:
        from story_automator.core.audit import (
            AuditLog,
            _canonical_record_bytes,
            _compute_tag,
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
                    seq=rec["seq"],
                    ts=rec["ts"],
                    event=rec["event"],
                    payload=rec["payload"],
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
            AuditLog,
            _canonical_record_bytes,
            _compute_tag,
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
                        seq=rec["seq"],
                        ts=rec["ts"],
                        event=rec["event"],
                        payload=rec["payload"],
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


class AuditModuleSizeBudgetM2Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
        from pathlib import Path

        audit_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "audit.py"
        )
        line_count = sum(1 for _ in audit_path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"audit.py is {line_count} lines (budget: 500 per NFR-500-line-cap)",
        )


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


if __name__ == "__main__":
    unittest.main()
