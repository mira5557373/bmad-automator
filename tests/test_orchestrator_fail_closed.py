"""Tests for ``run_production_gate(fail_closed=True)`` (Phase 2).

Pins:
 - default-off: a gate with error evidence still gets the verdict_engine's
   verdict (back-compat).
 - on + error evidence present: ``overall`` is forced to FAIL and the gate
   file carries ``fail_closed_triggered=True`` plus a sorted
   ``fail_closed_categories`` list.
 - on + no error evidence: original verdict is preserved (no false-trigger).
 - reuse path: the override applies to cache hits too (regression for the
   bug where fresh vs reused diverged on identical inputs).
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import (
    persist_evidence_record,
    persist_gate_file,
)
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import (
    make_evidence_record,
    make_gate_file,
    make_timeout_evidence,
)
from story_automator.core.product_profile import compute_profile_hash


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


class FailClosedReusePathTests(unittest.TestCase):
    """Regression: ``fail_closed`` must apply on cache hits too.

    Without the fix, the reuse short-circuit at
    ``gate_orchestrator.py`` returned the on-disk gate dict without
    running the fail_closed override block. Same (gate_id, commit,
    profile, factory_version) + same fail_closed=True + same on-disk
    error evidence yielded ``overall='PASS'`` on the reuse path but
    ``overall='FAIL'`` on the fresh path — a direct contradiction of
    the docstring contract ("forces overall=FAIL regardless of the
    verdict_engine's decision"). The cache-hit fail-open let
    error-status evidence slip into a commit via ``route_gate_verdict``
    when the operator had explicitly turned on the safety net.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-fc-reuse-")
        self.project_root = Path(self.tmpdir)
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_reuse_path_applies_fail_closed_override(self, mock_run) -> None:
        # Pre-persist a PASS gate_file matching the call's (commit,
        # profile_hash, factory_version) so ``check_gate_reuse``
        # returns True. Also persist an error-status evidence record
        # for the same gate_id — an out-of-band corruption scenario
        # that the on-disk fail_closed safety net is designed to
        # catch even when the operator has not re-evaluated.
        profile_hash = compute_profile_hash(self.profile)
        cached = make_gate_file(
            gate_id="g-reuse-fc",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"name": "test", "hash": profile_hash},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "evidence": []}},
            overall="PASS",
        )
        persist_gate_file(self.project_root, cached)
        record = make_evidence_record(
            collector="boom", tool="t", category="correctness",
            status="error", findings=["x"],
        )
        persist_evidence_record(self.project_root, "g-reuse-fc", record)
        mock_run.return_value = []

        result = run_production_gate(
            self.project_root, "g-reuse-fc",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        # Reuse-hit confirmed by overall starting at PASS on disk;
        # without the override the result would also be PASS. With
        # the fix the override forces FAIL and emits the audit marks.
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result.get("fail_closed_triggered"))
        self.assertEqual(
            result.get("fail_closed_categories"), ["correctness/boom"],
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_reuse_path_fail_closed_off_preserves_cached_verdict(
        self, mock_run,
    ) -> None:
        # When fail_closed is the (default) False, the reuse path
        # must NOT inject the audit fields — preserves byte-identical
        # back-compat for every existing call site.
        profile_hash = compute_profile_hash(self.profile)
        cached = make_gate_file(
            gate_id="g-reuse-noop",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"name": "test", "hash": profile_hash},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "evidence": []}},
            overall="PASS",
        )
        persist_gate_file(self.project_root, cached)
        record = make_evidence_record(
            collector="boom", tool="t", category="correctness",
            status="error", findings=["x"],
        )
        persist_evidence_record(self.project_root, "g-reuse-noop", record)
        mock_run.return_value = []

        result = run_production_gate(
            self.project_root, "g-reuse-noop",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            # fail_closed defaults False
        )
        self.assertEqual(result["overall"], "PASS")
        self.assertNotIn("fail_closed_triggered", result)
        self.assertNotIn("fail_closed_categories", result)


class FailClosedTimeoutEvidenceTests(unittest.TestCase):
    """Regression: ``fail_closed`` must catch ``status="timeout"`` too.

    Before the fix, ``_collect_error_evidence`` only matched
    ``record.get("status") == "error"``, but
    :func:`gate_schema.make_timeout_evidence` stamps
    ``status="timeout"`` (a distinct value in
    ``VALID_EVIDENCE_STATUSES``). The docstring at
    ``gate_orchestrator.py`` explicitly promises timeouts ARE caught
    ("status='error' is what the collector_runner stamps on a crashed
    collector and what timeouts produce" — false: timeouts produce
    ``status="timeout"``). The result was that a timeout-only gate
    silently lost the operator-facing audit trail
    (``fail_closed_triggered`` + ``fail_closed_categories``), even
    though ``category_rules`` still incidentally drove the verdict to
    FAIL via defense-in-depth. This test pins the docstring contract
    end-to-end on the fresh path.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-fc-timeout-")
        self.project_root = Path(self.tmpdir)
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_timeout_only_evidence_triggers_fail_closed_audit(
        self, mock_run,
    ) -> None:
        # Persist ONLY a status="timeout" record — no status="error" at
        # all. Pre-fix this returned no labels from
        # _collect_error_evidence, so the gate file silently lacked
        # fail_closed_triggered/fail_closed_categories.
        record = make_timeout_evidence(
            collector="slowpoke", tool="ruff",
            category="correctness", timeout_s=60,
        )
        persist_evidence_record(self.project_root, "g-timeout", record)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-timeout",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        self.assertEqual(gate["overall"], "FAIL")
        self.assertTrue(gate.get("fail_closed_triggered"))
        self.assertEqual(
            gate.get("fail_closed_categories"),
            ["correctness/slowpoke"],
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_mixed_error_and_timeout_evidence_both_in_categories(
        self, mock_run,
    ) -> None:
        # Mix one error + one timeout in different (category, collector)
        # pairs — both must appear sorted in fail_closed_categories.
        records = [
            make_evidence_record(
                collector="boom", tool="t", category="correctness",
                status="error", findings=["x"],
            ),
            make_timeout_evidence(
                collector="slowpoke", tool="t",
                category="security", timeout_s=60,
            ),
        ]
        for r in records:
            persist_evidence_record(self.project_root, "g-mixed", r)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "g-mixed",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            fail_closed=True,
        )
        self.assertEqual(gate["overall"], "FAIL")
        self.assertTrue(gate.get("fail_closed_triggered"))
        self.assertEqual(
            gate.get("fail_closed_categories"),
            ["correctness/boom", "security/slowpoke"],
        )


if __name__ == "__main__":
    unittest.main()
