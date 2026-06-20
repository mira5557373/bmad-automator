from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.trust_boundary import (
    CHILD_FORCED_VARS,
    CHILD_STRIPPED_VARS,
    TrustBoundaryError,
    assert_host_context,
    is_child_session,
    is_path_under,
    resolve_host_evidence_dir,
    sandbox_env,
    sandbox_tmux_env_args,
    validate_evidence_path_isolation,
    verify_sandbox_env,
)


class IsChildSessionTests(unittest.TestCase):
    def test_false_when_env_var_absent(self) -> None:
        self.assertFalse(is_child_session({}))

    def test_false_when_env_var_empty(self) -> None:
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": ""}))

    def test_true_when_env_var_true(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "true"}))

    def test_true_when_env_var_1(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "1"}))

    def test_true_when_env_var_yes(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "yes"}))

    def test_true_case_insensitive(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "True"}))
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "TRUE"}))

    def test_false_for_other_values(self) -> None:
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "false"}))
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "0"}))
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "no"}))

    def test_reads_os_environ_when_env_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_child_session())
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            self.assertTrue(is_child_session())


class AssertHostContextTests(unittest.TestCase):
    def test_no_raise_when_host(self) -> None:
        assert_host_context("test_op", env={})

    def test_raises_when_child(self) -> None:
        with self.assertRaises(TrustBoundaryError) as ctx:
            assert_host_context("persist_evidence", env={"STORY_AUTOMATOR_CHILD": "true"})
        self.assertIn("persist_evidence", str(ctx.exception))
        self.assertIn("trust boundary violation", str(ctx.exception))

    def test_raises_without_operation_label(self) -> None:
        with self.assertRaises(TrustBoundaryError) as ctx:
            assert_host_context(env={"STORY_AUTOMATOR_CHILD": "1"})
        self.assertIn("trust boundary violation", str(ctx.exception))
        self.assertNotIn(":", str(ctx.exception).split("violation")[1].split("operation")[0])

    def test_reads_os_environ_when_env_none(self) -> None:
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                assert_host_context()

    def test_error_is_runtime_error(self) -> None:
        self.assertTrue(issubclass(TrustBoundaryError, RuntimeError))


class ChildSandboxConstantsTests(unittest.TestCase):
    def test_stripped_vars_contains_audit_key(self) -> None:
        self.assertIn("BMAD_AUDIT_KEY", CHILD_STRIPPED_VARS)

    def test_stripped_vars_contains_claudecode(self) -> None:
        self.assertIn("CLAUDECODE", CHILD_STRIPPED_VARS)

    def test_stripped_vars_contains_bash_env(self) -> None:
        self.assertIn("BASH_ENV", CHILD_STRIPPED_VARS)

    def test_stripped_vars_is_frozenset(self) -> None:
        self.assertIsInstance(CHILD_STRIPPED_VARS, frozenset)

    def test_forced_vars_sets_child_flag(self) -> None:
        self.assertEqual(CHILD_FORCED_VARS["STORY_AUTOMATOR_CHILD"], "true")


