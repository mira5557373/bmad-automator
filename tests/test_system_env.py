"""Tests for system environment tier resolution, config, and provision/teardown."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from story_automator.core.system_env import (
    ENV_TIER_MINIMAL,
    ENV_TIER_FULL,
    SystemEnvConfig,
    SystemEnvInfo,
    resolve_env_tier,
    build_env_config,
    provision_system_env,
    teardown_system_env,
    system_env,
)


class ResolveTierTests(unittest.TestCase):
    def test_default_is_minimal(self) -> None:
        tier = resolve_env_tier({}, {})
        self.assertEqual(tier, ENV_TIER_MINIMAL)

    def test_infra_epic_is_full(self) -> None:
        epic = {"type": "infra"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_cross_cutting_epic_is_full(self) -> None:
        epic = {"type": "cross-cutting"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_release_candidate_is_full(self) -> None:
        epic = {"release_candidate": True}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_feature_epic_is_minimal(self) -> None:
        epic = {"type": "feature"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_MINIMAL)

    def test_profile_override_to_full(self) -> None:
        epic = {"type": "feature"}
        profile = {"rules": {"system_env": {"force_tier": "full"}}}
        tier = resolve_env_tier(epic, profile)
        self.assertEqual(tier, ENV_TIER_FULL)


class SystemEnvConfigTests(unittest.TestCase):
    def test_frozen(self) -> None:
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns")
        with self.assertRaises(AttributeError):
            config.tier = ENV_TIER_FULL  # type: ignore[misc]

    def test_defaults(self) -> None:
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        self.assertEqual(config.compose_file, "")
        self.assertEqual(config.services, ())
        self.assertEqual(config.seed_data, "")
        self.assertEqual(config.helm_values, "")


class BuildEnvConfigTests(unittest.TestCase):
    def test_minimal_tier(self) -> None:
        config = build_env_config(
            "/tmp/project", "abc123",
            {"type": "feature"}, {"version": 1, "id": "test"},
        )
        self.assertEqual(config.tier, ENV_TIER_MINIMAL)
        self.assertIn("abc123", config.namespace)

    def test_full_tier_infra(self) -> None:
        config = build_env_config(
            "/tmp/project", "abc123",
            {"type": "infra"}, {"version": 1, "id": "test"},
        )
        self.assertEqual(config.tier, ENV_TIER_FULL)

    def test_namespace_contains_commit_prefix(self) -> None:
        config = build_env_config(
            "/tmp/project", "deadbeef1234",
            {}, {"version": 1, "id": "test"},
        )
        self.assertIn("deadbeef", config.namespace)


class SystemEnvInfoTests(unittest.TestCase):
    def test_frozen(self) -> None:
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        with self.assertRaises(AttributeError):
            info.env_id = "e2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        self.assertEqual(info.endpoints, {})
        self.assertTrue(info.provisioned)


class ProvisionEnvTests(unittest.TestCase):
    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_minimal_calls_compose(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns", compose_file="compose.yaml")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertTrue(info.provisioned)
        self.assertEqual(info.tier, ENV_TIER_MINIMAL)
        mock_sub.run.assert_called()

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_full_calls_kind_and_helm(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        config = SystemEnvConfig(tier=ENV_TIER_FULL, namespace="test-ns")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertTrue(info.provisioned)
        self.assertEqual(info.tier, ENV_TIER_FULL)

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_provision_failure_returns_not_provisioned(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=1)
        mock_sub.CalledProcessError = Exception
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertFalse(info.provisioned)


class TeardownEnvTests(unittest.TestCase):
    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_teardown_minimal(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        with tempfile.TemporaryDirectory() as td:
            teardown_system_env(info, td)
        mock_sub.run.assert_called()

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_teardown_full(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        with tempfile.TemporaryDirectory() as td:
            teardown_system_env(info, td)


class SystemEnvContextManagerTests(unittest.TestCase):
    @patch("story_automator.core.system_env.teardown_system_env")
    @patch("story_automator.core.system_env.provision_system_env")
    def test_yields_env_info(self, mock_prov: MagicMock, mock_tear: MagicMock) -> None:
        expected = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_prov.return_value = expected
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        with system_env(config, "/tmp") as info:
            self.assertEqual(info, expected)
        mock_tear.assert_called_once_with(expected, "/tmp")

    @patch("story_automator.core.system_env.teardown_system_env")
    @patch("story_automator.core.system_env.provision_system_env")
    def test_teardown_on_exception(self, mock_prov: MagicMock, mock_tear: MagicMock) -> None:
        expected = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_prov.return_value = expected
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        with self.assertRaises(RuntimeError):
            with system_env(config, "/tmp"):
                raise RuntimeError("boom")
        mock_tear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
