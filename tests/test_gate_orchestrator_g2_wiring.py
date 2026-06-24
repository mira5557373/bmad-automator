"""G2 wiring tests for ``run_production_gate`` + ``_run_collectors``.

Covers AC-G-01..G-09 from the rev-2 design spec:
- Default kwargs preserve byte-identical lifecycle behavior.
- ``isolation_mode="per_unit"`` flows through to ``run_gate_collectors``.
- Invalid kwargs raise BEFORE ``assert_host_context`` AND BEFORE the
  gate-lock acquisition (no marker written).
- Gate-lock semantics are preserved across per-unit dispatch.
- ``isolation_mode="per_unit"`` composes with every existing kwarg.
- ``_run_collectors`` wrapper forwards the new kwargs.
- KeyboardInterrupt mid-gate still clears the marker.

The system_gate sibling parity (AC-G-08) lives in test_system_gate.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import (
    _run_collectors,
    run_production_gate,
)
from story_automator.core.gate_schema import make_evidence_record


def _minimal_profile() -> dict:
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


class _MarkerFreeMixin:
    """Provide ``self.project_root`` + helpers for marker assertions."""

    def setUp(self) -> None:  # type: ignore[override]
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.profile = _minimal_profile()
        self.registry = CollectorRegistry()
        (self.project_root / "_bmad" / "gate").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:  # type: ignore[override]
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _marker_path(self) -> Path:
        return self.project_root / "_bmad" / "gate" / "gate-in-progress.json"

    def _persist_ok_evidence(self, gate_id: str) -> None:
        record = make_evidence_record(
            collector="c",
            tool="t",
            category="correctness",
            status="ok",
            metrics={"coverage_pct": 95, "regressions": 0},
        )
        persist_evidence_record(self.project_root, gate_id, record)


class RunProductionGateValidationTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-04: validation BEFORE assert_host_context AND BEFORE gate-lock.

    No marker is written, no host context check is reached.
    """

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.assert_host_context")
    def test_invalid_isolation_mode_raises_value_error_before_host_check(
        self,
        mock_host: MagicMock,
    ) -> None:
        with self.assertRaises(ValueError):
            run_production_gate(
                self.project_root,
                "gate-bad-mode",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                isolation_mode="invalid",
            )
        mock_host.assert_not_called()
        self.assertFalse(self._marker_path().exists())

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.assert_host_context")
    def test_invalid_max_workers_str_raises_type_error_before_host_check(
        self,
        mock_host: MagicMock,
    ) -> None:
        with self.assertRaises(TypeError):
            run_production_gate(
                self.project_root,
                "gate-bad-mw",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                max_workers="four",  # type: ignore[arg-type]
            )
        mock_host.assert_not_called()
        self.assertFalse(self._marker_path().exists())

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.assert_host_context")
    def test_invalid_max_workers_bool_raises_type_error(
        self,
        mock_host: MagicMock,
    ) -> None:
        # bool is a subclass of int but must be rejected.
        with self.assertRaises(TypeError):
            run_production_gate(
                self.project_root,
                "gate-bad-bool",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                max_workers=True,  # type: ignore[arg-type]
            )
        mock_host.assert_not_called()
        self.assertFalse(self._marker_path().exists())

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.assert_host_context")
    def test_validation_runs_before_gate_lock_acquisition(
        self,
        mock_host: MagicMock,
    ) -> None:
        # If the gate lock had been acquired, a sibling FileLock attempt
        # would observe the .gate.lock file. The validation error should
        # arrive before any lock activity.
        with patch(
            "story_automator.core.gate_orchestrator.get_gate_lock",
        ) as mock_lock:
            with self.assertRaises(ValueError):
                run_production_gate(
                    self.project_root,
                    "gate-no-lock",
                    commit_sha="abc",
                    target={"kind": "story", "id": "s1"},
                    profile=self.profile,
                    factory_version="1.0.0",
                    registry=self.registry,
                    isolation_mode="bogus",
                )
            mock_lock.assert_not_called()
        mock_host.assert_not_called()


class RunProductionGateDefaultTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-01: default kwargs preserve byte-identical behavior."""

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_isolation_mode_is_shared(
        self,
        mock_run: MagicMock,
    ) -> None:
        self._persist_ok_evidence("gate-default")
        mock_run.return_value = []
        run_production_gate(
            self.project_root,
            "gate-default",
            commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.0.0",
            registry=self.registry,
        )
        # _run_collectors invoked exactly once with shared defaults.
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["isolation_mode"], "shared")
        self.assertEqual(kwargs["max_workers"], 4)


class RunProductionGatePerUnitTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-02 / AC-G-06: per_unit flows through and composes."""

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_per_unit_kwargs_threaded_through(
        self,
        mock_run: MagicMock,
    ) -> None:
        self._persist_ok_evidence("gate-per-unit")
        mock_run.return_value = []
        run_production_gate(
            self.project_root,
            "gate-per-unit",
            commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.0.0",
            registry=self.registry,
            isolation_mode="per_unit",
            max_workers=2,
        )
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["isolation_mode"], "per_unit")
        self.assertEqual(kwargs["max_workers"], 2)
        # Marker cleared on success.
        self.assertFalse(self._marker_path().exists())

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_per_unit_composes_with_drift_watcher(
        self,
        mock_run: MagicMock,
    ) -> None:
        self._persist_ok_evidence("gate-compose")
        mock_run.return_value = []
        watcher = MagicMock()
        run_production_gate(
            self.project_root,
            "gate-compose",
            commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.0.0",
            registry=self.registry,
            isolation_mode="per_unit",
            max_workers=4,
            drift_watcher=watcher,
        )
        # drift_watcher polled twice per gate (pre + post evaluate).
        self.assertEqual(watcher.poll.call_count, 2)
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["isolation_mode"], "per_unit")


class RunCollectorsWrapperTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-07: ``_run_collectors`` wrapper forwards the new kwargs."""

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.run_gate_collectors")
    def test_run_collectors_forwards_isolation_kwargs(
        self,
        mock_runner: MagicMock,
    ) -> None:
        mock_runner.return_value = []
        result = _run_collectors(
            self.project_root,
            "gate-wrap",
            "abc",
            self.profile,
            self.registry,
            isolation_mode="per_unit",
            max_workers=3,
        )
        self.assertEqual(result, [])
        mock_runner.assert_called_once()
        _, kwargs = mock_runner.call_args
        self.assertEqual(kwargs["isolation_mode"], "per_unit")
        self.assertEqual(kwargs["max_workers"], 3)

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.run_gate_collectors")
    def test_run_collectors_default_is_shared(
        self,
        mock_runner: MagicMock,
    ) -> None:
        mock_runner.return_value = []
        _run_collectors(
            self.project_root,
            "gate-wrap-default",
            "abc",
            self.profile,
            self.registry,
        )
        mock_runner.assert_called_once()
        _, kwargs = mock_runner.call_args
        self.assertEqual(kwargs["isolation_mode"], "shared")
        self.assertEqual(kwargs["max_workers"], 4)


class RunProductionGateLockSemanticsTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-05 / AC-G-09: lock semantics + marker hygiene."""

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_on_per_unit_success(
        self,
        mock_run: MagicMock,
    ) -> None:
        self._persist_ok_evidence("gate-marker-ok")
        mock_run.return_value = []
        run_production_gate(
            self.project_root,
            "gate-marker-ok",
            commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.0.0",
            registry=self.registry,
            isolation_mode="per_unit",
            max_workers=2,
        )
        self.assertFalse(self._marker_path().exists())

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_when_collectors_raise(
        self,
        mock_run: MagicMock,
    ) -> None:
        # KeyboardInterrupt mid-gate during per_unit must still hit
        # the finally clear_gate_marker block.
        mock_run.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_production_gate(
                self.project_root,
                "gate-marker-ki",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                isolation_mode="per_unit",
                max_workers=2,
            )
        self.assertFalse(self._marker_path().exists())


if __name__ == "__main__":
    unittest.main()
