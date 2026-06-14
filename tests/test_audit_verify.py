from __future__ import annotations

import json
import re as _re
import shutil as _shutil
import subprocess as _subprocess
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
                "seq": 3,
                "ts": "2026-06-14T00:00:00Z",
                "event": "E",
                "payload": {},
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
                "seq": 2,
                "ts": "t",
                "event": "E",
                "tag": "0" * 64,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(broken) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))


class VerifyNonUtf8BytesTests(unittest.TestCase):
    KEY = b"\xaf" * 32

    def test_invalid_utf8_first_line_returns_false_zero(self) -> None:
        # Tampered logs can contain arbitrary binary. REQ-08 treats a non-
        # decodable line as "malformed JSON" and must return
        # (False, last_valid_seq) — never propagate UnicodeDecodeError.
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            p.write_bytes(b"\xff\xfe\xfd\xfc not utf-8 at all\n")
            self.assertEqual(AuditLog(path=p, key=self.KEY).verify(), (False, 0))

    def test_invalid_utf8_after_valid_records_returns_false_at_previous(
        self,
    ) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            log.append(_FakeEvent("E", {"i": 1}))
            with p.open("ab") as handle:
                # A continuation byte with no leading byte is invalid UTF-8.
                handle.write(b"\xc3\x28\n")
            self.assertEqual(log.verify(), (False, 2))


class VerifyMalformedTagTests(unittest.TestCase):
    KEY = b"\xab" * 32

    def test_non_string_tag_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            # Append a record whose tag is an int (not a string). REQ-08
            # requires this to return (False, last_valid_seq) — not raise.
            bad = {
                "seq": 2,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": 12345,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(bad) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))

    def test_null_tag_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            bad = {
                "seq": 2,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": None,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(bad) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))

    def test_wrong_length_tag_returns_false_at_previous(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.append(_FakeEvent("E", {"i": 0}))
            bad = {
                "seq": 2,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": "f",  # not 64 hex chars
            }
            with p.open("ab") as handle:
                handle.write((compact_json(bad) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))


class VerifyBoolSeqRejectedTests(unittest.TestCase):
    KEY = b"\xac" * 32

    def test_first_record_seq_true_returns_false_zero(self) -> None:
        # bool is a subclass of int in Python; `seq=True` would coincidentally
        # equal 1 but is a type confusion bug that verify must catch.
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            rec = {
                "seq": True,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": "0" * 64,
            }
            p.write_bytes((compact_json(rec) + "\n").encode("utf-8"))
            self.assertEqual(AuditLog(path=p, key=self.KEY).verify(), (False, 0))


class VerifyNonContiguousSeqTests(unittest.TestCase):
    KEY = b"\xcc" * 32

    def test_first_record_with_seq_not_one_returns_false_zero(self) -> None:
        from story_automator.core.audit import AuditLog
        from story_automator.core.common import compact_json

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            # Hand-craft a record whose seq is 2 but file is otherwise empty.
            rec = {
                "seq": 2,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": "0" * 64,
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
                "seq": 4,
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": "0" * 64,
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
                "seq": "two",
                "ts": "t",
                "event": "E",
                "payload": {},
                "tag": "0" * 64,
            }
            with p.open("ab") as handle:
                handle.write((compact_json(bad) + "\n").encode("utf-8"))
            self.assertEqual(log.verify(), (False, 1))


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
                last_seq,
                100,
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
                for line in p.read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertEqual(set(labels), {"a", "b"})


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
                forbidden,
                source,
                f"verify() must stream — {forbidden} loads the whole file",
            )

    def test_verify_uses_iter_record_lines(self) -> None:
        # Verify must dispatch to our streaming generator helper.
        import inspect
        from story_automator.core.audit import AuditLog

        source = inspect.getsource(AuditLog.verify)
        self.assertIn(
            "_iter_record_lines",
            source,
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
                peak,
                1_048_576,
                f"verify() peaked at {peak} bytes — expected <1 MiB streaming",
            )


class AuditModuleSizeBudgetM3Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
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

        # Re-entrancy guard: the subprocess below runs `unittest discover -p
        # test_audit*.py`, which would re-pick this very test and recurse.
        # When invoked under the gate we sentinel-skip ourselves.
        if _os.environ.get("BMAD_AUDIT_COVERAGE_GATE_RUNNING") == "1":
            self.skipTest("re-entrant invocation under coverage gate")

        src_root = self.REPO_ROOT / "skills" / "bmad-story-automator" / "src"
        audit_dir = src_root / "story_automator" / "core"

        env = dict(_os.environ)
        env["PYTHONPATH"] = str(src_root) + _os.pathsep + env.get("PYTHONPATH", "")
        env["BMAD_AUDIT_COVERAGE_GATE_RUNNING"] = "1"

        # Use a private coverage data file so parallel runs and the
        # external CI gate don't fight over .coverage.
        data_file = str(self.REPO_ROOT / ".coverage.m3-gate")
        env["COVERAGE_FILE"] = data_file

        run = _subprocess.run(
            [
                coverage_exe,
                "run",
                f"--source={audit_dir}",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(self.REPO_ROOT / "tests"),
                "-p",
                "test_audit*.py",
            ],
            cwd=str(self.REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            run.returncode,
            0,
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
            report.returncode,
            0,
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
            percent,
            85,
            f"audit.py coverage = {percent}% (gate: 85%)\n{report.stdout}",
        )


if __name__ == "__main__":
    unittest.main()
