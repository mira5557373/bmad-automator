"""Tests for the bauto-shaped result.json emitter (M40).

The bauto variant extends the local v1 schema with two additional
top-level keys: ``task_id`` and ``phase``. This mirrors the
``bmad-story-automator-go`` reference shape so a downstream consumer
can route a single ``result.json`` across both producers.

The local v1 emitter (``make_session_result`` / ``write_result_json``)
is unchanged — these helpers live alongside it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.result_json import (
    BAUTO_API_VERSION,
    RESULT_JSON_API_VERSION,
    ResultJsonError,
    emit_bauto_result,
    is_bauto_result,
    make_session_result,
    read_bauto_result,
    write_bauto_result,
)


class EmitBautoResultTests(unittest.TestCase):
    def test_minimal_payload_has_bauto_keys(self) -> None:
        p = emit_bauto_result(
            commit_sha="a" * 40,
            files_changed=["x.py"],
            summary="did x",
        )
        # The bauto shape mirrors v1 but adds task_id + phase.
        self.assertEqual(p["api_version"], BAUTO_API_VERSION)
        self.assertEqual(p["claims"]["files_changed"], ["x.py"])
        self.assertEqual(p["escalations"], [])
        self.assertEqual(p["spec_file"], "")
        self.assertEqual(p["task_id"], "")
        self.assertEqual(p["phase"], "")

    def test_full_payload_round_trips_task_id_and_phase(self) -> None:
        p = emit_bauto_result(
            commit_sha="b" * 40,
            files_changed=["a.py", "b.py"],
            summary="s",
            spec_file="specs/foo.md",
            escalations=[{"severity": "CRITICAL", "reason": "x"}],
            task_id="T-123",
            phase="phase-2",
        )
        self.assertEqual(p["task_id"], "T-123")
        self.assertEqual(p["phase"], "phase-2")
        self.assertEqual(p["spec_file"], "specs/foo.md")
        self.assertEqual(len(p["escalations"]), 1)

    def test_payload_is_serializable_deterministically(self) -> None:
        p1 = emit_bauto_result(
            commit_sha="c" * 40,
            files_changed=["x"],
            summary="s",
            task_id="T",
            phase="p",
        )
        p2 = emit_bauto_result(
            commit_sha="c" * 40,
            files_changed=["x"],
            summary="s",
            task_id="T",
            phase="p",
        )
        self.assertEqual(
            json.dumps(p1, sort_keys=True),
            json.dumps(p2, sort_keys=True),
        )

    def test_emit_rejects_bad_escalation_severity(self) -> None:
        # Inherits the same escalation validation as v1.
        with self.assertRaises(ResultJsonError):
            emit_bauto_result(
                commit_sha="d" * 40,
                files_changed=[],
                summary="s",
                escalations=[{"severity": "BOGUS", "reason": "x"}],
            )

    def test_emit_rejects_non_string_task_id(self) -> None:
        with self.assertRaises(ResultJsonError):
            emit_bauto_result(
                commit_sha="e" * 40,
                files_changed=[],
                summary="s",
                task_id=123,  # type: ignore[arg-type]
            )

    def test_emit_rejects_non_string_phase(self) -> None:
        with self.assertRaises(ResultJsonError):
            emit_bauto_result(
                commit_sha="f" * 40,
                files_changed=[],
                summary="s",
                phase=42,  # type: ignore[arg-type]
            )


class WriteReadBautoResultTests(unittest.TestCase):
    def test_round_trip_disk(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out" / "result.json"
            payload = emit_bauto_result(
                commit_sha="9" * 40,
                files_changed=["m.py"],
                summary="round trip",
                spec_file="specs/r.md",
                task_id="T-RT",
                phase="impl",
            )
            written = write_bauto_result(target, payload)
            self.assertEqual(written, target)
            self.assertTrue(target.exists())

            on_disk = read_bauto_result(target)
            self.assertEqual(on_disk, payload)

    def test_read_rejects_truncated_payload_missing_task_id(self) -> None:
        # A bauto reader must NOT silently accept a v1-shaped file —
        # the schemas are distinguishable on purpose.
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "result.json"
            # Hand-craft a v1 (no task_id, no phase) payload.
            v1_like = make_session_result(
                commit_sha="0" * 40,
                files_changed=[],
                summary="s",
            )
            target.write_text(
                json.dumps(v1_like, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ResultJsonError):
                read_bauto_result(target)

    def test_write_rejects_payload_with_unknown_extra_key(self) -> None:
        # Strict fail-closed: extra keys are never tolerated.
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "result.json"
            payload = emit_bauto_result(
                commit_sha="1" * 40,
                files_changed=[],
                summary="s",
            )
            payload["surprise"] = "no"
            with self.assertRaises(ResultJsonError):
                write_bauto_result(target, payload)


class IsBautoResultTests(unittest.TestCase):
    def test_detects_bauto_via_task_id_and_phase_presence(self) -> None:
        bauto = emit_bauto_result(
            commit_sha="2" * 40,
            files_changed=[],
            summary="s",
        )
        self.assertTrue(is_bauto_result(bauto))

    def test_v1_payload_is_not_bauto(self) -> None:
        v1 = make_session_result(
            commit_sha="3" * 40,
            files_changed=[],
            summary="s",
        )
        self.assertFalse(is_bauto_result(v1))

    def test_handles_none_and_non_dict_gracefully(self) -> None:
        self.assertFalse(is_bauto_result(None))
        self.assertFalse(is_bauto_result("not a dict"))
        self.assertFalse(is_bauto_result(["nope"]))

    def test_detects_partial_presence_as_non_bauto(self) -> None:
        # Only task_id, missing phase → not a complete bauto shape.
        partial = {
            "api_version": BAUTO_API_VERSION,
            "claims": {
                "commit_sha": "4" * 40,
                "files_changed": [],
                "summary": "s",
            },
            "escalations": [],
            "spec_file": "",
            "task_id": "T-1",
        }
        self.assertFalse(is_bauto_result(partial))


class V1CoexistenceTests(unittest.TestCase):
    def test_v1_version_constant_unchanged(self) -> None:
        # Sanity: the bauto landing must not shift the v1 constant.
        self.assertEqual(RESULT_JSON_API_VERSION, 1)

    def test_bauto_version_constant_is_independent(self) -> None:
        # They can both equal 1 today, but they're independent
        # symbols so future bumps don't collide.
        self.assertEqual(BAUTO_API_VERSION, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
