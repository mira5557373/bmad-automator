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

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_when_drift_watcher_poll_raises_base_exception(
        self,
        mock_run: MagicMock,
    ) -> None:
        # R3 fix regression: the C1 ``drift_watcher.poll()`` call at
        # lifecycle start MUST live inside the try whose finally
        # clears the marker. The pre-fix code wrapped poll() in
        # ``try: ... except Exception: pass`` BEFORE the try whose
        # finally clears the marker — a BaseException subclass
        # (KeyboardInterrupt / SystemExit / MemoryError) escaping
        # poll() would skip the bare except, propagate past the
        # write_gate_marker call, and skip the inner finally,
        # leaking the marker on disk. ``_recover_from_crash_locked``
        # mops it up on the next gate run, but the inner-finally
        # contract "marker MUST be cleared on every exit path after
        # it is written" was violated for the drift_watcher window.
        mock_run.return_value = []

        class _BaseExcWatcher:
            def poll(self) -> None:
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            run_production_gate(
                self.project_root,
                "gate-drift-ki",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                drift_watcher=_BaseExcWatcher(),
            )
        self.assertFalse(
            self._marker_path().exists(),
            "Marker leaked after BaseException in drift_watcher.poll()",
        )
        # Collectors never ran — the KeyboardInterrupt aborted the
        # gate inside the inner try BEFORE _run_collectors was
        # called. The finally still ran, clearing the marker.
        mock_run.assert_not_called()

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.clear_gate_marker")
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_clear_gate_marker_oserror_does_not_clobber_keyboard_interrupt(
        self,
        mock_run: MagicMock,
        mock_clear: MagicMock,
    ) -> None:
        # R2 fix #17 regression: when ``_run_collectors`` raises
        # KeyboardInterrupt AND ``clear_gate_marker`` then raises a
        # non-FileNotFoundError OSError (read-only fs, permission denied,
        # etc.) inside the inner ``finally``, the secondary OSError must
        # NOT replace the operator's SIGINT in the propagating exception.
        # The original ``except KeyboardInterrupt`` clauses (shutdown
        # handlers, signal-aware code) MUST still match. The
        # marker-not-cleared edge is acceptable — the K-5 startup janitor
        # / recover_from_crash mops up orphan markers.
        mock_run.side_effect = KeyboardInterrupt()
        mock_clear.side_effect = OSError("permission denied")
        with self.assertRaises(KeyboardInterrupt):
            run_production_gate(
                self.project_root,
                "gate-marker-oserror",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
            )
        # ``clear_gate_marker`` was called exactly once from the inner
        # finally (the OSError did not prevent invocation).
        mock_clear.assert_called_once_with(self.project_root)

    @patch.dict(os.environ, {}, clear=False)
    @patch("story_automator.core.gate_orchestrator.get_gate_lock")
    def test_lock_released_when_keyboard_interrupt_arrives_after_acquire(
        self,
        mock_get_lock: MagicMock,
    ) -> None:
        # R2 fix #25 regression: SIGINT / KeyboardInterrupt arriving in
        # the bytecode-gap between ``_gate_lock.acquire()`` returning
        # successfully and the inner try (whose ``finally:`` releases
        # the lock) being entered MUST still release the lock. The pre-
        # fix code had ``_pending_cleanup = []`` + ``_recovery_descriptor
        # = {}`` (plus the ``except Timeout`` block) sitting between the
        # acquire and the protecting try, so a KeyboardInterrupt
        # delivered in that window leaked the OS-level lock until the
        # FileLock instance was GC'd. The fix restructures so
        # ``acquire()`` is the first statement of the try whose
        # ``finally:`` releases the lock — any exception (including
        # KeyboardInterrupt arriving immediately after acquire returns)
        # is caught by that finally and the lock is released.
        #
        # We simulate the race by giving the mock lock an ``acquire()``
        # that records a successful acquire, then raises
        # KeyboardInterrupt. The fix guarantees ``release()`` runs even
        # on this exit path; the unfixed code would not.
        mock_lock = MagicMock()
        mock_lock.timeout = 3600.0
        release_calls: list[None] = []

        def fake_acquire(*args: object, **kwargs: object) -> None:
            # Simulate the sub-microsecond window: lock has been acquired
            # at the OS level, then SIGINT arrives just as control
            # returns to the caller.
            raise KeyboardInterrupt()

        mock_lock.acquire.side_effect = fake_acquire
        mock_lock.release.side_effect = lambda *a, **kw: release_calls.append(None)
        mock_get_lock.return_value = mock_lock

        with self.assertRaises(KeyboardInterrupt):
            run_production_gate(
                self.project_root,
                "gate-ki-after-acquire",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
            )

        # The release MUST have been called even though the
        # KeyboardInterrupt fired immediately after acquire returned.
        # On the unfixed code this assertion fails because the lock
        # release sits inside a try that was never entered.
        self.assertEqual(
            len(release_calls), 1,
            "_gate_lock.release() must run on every exit path from "
            "the protected region — including KeyboardInterrupt "
            "arriving immediately after acquire returns.",
        )


