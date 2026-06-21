"""Tests for ``run_production_gate(fail_closed=True)`` (Phase 2).

Pins:
 - default-off: a gate with error evidence still gets the verdict_engine's
   verdict (back-compat).
 - on + error evidence present: ``overall`` is forced to FAIL and the gate
   file carries ``fail_closed_triggered=True`` plus a sorted
   ``fail_closed_categories`` list.
 - on + no error evidence: original verdict is preserved (no false-trigger).
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record


def _minimal_profile() -> dict:
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


class FailClosedDefaultOffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-fc-off-")
        self.project_root = Path(self.tmpdir)
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_off_does_not_inject_keys(self, mock_run) -> None:
        record = make_evidence_record(
            collector="boom", tool="t", category="correctness",
            status="error", findings=["crash"],
        )
        persist_evidence_record(self.project_root, "g-off", record)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-off",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            # fail_closed defaults False
        )
        self.assertNotIn("fail_closed_triggered", gate)
        self.assertNotIn("fail_closed_categories", gate)


class FailClosedEnabledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-fc-on-")
        self.project_root = Path(self.tmpdir)
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_error_evidence_forces_fail(self, mock_run) -> None:
        # Two error evidences in different (category, collector) pairs +
        # one ok evidence in another category — the override should
        # surface both error labels, sorted, and NOT report the ok one.
        records = [
            make_evidence_record(
                collector="boom", tool="t", category="correctness",
                status="error", findings=["x"],
            ),
            make_evidence_record(
                collector="kaboom", tool="t", category="security",
                status="error", findings=["y"],
            ),
            make_evidence_record(
                collector="ok", tool="t", category="static",
                status="ok",
                metrics={"coverage_pct": 95, "regressions": 0},
            ),
        ]
        for r in records:
            persist_evidence_record(self.project_root, "g-on", r)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-on",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        self.assertEqual(gate["overall"], "FAIL")
        self.assertTrue(gate["fail_closed_triggered"])
        self.assertEqual(
            gate["fail_closed_categories"],
            ["correctness/boom", "security/kaboom"],
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_no_error_evidence_does_not_trigger(self, mock_run) -> None:
        record = make_evidence_record(
            collector="ok", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )
        persist_evidence_record(self.project_root, "g-clean", record)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-clean",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        self.assertEqual(gate["overall"], "PASS")
        self.assertNotIn("fail_closed_triggered", gate)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_already_fail_marker_still_emitted(self, mock_run) -> None:
        # A FAIL verdict from the engine + error evidence: fail_closed
        # was a factor, so the audit markers MUST be emitted even though
        # the override didn't change the final overall verdict. This is
        # the operator-facing record that fail_closed contributed.
        records = [
            make_evidence_record(
                collector="boom", tool="t", category="correctness",
                status="error", findings=["x"],
            ),
        ]
        for r in records:
            persist_evidence_record(self.project_root, "g-double", r)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-double",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        self.assertEqual(gate["overall"], "FAIL")
        self.assertTrue(gate["fail_closed_triggered"])
        self.assertEqual(
            gate["fail_closed_categories"], ["correctness/boom"],
        )


if __name__ == "__main__":
    unittest.main()
