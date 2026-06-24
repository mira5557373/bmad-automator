"""Tests for system gate lifecycle and epic verdict routing."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.system_gate import (
    run_system_gate,
    route_epic_verdict,
    stories_to_reopen,
)


def _minimal_profile() -> dict:
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {
            "code": [],
            "system": ["reliability", "resilience"],
        },
    }


def _make_system_gate_file(
    overall: str = "PASS",
    categories: dict | None = None,
) -> dict:
    return {
        "gate_id": "sg1", "schema_version": 1, "tier": "system",
        "target": {"kind": "epic", "id": "E1"},
        "commit_sha": "abc",
        "profile": {"id": "test", "version": 1, "hash": "h1"},
        "factory_version": "1.0.0",
        "categories": categories or {},
        "overall": overall,
        "waivers": [],
    }


class RunSystemGateTests(unittest.TestCase):
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate._recover_from_crash_locked")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_full_lifecycle(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "no existing gate")
        # K-5: inner recovery now returns (descriptor, pending_paths).
        mock_recover.return_value = ({"recovered": False}, [])
        mock_collectors.return_value = []

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL

        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        gate_file = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc", "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }
        mock_evaluate.return_value = gate_file

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={"type": "feature"},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["tier"], "system")
        mock_recover.assert_called_once()
        mock_env.assert_called_once()

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.check_gate_reuse")
    @patch("story_automator.core.system_gate.recover_from_crash")
    def test_reuses_existing_gate(
        self, mock_recover: MagicMock, mock_reuse: MagicMock,
    ) -> None:
        mock_recover.return_value = {"recovered": False}
        existing_gate = {"gate_id": "sg1", "overall": "PASS", "tier": "system"}
        mock_reuse.return_value = (existing_gate, "")

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "PASS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate.recover_from_crash")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_injects_runtime_env(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = {"recovered": False}
        mock_collectors.return_value = []

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_FULL

        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        gate_file = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc", "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }
        mock_evaluate.return_value = gate_file

        captured_profile = {}

        def capture_collectors(*args, **kwargs):
            captured_profile.update(args[3])
            return []

        mock_collectors.side_effect = capture_collectors

        with tempfile.TemporaryDirectory() as td:
            run_system_gate(
                td, "sg1", epic_id="E1", commit_sha="abc",
                epic_metadata={"type": "infra"},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertIn("_runtime_env", captured_profile)
        self.assertEqual(captured_profile["_runtime_env"]["tier"], ENV_TIER_FULL)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.recover_from_crash")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_provision_failure_returns_fail(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = {"recovered": False}

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL

        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns", provisioned=False)
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result.get("_provision_failed"))


class RouteEpicVerdictTests(unittest.TestCase):
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_pass_returns_done(self) -> None:
        gate = _make_system_gate_file("PASS")
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=["E1-001"])
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["overall"], "PASS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_concerns_returns_done_with_debt(self) -> None:
        cats = {"reliability": {"verdict": "CONCERNS", "rationale": "degraded"}}
        gate = _make_system_gate_file("CONCERNS", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=["E1-001"])
        self.assertEqual(result["action"], "done")
        self.assertIn("mitigation_debt", result)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_fail_returns_reopen(self) -> None:
        cats = {"resilience": {"verdict": "FAIL", "rationale": "scenario failed"}}
        gate = _make_system_gate_file("FAIL", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(
                td, gate, epic_id="E1", story_keys=["E1-001", "E1-002"],
            )
        self.assertEqual(result["action"], "reopen")
        self.assertIn("failing_categories", result)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_fail_exhausted_parks(self) -> None:
        cats = {"resilience": {"verdict": "FAIL", "rationale": "scenario failed"}}
        gate = _make_system_gate_file("FAIL", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(
                td, gate, epic_id="E1", story_keys=["E1-001"],
                remediation_cycle=3, max_cycles=3,
            )
        self.assertEqual(result["action"], "park")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_waived_returns_done(self) -> None:
        gate = _make_system_gate_file("WAIVED")
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=[])
        self.assertEqual(result["action"], "done")


class StoriesToReopenTests(unittest.TestCase):
    def test_returns_all_stories_on_fail(self) -> None:
        cats = {"resilience": {"verdict": "FAIL"}}
        gate = _make_system_gate_file("FAIL", cats)
        reopened = stories_to_reopen(gate, ["E1-001", "E1-002"])
        self.assertEqual(reopened, ["E1-001", "E1-002"])

    def test_returns_empty_on_pass(self) -> None:
        gate = _make_system_gate_file("PASS")
        reopened = stories_to_reopen(gate, ["E1-001"])
        self.assertEqual(reopened, [])


class RunSystemGateG2WiringTests(unittest.TestCase):
    """AC-G-08 — ``run_system_gate`` accepts + forwards G2 kwargs.

    Mirrors ``test_gate_orchestrator_g2_wiring.py``: validation runs
    early (before host check / lock acquisition), defaults are
    ``shared`` + ``4``, and the kwargs reach ``run_gate_collectors``.
    """

    def _build_env_info(self):
        from story_automator.core.system_env import (
            ENV_TIER_MINIMAL,
            SystemEnvInfo,
        )

        return SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.assert_host_context")
    def test_invalid_isolation_mode_raises_before_host_check(
        self, mock_host: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                run_system_gate(
                    td, "sg1",
                    epic_id="E1", commit_sha="abc",
                    epic_metadata={},
                    profile=_minimal_profile(),
                    factory_version="1.0.0",
                    registry=CollectorRegistry(),
                    isolation_mode="bogus",
                )
        mock_host.assert_not_called()

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.assert_host_context")
    def test_invalid_max_workers_raises_before_host_check(
        self, mock_host: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TypeError):
                run_system_gate(
                    td, "sg1",
                    epic_id="E1", commit_sha="abc",
                    epic_metadata={},
                    profile=_minimal_profile(),
                    factory_version="1.0.0",
                    registry=CollectorRegistry(),
                    max_workers="four",  # type: ignore[arg-type]
                )
        mock_host.assert_not_called()

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.assert_host_context")
    def test_invalid_max_workers_bool_raises(
        self, mock_host: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TypeError):
                run_system_gate(
                    td, "sg1",
                    epic_id="E1", commit_sha="abc",
                    epic_metadata={},
                    profile=_minimal_profile(),
                    factory_version="1.0.0",
                    registry=CollectorRegistry(),
                    max_workers=True,  # type: ignore[arg-type]
                )
        mock_host.assert_not_called()

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate._recover_from_crash_locked")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_default_isolation_mode_is_shared(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = ({"recovered": False}, [])
        mock_collectors.return_value = []

        env_info = self._build_env_info()
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_evaluate.return_value = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc",
            "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }

        with tempfile.TemporaryDirectory() as td:
            run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        mock_collectors.assert_called_once()
        _, kwargs = mock_collectors.call_args
        self.assertEqual(kwargs["isolation_mode"], "shared")
        self.assertEqual(kwargs["max_workers"], 4)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate._recover_from_crash_locked")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_per_unit_kwargs_threaded_through(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = ({"recovered": False}, [])
        mock_collectors.return_value = []

        env_info = self._build_env_info()
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)
        mock_evaluate.return_value = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc",
            "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }

        with tempfile.TemporaryDirectory() as td:
            run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
                isolation_mode="per_unit",
                max_workers=2,
            )
        mock_collectors.assert_called_once()
        _, kwargs = mock_collectors.call_args
        self.assertEqual(kwargs["isolation_mode"], "per_unit")
        self.assertEqual(kwargs["max_workers"], 2)


if __name__ == "__main__":
    unittest.main()
