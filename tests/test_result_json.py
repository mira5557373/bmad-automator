"""Tests for the result.json schema (Phase 2)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.result_json import (
    RESULT_JSON_API_VERSION,
    ResultJsonApiVersionError,
    ResultJsonError,
    critical_escalations,
    make_session_result,
    preference_escalations,
    read_result_json,
    validate_result_json,
    write_result_json,
)


class MakeSessionResultTests(unittest.TestCase):
    def test_minimal_payload(self) -> None:
        p = make_session_result(
            commit_sha="abc1234567" * 4,
            files_changed=["a.py"],
            summary="did a thing",
        )
        self.assertEqual(p["api_version"], RESULT_JSON_API_VERSION)
        self.assertEqual(p["claims"]["files_changed"], ["a.py"])
        self.assertEqual(p["escalations"], [])
        self.assertEqual(p["spec_file"], "")

    def test_with_escalations(self) -> None:
        p = make_session_result(
            commit_sha="x" * 40,
            files_changed=[],
            summary="x",
            spec_file="specs/s.md",
            escalations=[
                {"severity": "CRITICAL", "reason": "data loss"},
                {"severity": "PREFERENCE", "reason": "style"},
            ],
        )
        self.assertEqual(len(p["escalations"]), 2)

    def test_deterministic_alpha_key_order_after_json(self) -> None:
        # The payload itself is dict-ordered, but when serialized
        # with sort_keys it is byte-deterministic.
        p1 = make_session_result(
            commit_sha="a" * 40, files_changed=["x"], summary="s",
        )
        p2 = make_session_result(
            commit_sha="a" * 40, files_changed=["x"], summary="s",
        )
        self.assertEqual(
            json.dumps(p1, sort_keys=True),
            json.dumps(p2, sort_keys=True),
        )

    def test_invalid_payload_raises_on_build(self) -> None:
        # The builder validates — passing a malformed escalation
        # bubbles up immediately, not at write time.
        with self.assertRaises(ResultJsonError):
            make_session_result(
                commit_sha="x" * 40, files_changed=[], summary="s",
                escalations=[{"severity": "INVALID", "reason": "x"}],
            )


class ValidateResultJsonTests(unittest.TestCase):
    def _valid(self) -> dict:
        return {
            "api_version": RESULT_JSON_API_VERSION,
            "claims": {
                "commit_sha": "a" * 40,
                "files_changed": [],
                "summary": "s",
            },
            "escalations": [],
            "spec_file": "",
        }

    def test_accepts_well_formed(self) -> None:
        validate_result_json(self._valid())  # does not raise

    def test_top_level_must_be_object(self) -> None:
        with self.assertRaises(ResultJsonError):
            validate_result_json([1, 2])  # type: ignore[arg-type]

    def test_missing_required_key(self) -> None:
        bad = self._valid()
        del bad["spec_file"]
        with self.assertRaises(ResultJsonError) as ctx:
            validate_result_json(bad)
        self.assertIn("spec_file", str(ctx.exception))

    def test_unknown_top_level_key_rejected(self) -> None:
        bad = self._valid()
        bad["mystery"] = "x"
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_api_version_mismatch_subclass(self) -> None:
        bad = self._valid()
        bad["api_version"] = 99
        with self.assertRaises(ResultJsonApiVersionError):
            validate_result_json(bad)

    def test_api_version_must_be_int(self) -> None:
        bad = self._valid()
        bad["api_version"] = "1"
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_claims_must_be_object(self) -> None:
        bad = self._valid()
        bad["claims"] = []
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_claims_files_changed_must_be_list_of_str(self) -> None:
        bad = self._valid()
        bad["claims"]["files_changed"] = [1, 2]
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_claims_extra_keys_rejected(self) -> None:
        bad = self._valid()
        bad["claims"]["extra"] = "x"
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_escalation_unknown_severity_rejected(self) -> None:
        bad = self._valid()
        bad["escalations"] = [{"severity": "URGENT", "reason": "x"}]
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_escalation_extra_field_rejected(self) -> None:
        bad = self._valid()
        bad["escalations"] = [
            {"severity": "CRITICAL", "reason": "x", "extra": "y"}
        ]
        with self.assertRaises(ResultJsonError):
            validate_result_json(bad)

    def test_escalations_default_to_empty_list_when_omitted(self) -> None:
        bad = self._valid()
        del bad["escalations"]
        # escalations is optional — this should NOT raise.
        validate_result_json(bad)


class IOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-result-")
        self.path = Path(self.tmpdir) / "result.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_then_read_roundtrip(self) -> None:
        payload = make_session_result(
            commit_sha="b" * 40, files_changed=["x"], summary="ok",
            escalations=[{"severity": "PREFERENCE", "reason": "y"}],
        )
        write_result_json(self.path, payload)
        loaded = read_result_json(self.path)
        self.assertEqual(loaded, payload)

    def test_write_creates_parent_dirs(self) -> None:
        nested = Path(self.tmpdir) / "a" / "b" / "result.json"
        payload = make_session_result(
            commit_sha="c" * 40, files_changed=[], summary="s",
        )
        write_result_json(nested, payload)
        self.assertTrue(nested.exists())

    def test_write_rejects_invalid_payload(self) -> None:
        bad = {"api_version": 1}
        with self.assertRaises(ResultJsonError):
            write_result_json(self.path, bad)
        # And nothing landed on disk.
        self.assertFalse(self.path.exists())

    def test_read_validates_on_load(self) -> None:
        self.path.write_text(json.dumps({"api_version": 1}))
        with self.assertRaises(ResultJsonError):
            read_result_json(self.path)

    def test_read_propagates_jsondecodeerror(self) -> None:
        self.path.write_text("{not json}")
        with self.assertRaises(json.JSONDecodeError):
            read_result_json(self.path)

    def test_read_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_result_json(self.path)

    def test_wire_form_is_deterministic_bytes(self) -> None:
        payload = make_session_result(
            commit_sha="d" * 40, files_changed=["a", "b"], summary="x",
        )
        write_result_json(self.path, payload)
        first = self.path.read_bytes()
        # Re-write the same payload; bytes must be identical.
        write_result_json(self.path, payload)
        second = self.path.read_bytes()
        self.assertEqual(first, second)


class EscalationHelpersTests(unittest.TestCase):
    def test_critical_filter(self) -> None:
        p = make_session_result(
            commit_sha="x" * 40, files_changed=[], summary="x",
            escalations=[
                {"severity": "CRITICAL", "reason": "a"},
                {"severity": "PREFERENCE", "reason": "b"},
                {"severity": "CRITICAL", "reason": "c"},
            ],
        )
        crits = critical_escalations(p)
        self.assertEqual(len(crits), 2)
        self.assertTrue(all(e["severity"] == "CRITICAL" for e in crits))

    def test_preference_filter(self) -> None:
        p = make_session_result(
            commit_sha="x" * 40, files_changed=[], summary="x",
            escalations=[
                {"severity": "PREFERENCE", "reason": "a"},
                {"severity": "CRITICAL", "reason": "b"},
            ],
        )
        prefs = preference_escalations(p)
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["reason"], "a")

    def test_none_payload(self) -> None:
        self.assertEqual(critical_escalations(None), [])
        self.assertEqual(preference_escalations(None), [])

    def test_payload_without_escalations_key(self) -> None:
        self.assertEqual(critical_escalations({}), [])
        self.assertEqual(preference_escalations({}), [])


if __name__ == "__main__":
    unittest.main()
