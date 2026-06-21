from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core import tea_emit
from story_automator.core.tea_emit import (
    VALID_CATEGORY_VERDICTS,
    VALID_VERDICTS,
    write_gate_decision,
    write_trace_summary,
)


class TeaEmitConstantsTests(unittest.TestCase):
    def test_valid_verdicts_membership(self) -> None:
        self.assertEqual(VALID_VERDICTS, frozenset({"PASS", "CONCERNS", "FAIL", "WAIVED"}))

    def test_valid_category_verdicts_membership(self) -> None:
        self.assertEqual(
            VALID_CATEGORY_VERDICTS,
            frozenset({"PASS", "CONCERNS", "FAIL", "NA"}),
        )

    def test_valid_verdicts_is_frozenset(self) -> None:
        self.assertIsInstance(VALID_VERDICTS, frozenset)
        self.assertIsInstance(VALID_CATEGORY_VERDICTS, frozenset)


class WriteTraceSummaryTests(unittest.TestCase):
    def test_writes_canonical_json_with_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            requirements = [
                {"id": "R-2", "covered": True, "level": "unit"},
                {"id": "R-1", "covered": False, "level": "integration"},
            ]
            coverage_by_level = {"unit": 1, "integration": 0}
            result = write_trace_summary(
                path,
                story_key="epic-1.story-2",
                requirements=requirements,
                coverage_by_level=coverage_by_level,
            )
            self.assertEqual(Path(result), path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")
            self.assertEqual(payload["story_key"], "epic-1.story-2")
            self.assertEqual(payload["requirements"], requirements)
            self.assertEqual(payload["coverage_by_level"], coverage_by_level)

    def test_writes_sorted_keys_for_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            write_trace_summary(
                path,
                story_key="epic-1.story-1",
                requirements=[],
                coverage_by_level={},
            )
            raw = path.read_text(encoding="utf-8")
            keys_in_order = [line.split('"')[1] for line in raw.splitlines() if line.strip().startswith('"')]
            # Top-level keys should come out alphabetically sorted (json sort_keys=True).
            top_level = ["coverage_by_level", "requirements", "schema_version", "story_key"]
            self.assertEqual(
                [k for k in keys_in_order if k in top_level],
                top_level,
            )

    def test_accepts_custom_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            write_trace_summary(
                path,
                story_key="epic-1.story-1",
                requirements=[],
                coverage_by_level={},
                schema_version="0.2.0",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.2.0")

    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "trace.json"
            write_trace_summary(
                path,
                story_key="epic-1.story-1",
                requirements=[],
                coverage_by_level={},
            )
            self.assertTrue(path.exists())


class WriteGateDecisionTests(unittest.TestCase):
    def test_writes_canonical_json_with_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            categories = {"correctness": "PASS", "security": "CONCERNS"}
            result = write_gate_decision(
                path,
                story_key="epic-2.story-3",
                verdict="CONCERNS",
                categories=categories,
                commit_sha="abc1234",
            )
            self.assertEqual(Path(result), path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.1.0")
            self.assertEqual(payload["story_key"], "epic-2.story-3")
            self.assertEqual(payload["verdict"], "CONCERNS")
            self.assertEqual(payload["categories"], categories)
            self.assertEqual(payload["commit_sha"], "abc1234")

    def test_rejects_invalid_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            with self.assertRaises(ValueError):
                write_gate_decision(
                    path,
                    story_key="epic-1.story-1",
                    verdict="MAYBE",
                    categories={},
                    commit_sha="deadbeef",
                )

    def test_accepts_all_valid_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for verdict in ("PASS", "CONCERNS", "FAIL", "WAIVED"):
                path = Path(tmp) / f"gate_{verdict}.json"
                write_gate_decision(
                    path,
                    story_key="epic-1.story-1",
                    verdict=verdict,
                    categories={},
                    commit_sha="abc1234",
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["verdict"], verdict)

    def test_rejects_invalid_category_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            with self.assertRaises(ValueError):
                write_gate_decision(
                    path,
                    story_key="epic-1.story-1",
                    verdict="PASS",
                    categories={"correctness": "BOGUS"},
                    commit_sha="abc1234",
                )

    def test_accepts_na_category_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            write_gate_decision(
                path,
                story_key="epic-1.story-1",
                verdict="PASS",
                categories={"compliance": "NA"},
                commit_sha="abc1234",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["categories"]["compliance"], "NA")

    def test_accepts_custom_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            write_gate_decision(
                path,
                story_key="epic-1.story-1",
                verdict="PASS",
                categories={},
                commit_sha="abc1234",
                schema_version="0.3.0",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "0.3.0")

    def test_determinism_repeat_emit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "gate_a.json"
            path_b = Path(tmp) / "gate_b.json"
            payload_args = dict(
                story_key="epic-9.story-1",
                verdict="FAIL",
                categories={"correctness": "FAIL", "security": "PASS"},
                commit_sha="cafef00d",
            )
            write_gate_decision(path_a, **payload_args)
            write_gate_decision(path_b, **payload_args)
            self.assertEqual(
                path_a.read_text(encoding="utf-8"),
                path_b.read_text(encoding="utf-8"),
            )

    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "gate.json"
            write_gate_decision(
                path,
                story_key="epic-1.story-1",
                verdict="PASS",
                categories={},
                commit_sha="abc1234",
            )
            self.assertTrue(path.exists())


class ModuleExportTests(unittest.TestCase):
    def test_module_exports_public_api(self) -> None:
        self.assertTrue(hasattr(tea_emit, "write_trace_summary"))
        self.assertTrue(hasattr(tea_emit, "write_gate_decision"))
        self.assertTrue(hasattr(tea_emit, "VALID_VERDICTS"))
        self.assertTrue(hasattr(tea_emit, "VALID_CATEGORY_VERDICTS"))


if __name__ == "__main__":
    unittest.main()
