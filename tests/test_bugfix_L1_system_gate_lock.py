"""Reproducer + regression tests for the L1 follow-up — system_gate lock gap.

The original L1 fix wrapped ``run_production_gate``'s
marker -> collectors -> clear lifecycle in the gate file lock. The sibling
entry point ``run_system_gate`` was not converted in the same pass, leaving
a concurrency window:

* ``run_system_gate`` calls ``write_gate_marker`` at line 78 and
  ``clear_gate_marker`` at line 115 *without* holding the gate lock.
* A concurrent ``run_production_gate`` (or another ``run_system_gate``)
  against the same ``project_root`` therefore still races on
  ``_bmad/gate/gate-in-progress.json``.

The fix extends the same ``get_gate_lock`` envelope used by
``run_production_gate`` (3600s timeout) across ``run_system_gate``'s full
recover -> reuse -> marker -> collectors -> clear -> route lifecycle, and
delegates the inner recovery to ``_recover_from_crash_locked`` so the lock
is not re-entered (``filelock`` is not re-entrant across separate
``FileLock`` instances). Locking approach: option (b) — share the SAME lock
as ``run_production_gate`` and reuse the internal locked recovery helper.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from filelock import FileLock, Timeout

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import gate_lock_path, get_gate_lock
from story_automator.core.system_env import ENV_TIER_MINIMAL, SystemEnvInfo
from story_automator.core.system_gate import run_system_gate


def _minimal_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": [], "system": ["reliability"]},
    }


def _make_gate_file(gate_id: str = "sg1", overall: str = "PASS") -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "schema_version": 1,
        "tier": "system",
        "target": {"kind": "epic", "id": "E1"},
        "commit_sha": "abc",
        "profile": {"id": "test", "version": 1, "hash": "h1"},
        "factory_version": "1.0.0",
        "categories": {},
        "overall": overall,
        "waivers": [],
    }


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["_STORY_AUTOMATOR_HOST"] = "1"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class ConcurrentSystemGatesDoNotRace(_Mixin, unittest.TestCase):
    """Two concurrent ``run_system_gate`` calls must serialize via the lock."""

    def test_concurrent_system_gates_do_not_race(self) -> None:
        order: list[str] = []
        order_lock = threading.Lock()

        def slow_collectors(*args: Any, **kwargs: Any) -> list[Any]:
            # Sleep inside the marker -> clear window to maximize the race
            # opportunity. With the lock, B can't enter while A is here.
            with order_lock:
                order.append("collectors-enter")
            time.sleep(0.3)
            with order_lock:
                order.append("collectors-exit")
            return []

        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")

        # Patches installed ONCE at the test level — patching a module attr
        # concurrently from two threads is itself a race, so we set up the
        # shared mocks here and let both worker threads use them.
        with patch(
            "story_automator.core.system_gate.system_env"
        ) as mock_env, patch(
            "story_automator.core.system_gate.evaluate_gate"
        ) as mock_eval, patch(
            "story_automator.core.system_gate.run_gate_collectors",
            side_effect=slow_collectors,
        ), patch(
            "story_automator.core.system_gate._recover_from_crash_locked",
            # K-5: inner recovery now returns (descriptor, pending_paths).
            return_value=({"recovered": False}, []),
        ), patch(
            "story_automator.core.system_gate.check_gate_reuse",
            return_value=(None, ""),
        ):
            mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
            mock_env.return_value.__exit__ = MagicMock(return_value=False)
            mock_eval.return_value = _make_gate_file()

            results: list[dict[str, Any]] = []
            errors: list[BaseException] = []
            results_lock = threading.Lock()

            def worker() -> None:
                try:
                    out = run_system_gate(
                        self.tmp,
                        "sg1",
                        epic_id="E1",
                        commit_sha="abc",
                        epic_metadata={},
                        profile=_minimal_profile(),
                        factory_version="1.0.0",
                        registry=CollectorRegistry(),
                    )
                    with results_lock:
                        results.append(out)
                except BaseException as e:  # noqa: BLE001
                    with results_lock:
                        errors.append(e)

            t_a = threading.Thread(target=worker)
            t_b = threading.Thread(target=worker)
            t_a.start()
            # Slight stagger so A enters the lock first.
            time.sleep(0.05)
            t_b.start()
            t_a.join(timeout=30)
            t_b.join(timeout=30)

        self.assertEqual(errors, [], f"workers raised: {errors}")
        self.assertEqual(len(results), 2)
        # Lock must have serialized the collectors window: A-enter, A-exit,
        # then B-enter, B-exit — no interleaving.
        self.assertEqual(
            order,
            [
                "collectors-enter",
                "collectors-exit",
                "collectors-enter",
                "collectors-exit",
            ],
            "marker lifecycle must be serialized by the gate lock",
        )


class SystemGateAcquiresLockBeforeMarkerWrite(_Mixin, unittest.TestCase):
    """The gate lock must be held by the time write_gate_marker runs."""

    def test_system_gate_lock_acquired_before_marker_write(self) -> None:
        observed: dict[str, Any] = {}
        expected_lock = gate_lock_path(self.tmp)

        real_write = None

        def spy_write(project_root: Any, gate_id: str, commit_sha: str) -> Path:
            # The lock file must exist on disk at this point — get_gate_lock
            # creates it implicitly when acquired.
            observed["lock_existed"] = expected_lock.is_file()
            # And attempting to grab the same lock from a foreign FileLock
            # with no timeout must fail — proving the calling thread holds it.
            foreign = FileLock(str(expected_lock), timeout=0.05)
            try:
                foreign.acquire()
            except Timeout:
                observed["lock_held"] = True
            else:
                observed["lock_held"] = False
                foreign.release()
            # Now invoke the real writer so the rest of the lifecycle works.
            from story_automator.core.evidence_io import (
                write_gate_marker as real,
            )
            return real(project_root, gate_id, commit_sha)

        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")

        with patch(
            "story_automator.core.system_gate.write_gate_marker",
            side_effect=spy_write,
        ), patch(
            "story_automator.core.system_gate.system_env"
        ) as mock_env, patch(
            "story_automator.core.system_gate.evaluate_gate"
        ) as mock_eval, patch(
            "story_automator.core.system_gate.run_gate_collectors",
            return_value=[],
        ), patch(
            "story_automator.core.system_gate._recover_from_crash_locked"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
            mock_env.return_value.__exit__ = MagicMock(return_value=False)
            # K-5: inner recovery now returns (descriptor, pending_paths).
            mock_recover.return_value = ({"recovered": False}, [])
            mock_reuse.return_value = (None, "")
            mock_eval.return_value = _make_gate_file()
            run_system_gate(
                self.tmp,
                "sg1",
                epic_id="E1",
                commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )

        self.assertTrue(observed.get("lock_existed"),
                        "gate lock file must exist before write_gate_marker")
        self.assertTrue(observed.get("lock_held"),
                        "system_gate must hold the gate lock during marker write")
        del real_write  # silence unused


class SystemGateReleasesLockOnProvisionFailure(_Mixin, unittest.TestCase):
    """On provisioned=False, the marker is cleared AND lock is released."""

    def test_system_gate_releases_lock_on_provision_failure(self) -> None:
        env_info = SystemEnvInfo(
            env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns",
            provisioned=False,
        )
        with patch(
            "story_automator.core.system_gate.system_env"
        ) as mock_env, patch(
            "story_automator.core.system_gate.recover_from_crash"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
            mock_env.return_value.__exit__ = MagicMock(return_value=False)
            mock_recover.return_value = {"recovered": False}
            mock_reuse.return_value = (None, "")
            result = run_system_gate(
                self.tmp,
                "sg1",
                epic_id="E1",
                commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )

        # Provision failure must still produce a FAIL gate_file.
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result.get("_provision_failed"))

        # The marker must be cleared.
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.is_file(),
                         "marker must be cleared on provision failure")

        # The lock MUST be released — a fresh acquire from a foreign holder
        # with a short timeout must succeed.
        with get_gate_lock(self.tmp, timeout=2.0):
            pass


class SystemGateReleasesLockOnException(_Mixin, unittest.TestCase):
    """When the collector explodes, the lock must still be released."""

    def test_system_gate_lock_releases_on_exception(self) -> None:
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")

        def boom(*args: Any, **kwargs: Any) -> list[Any]:
            raise RuntimeError("collector exploded")

        with patch(
            "story_automator.core.system_gate.system_env"
        ) as mock_env, patch(
            "story_automator.core.system_gate.evaluate_gate"
        ), patch(
            "story_automator.core.system_gate.run_gate_collectors",
            side_effect=boom,
        ), patch(
            "story_automator.core.system_gate._recover_from_crash_locked"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
            mock_env.return_value.__exit__ = MagicMock(return_value=False)
            # K-5: inner recovery now returns (descriptor, pending_paths).
            mock_recover.return_value = ({"recovered": False}, [])
            mock_reuse.return_value = (None, "")
            with self.assertRaises(RuntimeError):
                run_system_gate(
                    self.tmp,
                    "sg1",
                    epic_id="E1",
                    commit_sha="abc",
                    epic_metadata={},
                    profile=_minimal_profile(),
                    factory_version="1.0.0",
                    registry=CollectorRegistry(),
                )

        # Marker must still be cleared via the finally block.
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.is_file(),
                         "marker must be cleared even when collectors raise")

        # And the lock must be released.
        with get_gate_lock(self.tmp, timeout=2.0):
            pass


if __name__ == "__main__":
    unittest.main()
