from __future__ import annotations

import json
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
        original = line[pos : pos + 1]
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


if __name__ == "__main__":
    unittest.main()
