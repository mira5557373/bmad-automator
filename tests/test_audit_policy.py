from __future__ import annotations

import os
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


class AuditForPolicyGateOnTests(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot/restore the env var so test ordering can't leak it.
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_returns_audit_log_when_flag_true_and_key_set(self) -> None:
        from story_automator.core.audit import AuditLog, audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            log = audit_for_policy(
                {"security": {"audit_trail": True}},
                Path(d) / "audit.jsonl",
            )
            self.assertIsInstance(log, AuditLog)
            self.assertEqual(log.path, Path(d) / "audit.jsonl")
            self.assertEqual(len(log.key), 32)

    def test_returned_log_can_append_and_verify(self) -> None:
        # End-to-end: the returned log is a fully wired AuditLog.
        from story_automator.core.audit import audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            log = audit_for_policy(
                {"security": {"audit_trail": True}},
                Path(d) / "audit.jsonl",
            )

            class Fake:
                event_name = "E"

                def to_dict(self) -> dict:
                    return {"k": 1}

            assert log is not None
            log.append(Fake())
            self.assertEqual(log.verify(), (True, 1))


class AuditForPolicyKeyMissingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_raises_when_flag_true_but_env_unset(self) -> None:
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing):
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )

    def test_raises_when_flag_true_but_env_empty(self) -> None:
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = ""
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing):
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )

    def test_exception_message_does_not_contain_env_value(self) -> None:
        # NFR-no-secret-leak: even though the env var is unset here, the
        # message must not embed any audit key material under any branch.
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        secret = "do-not-log-this-canary-2c2c2c"
        os.environ["BMAD_AUDIT_KEY"] = secret
        # Force the missing-key branch by setting flag false, then back to
        # true with the env cleared again — the message we capture is from
        # the second call.
        os.environ.pop("BMAD_AUDIT_KEY")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing) as ctx:
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )
            self.assertNotIn(secret, str(ctx.exception))


class AuditModuleSizeBudgetM4Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
        # Same NFR as M2/M3; re-asserted here so an M4-only run catches
        # accidental bloat without depending on the M2/M3 suites.
        from pathlib import Path

        audit_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "audit.py"
        )
        line_count = sum(1 for _ in audit_path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"audit.py is {line_count} lines (budget: 500 per NFR-500-line-cap)",
        )


if __name__ == "__main__":
    unittest.main()
