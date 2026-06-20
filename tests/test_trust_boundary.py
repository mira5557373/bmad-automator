from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from story_automator.core.trust_boundary import (
    TrustBoundaryError,
    assert_host_context,
    is_child_session,
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


if __name__ == "__main__":
    unittest.main()