class RunProductionGateVerdictEquivalenceTests(_MarkerFreeMixin, unittest.TestCase):
    """AC-G-03 + AC-G-02: shared and per_unit produce IDENTICAL
    ``categories[*].verdict`` for deterministic inputs.

    Post-impl review fold-in. The spec's §7.1 AC-G-03 and §7.3 #6 pin
    verdict equivalence as the headline operational guarantee of the
    milestone: switching modes should not change the gate verdict.
    Earlier tests mock ``_run_collectors`` to a MagicMock and only
    inspect kwarg pass-through; this test injects IDENTICAL outcomes
    for both modes and asserts the resulting gate-file ``verdict`` /
    ``overall`` strings match, while explicitly confirming
    ``evidence_merkle_root`` differs (the documented mode divergence).
    """

    def _run_one_mode(self, gate_id: str, mode: str) -> dict:
        """Drive ``run_production_gate`` once with the given mode.

        Mocks ``_run_collectors`` to return a fixed deterministic outcome
        list so the resulting gate file is a function ONLY of the mode
        kwarg's effect on the orchestrator's downstream wiring.
        """
        from story_automator.core.collector_config import CollectorConfig
        from story_automator.core.collector_runner import run_single_collector  # noqa: F401

        cfg = CollectorConfig(
            collector_id="probe",
            tool="python3",
            category="correctness",
            build_cmd=lambda c, p: ["true"],
        )
        evidence = make_evidence_record(
            collector="probe",
            tool="python3",
            category="correctness",
            status="ok",
            metrics={"coverage_pct": 95, "regressions": 0},
        )
        persisted = persist_evidence_record(self.project_root, gate_id, evidence)
        from story_automator.core.collector_config import CollectorOutcome

        outcome = CollectorOutcome(config=cfg, evidence=evidence, persisted_path=persisted)
        with patch(
            "story_automator.core.gate_orchestrator._run_collectors",
            return_value=[outcome],
        ):
            return run_production_gate(
                self.project_root,
                gate_id,
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile,
                factory_version="1.0.0",
                registry=self.registry,
                isolation_mode=mode,
                max_workers=2,
            )

    @patch.dict(os.environ, {}, clear=False)
    def test_shared_and_per_unit_produce_identical_category_verdicts(self) -> None:
        gate_shared = self._run_one_mode("gate-eq-shared", "shared")
        gate_per_unit = self._run_one_mode("gate-eq-per-unit", "per_unit")
        # gate dict may surface verdict either under "categories" with
        # nested "verdict" keys, or under a top-level "overall" string —
        # tolerate either shape but assert both modes agree.
        if "categories" in gate_shared and "categories" in gate_per_unit:
            cats_shared = gate_shared["categories"]
            cats_per_unit = gate_per_unit["categories"]
            self.assertEqual(set(cats_shared.keys()), set(cats_per_unit.keys()))
            for cat in cats_shared:
                v_shared = cats_shared[cat]
                v_per_unit = cats_per_unit[cat]
                if isinstance(v_shared, dict) and "verdict" in v_shared:
                    self.assertEqual(
                        v_shared["verdict"],
                        v_per_unit["verdict"],
                        f"verdict differs for category {cat!r}: "
                        f"shared={v_shared['verdict']!r} "
                        f"per_unit={v_per_unit['verdict']!r}",
                    )
        if "overall" in gate_shared and "overall" in gate_per_unit:
            self.assertEqual(
                gate_shared["overall"],
                gate_per_unit["overall"],
                "overall verdict differs between shared and per_unit modes",
            )


if __name__ == "__main__":
    unittest.main()
