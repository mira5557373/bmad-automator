from __future__ import annotations

import unittest

from story_automator.core.tmux_runtime import (
    BMAD_AUTO_ENV_KEYS,
    inject_bmad_auto_env,
)


class BmadAutoEnvKeysTests(unittest.TestCase):
    def test_keys_constant_is_complete_and_ordered(self) -> None:
        self.assertEqual(
            BMAD_AUTO_ENV_KEYS,
            (
                "BMAD_AUTO_STORY_KEY",
                "BMAD_AUTO_PHASE",
                "BMAD_AUTO_CLI_ID",
                "BMAD_AUTO_COMMIT_SHA",
                "BMAD_AUTO_TASK_ID",
            ),
        )

    def test_keys_constant_is_tuple_for_immutability(self) -> None:
        self.assertIsInstance(BMAD_AUTO_ENV_KEYS, tuple)
        # Tuples are hashable; lists are not. Confirm immutability.
        with self.assertRaises(AttributeError):
            BMAD_AUTO_ENV_KEYS.append("X")  # type: ignore[attr-defined]


class InjectBmadAutoEnvTests(unittest.TestCase):
    def test_returns_new_dict_does_not_mutate_input(self) -> None:
        base = {"PATH": "/usr/bin", "HOME": "/home/u"}
        out = inject_bmad_auto_env(base, story_key="e1.s2", phase="dev")
        self.assertIsNot(out, base)
        self.assertNotIn("BMAD_AUTO_STORY_KEY", base)
        self.assertEqual(base, {"PATH": "/usr/bin", "HOME": "/home/u"})

    def test_injects_default_cli_id_and_blank_optional_fields(self) -> None:
        out = inject_bmad_auto_env({}, story_key="e1.s2", phase="dev")
        self.assertEqual(out["BMAD_AUTO_STORY_KEY"], "e1.s2")
        self.assertEqual(out["BMAD_AUTO_PHASE"], "dev")
        self.assertEqual(out["BMAD_AUTO_CLI_ID"], "claude-code")
        self.assertEqual(out["BMAD_AUTO_COMMIT_SHA"], "")
        self.assertEqual(out["BMAD_AUTO_TASK_ID"], "")

    def test_explicit_values_override_defaults(self) -> None:
        out = inject_bmad_auto_env(
            {},
            story_key="e2.s7",
            phase="review",
            cli_id="codex",
            commit_sha="deadbeefcafe",
            task_id="t-99",
        )
        self.assertEqual(out["BMAD_AUTO_CLI_ID"], "codex")
        self.assertEqual(out["BMAD_AUTO_COMMIT_SHA"], "deadbeefcafe")
        self.assertEqual(out["BMAD_AUTO_TASK_ID"], "t-99")

    def test_preserves_caller_env(self) -> None:
        base = {"PATH": "/usr/bin", "FOO": "bar"}
        out = inject_bmad_auto_env(base, story_key="k", phase="p")
        self.assertEqual(out["PATH"], "/usr/bin")
        self.assertEqual(out["FOO"], "bar")

    def test_all_values_are_strings(self) -> None:
        out = inject_bmad_auto_env({}, story_key="k", phase="p")
        for key in BMAD_AUTO_ENV_KEYS:
            self.assertIn(key, out)
            self.assertIsInstance(out[key], str)

    def test_story_key_required_non_empty(self) -> None:
        with self.assertRaises(ValueError):
            inject_bmad_auto_env({}, story_key="", phase="dev")

    def test_phase_required_non_empty(self) -> None:
        with self.assertRaises(ValueError):
            inject_bmad_auto_env({}, story_key="k", phase="")

    def test_strips_whitespace_from_inputs(self) -> None:
        out = inject_bmad_auto_env(
            {},
            story_key="  e1.s2  ",
            phase="  dev  ",
            cli_id="  claude-code  ",
            commit_sha="  abc  ",
            task_id="  t-1  ",
        )
        self.assertEqual(out["BMAD_AUTO_STORY_KEY"], "e1.s2")
        self.assertEqual(out["BMAD_AUTO_PHASE"], "dev")
        self.assertEqual(out["BMAD_AUTO_CLI_ID"], "claude-code")
        self.assertEqual(out["BMAD_AUTO_COMMIT_SHA"], "abc")
        self.assertEqual(out["BMAD_AUTO_TASK_ID"], "t-1")

    def test_rejects_non_dict_env(self) -> None:
        with self.assertRaises(TypeError):
            inject_bmad_auto_env(["PATH=/x"], story_key="k", phase="p")  # type: ignore[arg-type]

    def test_existing_bmad_auto_keys_are_overwritten(self) -> None:
        base = {"BMAD_AUTO_STORY_KEY": "old", "BMAD_AUTO_PHASE": "old"}
        out = inject_bmad_auto_env(base, story_key="new-key", phase="new-phase")
        self.assertEqual(out["BMAD_AUTO_STORY_KEY"], "new-key")
        self.assertEqual(out["BMAD_AUTO_PHASE"], "new-phase")


if __name__ == "__main__":
    unittest.main()
