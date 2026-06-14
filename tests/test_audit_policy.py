from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class PolicySchemaSecurityTests(unittest.TestCase):
    def _base_policy(self) -> dict:
        # Minimal shape that satisfies _validate_policy_shape today.
        return {
            "version": 1,
            "runtime": {
                "parser": {
                    "provider": "claude",
                    "model": "haiku",
                    "timeoutSeconds": 120,
                },
            },
            "workflow": {"sequence": []},
            "steps": {},
        }

    def test_security_audit_trail_false_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        policy = self._base_policy()
        policy["security"] = {"audit_trail": False}
        _validate_policy_shape(policy)  # must not raise

    def test_security_audit_trail_true_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        policy = self._base_policy()
        policy["security"] = {"audit_trail": True}
        _validate_policy_shape(policy)

    def test_security_missing_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        _validate_policy_shape(self._base_policy())

    def test_security_audit_trail_non_bool_rejected(self) -> None:
        from story_automator.core.runtime_policy import (
            PolicyError,
            _validate_policy_shape,
        )

        policy = self._base_policy()
        policy["security"] = {"audit_trail": "yes"}
        with self.assertRaises(PolicyError):
            _validate_policy_shape(policy)

    def test_security_unknown_subkey_rejected(self) -> None:
        from story_automator.core.runtime_policy import (
            PolicyError,
            _validate_policy_shape,
        )

        policy = self._base_policy()
        policy["security"] = {"audit_trail": False, "unknown": 1}
        with self.assertRaises(PolicyError):
            _validate_policy_shape(policy)


class AuditForPolicyGateOffTests(unittest.TestCase):
    def test_returns_none_when_security_block_missing(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(audit_for_policy({}, Path(d) / "audit.jsonl"))

    def test_returns_none_when_audit_trail_missing(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                audit_for_policy({"security": {}}, Path(d) / "audit.jsonl")
            )

    def test_returns_none_when_audit_trail_false(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                audit_for_policy(
                    {"security": {"audit_trail": False}},
                    Path(d) / "audit.jsonl",
                )
            )

    def test_gate_off_does_no_filesystem_io(self) -> None:
        # REQ-14: short-circuit must touch no files, not even the parent dir.
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "nonexistent-subdir" / "audit.jsonl"
            self.assertIsNone(
                audit_for_policy({"security": {"audit_trail": False}}, target)
            )
            # The parent we asked about must not have been created.
            self.assertFalse(target.parent.exists())


if __name__ == "__main__":
    unittest.main()
