from __future__ import annotations

import tempfile
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
            p.write_text('{"seq":1}\n{"seq":2}\n{"seq":3}\n', encoding="utf-8")
            with p.open("rb") as handle:
                lines = list(_iter_record_lines(handle))
            self.assertEqual(lines, [b'{"seq":1}', b'{"seq":2}', b'{"seq":3}'])

    def test_skips_blank_lines(self) -> None:
        from story_automator.core.audit import _iter_record_lines

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.jsonl"
            p.write_text('{"seq":1}\n\n{"seq":2}\n\n', encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
