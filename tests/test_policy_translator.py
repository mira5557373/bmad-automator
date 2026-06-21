from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from story_automator.core.bauto_bridge.policy_translator import (
    KNOWN_BAUTO_TABLES,
    PolicyTranslationError,
    policy_toml_to_runtime,
    runtime_to_policy_toml,
)


SAMPLE_TOML = """\
[scm]
provider = "git"
default_branch = "main"

[review]
max_iterations = 3
required_reviewers = ["alice", "bob"]

[session]
timeout_seconds = 600
auto_resume = true

[ceilings]
max_loc = 500
max_files = 20

[drift]
detect = true
threshold = 0.25

[policy]
strict = true
allow_skip = false

[trust]
verify_sigs = true
trusted_keys = ["KEY-AAA", "KEY-BBB"]

[calibration]
score_floor = 0.7

[telemetry]
enabled = true
endpoint = "http://localhost:9000"

[plugins]
allowlist = ["a", "b"]

[test]
runner = "unittest"
parallel = 2
"""


class PolicyTranslatorReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.toml_path = self.tmp_path / "policy.toml"
        self.toml_path.write_text(SAMPLE_TOML, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_known_tables_contains_expected(self) -> None:
        self.assertIn("scm", KNOWN_BAUTO_TABLES)
        self.assertIn("review", KNOWN_BAUTO_TABLES)
        self.assertIn("test", KNOWN_BAUTO_TABLES)
        self.assertEqual(len(KNOWN_BAUTO_TABLES), 11)

    def test_policy_toml_to_runtime_returns_dict_with_known_tables(self) -> None:
        runtime = policy_toml_to_runtime(self.toml_path)
        self.assertIsInstance(runtime, dict)
        for table in KNOWN_BAUTO_TABLES:
            self.assertIn(table, runtime, f"missing table {table}")
        self.assertEqual(runtime["scm"]["provider"], "git")
        self.assertEqual(runtime["review"]["max_iterations"], 3)
        self.assertEqual(runtime["review"]["required_reviewers"], ["alice", "bob"])
        self.assertTrue(runtime["session"]["auto_resume"])

    def test_policy_toml_to_runtime_accepts_str_path(self) -> None:
        runtime = policy_toml_to_runtime(str(self.toml_path))
        self.assertEqual(runtime["scm"]["provider"], "git")

    def test_policy_toml_to_runtime_missing_file_raises(self) -> None:
        missing = self.tmp_path / "nope.toml"
        with self.assertRaises(PolicyTranslationError):
            policy_toml_to_runtime(missing)

    def test_policy_toml_to_runtime_invalid_toml_raises(self) -> None:
        bad = self.tmp_path / "bad.toml"
        bad.write_text("this is = = not valid toml [\n", encoding="utf-8")
        with self.assertRaises(PolicyTranslationError):
            policy_toml_to_runtime(bad)

    def test_unknown_table_raises_translation_error(self) -> None:
        weird = self.tmp_path / "weird.toml"
        weird.write_text("[unexpected_table]\nfoo = 1\n", encoding="utf-8")
        with self.assertRaises(PolicyTranslationError):
            policy_toml_to_runtime(weird)


class PolicyTranslatorWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_runtime_to_policy_toml_roundtrip(self) -> None:
        original_toml = self.tmp_path / "in.toml"
        original_toml.write_text(SAMPLE_TOML, encoding="utf-8")
        runtime = policy_toml_to_runtime(original_toml)

        out_path = self.tmp_path / "out.toml"
        written = runtime_to_policy_toml(runtime, out_path)
        self.assertEqual(written, out_path)
        self.assertTrue(out_path.is_file())

        with out_path.open("rb") as fh:
            reloaded = tomllib.load(fh)

        self.assertEqual(reloaded["scm"]["provider"], "git")
        self.assertEqual(reloaded["review"]["required_reviewers"], ["alice", "bob"])
        self.assertEqual(reloaded["ceilings"]["max_loc"], 500)
        self.assertTrue(reloaded["trust"]["verify_sigs"])

    def test_runtime_to_policy_toml_rejects_unknown_table(self) -> None:
        runtime = {"scm": {"provider": "git"}, "rogue": {"k": "v"}}
        out_path = self.tmp_path / "out.toml"
        with self.assertRaises(PolicyTranslationError):
            runtime_to_policy_toml(runtime, out_path)

    def test_runtime_to_policy_toml_writes_minimal_subset(self) -> None:
        runtime = {"scm": {"provider": "git"}, "test": {"runner": "unittest", "parallel": 4}}
        out_path = self.tmp_path / "out.toml"
        runtime_to_policy_toml(runtime, out_path)
        with out_path.open("rb") as fh:
            reloaded = tomllib.load(fh)
        self.assertEqual(reloaded, runtime)

    def test_runtime_to_policy_toml_rejects_non_dict_input(self) -> None:
        out_path = self.tmp_path / "out.toml"
        with self.assertRaises(PolicyTranslationError):
            runtime_to_policy_toml("not a dict", out_path)  # type: ignore[arg-type]

    def test_runtime_to_policy_toml_handles_nested_dicts(self) -> None:
        runtime = {
            "scm": {"provider": "git", "auth": {"method": "ssh", "key": "id_rsa"}},
        }
        out_path = self.tmp_path / "out.toml"
        runtime_to_policy_toml(runtime, out_path)
        with out_path.open("rb") as fh:
            reloaded = tomllib.load(fh)
        self.assertEqual(reloaded["scm"]["provider"], "git")
        self.assertEqual(reloaded["scm"]["auth"]["method"], "ssh")


class PolicyTranslationErrorTests(unittest.TestCase):
    def test_is_value_error_subclass(self) -> None:
        self.assertTrue(issubclass(PolicyTranslationError, ValueError))


if __name__ == "__main__":
    unittest.main()
