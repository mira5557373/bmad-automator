from __future__ import annotations

import hashlib
import hmac
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


if __name__ == "__main__":
    unittest.main()