class SandboxEnvTests(unittest.TestCase):
    def test_strips_security_vars(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret", "PATH": "/usr/bin"}, clear=True):
            env = sandbox_env()
            self.assertNotIn("BMAD_AUDIT_KEY", env)
            self.assertIn("PATH", env)

    def test_forces_child_flag(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertEqual(env["STORY_AUTOMATOR_CHILD"], "true")

    def test_sets_agent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env(agent="claude")
            self.assertEqual(env["AI_AGENT"], "claude")

    def test_no_agent_when_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertNotIn("AI_AGENT", env)

    def test_extras_applied(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env(extras={"MY_VAR": "val"})
            self.assertEqual(env["MY_VAR"], "val")

    def test_strips_all_defined_vars(self) -> None:
        fake_env = {var: "should_strip" for var in CHILD_STRIPPED_VARS}
        with patch.dict(os.environ, fake_env, clear=True):
            env = sandbox_env()
            for var in CHILD_STRIPPED_VARS:
                value = env.get(var, "")
                self.assertEqual(value, "", f"{var} should be stripped but got {value!r}")


class VerifySandboxEnvTests(unittest.TestCase):
    def test_valid_env_passes(self) -> None:
        env = {"STORY_AUTOMATOR_CHILD": "true", "PATH": "/usr/bin"}
        ok, violations = verify_sandbox_env(env)
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_audit_key_present_fails(self) -> None:
        env = {"STORY_AUTOMATOR_CHILD": "true", "BMAD_AUDIT_KEY": "secret"}
        ok, violations = verify_sandbox_env(env)
        self.assertFalse(ok)
        self.assertTrue(any("BMAD_AUDIT_KEY" in v for v in violations))

    def test_missing_child_flag_fails(self) -> None:
        env = {"PATH": "/usr/bin"}
        ok, violations = verify_sandbox_env(env)
        self.assertFalse(ok)
        self.assertTrue(any("STORY_AUTOMATOR_CHILD" in v for v in violations))


class SandboxTmuxEnvArgsTests(unittest.TestCase):
    def test_contains_forced_vars(self) -> None:
        args = sandbox_tmux_env_args()
        self.assertIn("-e", args)
        self.assertIn("STORY_AUTOMATOR_CHILD=true", args)

    def test_contains_stripped_vars_as_empty(self) -> None:
        args = sandbox_tmux_env_args()
        for var in CHILD_STRIPPED_VARS:
            self.assertIn(f"{var}=", args)

    def test_contains_agent_when_specified(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        self.assertIn("AI_AGENT=claude", args)

    def test_no_agent_when_empty(self) -> None:
        args = sandbox_tmux_env_args()
        agent_args = [a for a in args if a.startswith("AI_AGENT=")]
        self.assertEqual(agent_args, [])

    def test_args_are_paired(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        for i in range(0, len(args), 2):
            self.assertEqual(args[i], "-e")


class IsPathUnderTests(unittest.TestCase):
    def test_child_under_parent(self) -> None:
        self.assertTrue(is_path_under(Path("/a/b"), Path("/a/b/c/d")))

    def test_child_is_parent(self) -> None:
        self.assertTrue(is_path_under(Path("/a/b"), Path("/a/b")))

    def test_child_not_under_parent(self) -> None:
        self.assertFalse(is_path_under(Path("/a/b"), Path("/x/y")))

    def test_traversal_attempt(self) -> None:
        self.assertFalse(is_path_under(Path("/a/b"), Path("/a/b/../c")))

    def test_real_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "parent"
            parent.mkdir()
            child = parent / "sub" / "deep"
            child.mkdir(parents=True)
            self.assertTrue(is_path_under(parent, child))
            self.assertFalse(is_path_under(child, parent))


class ValidateEvidencePathIsolationTests(unittest.TestCase):
    def test_isolated_path_passes(self) -> None:
        ok, reason = validate_evidence_path_isolation(
            Path("/host/evidence"), Path("/child/workdir")
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_evidence_under_child_fails(self) -> None:
        ok, reason = validate_evidence_path_isolation(
            Path("/child/workdir/_bmad/gate"), Path("/child/workdir")
        )
        self.assertFalse(ok)
        self.assertIn("under child working tree", reason)


class ResolveHostEvidenceDirTests(unittest.TestCase):
    def test_returns_bmad_gate_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = resolve_host_evidence_dir(td)
            self.assertEqual(result, Path(td).resolve() / "_bmad" / "gate")

    def test_returns_absolute_path(self) -> None:
        result = resolve_host_evidence_dir("relative/path")
        self.assertTrue(result.is_absolute())


class TmuxRuntimeCrossCheckTests(unittest.TestCase):
    """Verify sandbox_tmux_env_args produces flags covering all vars
    that tmux_runtime historically stripped inline."""

    HISTORICALLY_STRIPPED = {"BMAD_AUDIT_KEY", "CLAUDECODE", "BASH_ENV"}
    HISTORICALLY_FORCED = {"STORY_AUTOMATOR_CHILD": "true"}

    def test_stripped_vars_cover_historical(self) -> None:
        self.assertTrue(
            self.HISTORICALLY_STRIPPED.issubset(CHILD_STRIPPED_VARS),
            f"missing from CHILD_STRIPPED_VARS: "
            f"{self.HISTORICALLY_STRIPPED - CHILD_STRIPPED_VARS}",
        )

    def test_forced_vars_cover_historical(self) -> None:
        for var, val in self.HISTORICALLY_FORCED.items():
            self.assertEqual(
                CHILD_FORCED_VARS.get(var), val,
                f"CHILD_FORCED_VARS[{var!r}] should be {val!r}",
            )

    def test_tmux_args_contain_all_historical_vars(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        flat = " ".join(args)
        for var in self.HISTORICALLY_STRIPPED:
            self.assertIn(f"{var}=", flat)
        self.assertIn("STORY_AUTOMATOR_CHILD=true", flat)
        self.assertIn("AI_AGENT=claude", flat)


if __name__ == "__main__":
    unittest.main()
