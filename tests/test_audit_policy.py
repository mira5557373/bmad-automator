from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
