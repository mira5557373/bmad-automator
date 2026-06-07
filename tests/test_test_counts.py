from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import story_automator
from story_automator.commands.basic import cmd_test_counts
from story_automator.core.junit import parse_junit

# Pin the bundled policy to THIS checkout so the override merge is hermetic even
# when bmad-story-automator is also installed under ~/.claude/skills.
SKILL_DIR = Path(story_automator.__file__).resolve().parents[2]


class ParseJunitTests(unittest.TestCase):
    """JUnit parsing is stack-agnostic: only the universal testsuite attributes
    are read, summed over direct children to avoid phpunit's nested double-count."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _xml(self, body: str) -> Path:
        path = self.dir / "junit.xml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_single_testsuite_root(self) -> None:
        path = self._xml('<testsuite tests="5" failures="1" errors="0" skipped="2" assertions="42"/>')
        self.assertEqual(
            parse_junit(path),
            {"tests": 5, "failures": 1, "errors": 0, "skipped": 2, "assertions": 42},
        )

    def test_testsuites_sums_direct_children(self) -> None:
        path = self._xml(
            '<testsuites>'
            '<testsuite tests="3" failures="0" errors="0" skipped="1"/>'
            '<testsuite tests="2" failures="1" errors="0" skipped="0"/>'
            '</testsuites>'
        )
        counts = parse_junit(path)
        self.assertEqual((counts["tests"], counts["failures"], counts["skipped"]), (5, 1, 1))
        self.assertIsNone(counts["assertions"])  # no suite carries it -> nullable

    def test_nested_suites_not_double_counted(self) -> None:
        # phpunit nests a child suite under a parent that already holds subtree
        # totals; summing direct children only must report 10, not 20.
        path = self._xml(
            '<testsuites>'
            '<testsuite tests="10" failures="2" errors="0" skipped="1" assertions="30">'
            '<testsuite tests="10" failures="2" errors="0" skipped="1" assertions="30"/>'
            '</testsuite>'
            '</testsuites>'
        )
        counts = parse_junit(path)
        self.assertEqual(counts["tests"], 10)
        self.assertEqual(counts["assertions"], 30)

    def test_aggregate_only_testsuites(self) -> None:
        path = self._xml('<testsuites tests="7" failures="0" errors="1" skipped="0"></testsuites>')
        self.assertEqual(parse_junit(path)["tests"], 7)

    def test_corrupt_xml_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_junit(self._xml('<testsuite tests="1"'))

    def test_non_junit_root_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_junit(self._xml('<coverage/>'))


class TestCountsCommandTests(unittest.TestCase):
    """test-counts computes story test counts from JUnit truth and owns a single
    `### Test Counts` block — the second half of the doc-drift fix (issue #40)."""

    SUITE = '<testsuite tests="4" failures="0" errors="0" skipped="1" assertions="20"/>'

    def setUp(self) -> None:
        self._prev_skills_root = os.environ.get("BMAD_SKILLS_ROOT")
        os.environ["BMAD_SKILLS_ROOT"] = str(SKILL_DIR)
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.artifacts = self.repo / "_bmad-output" / "implementation-artifacts"
        self.artifacts.mkdir(parents=True)
        self.story = self.artifacts / "1-2-example.md"
        self.story.write_text(
            "# Story 1.2\n\n## Dev Agent Record\n\n### File List\n\n- src/a.py\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self._prev_skills_root is None:
            os.environ.pop("BMAD_SKILLS_ROOT", None)
        else:
            os.environ["BMAD_SKILLS_ROOT"] = self._prev_skills_root
        self.tmp.cleanup()

    def _policy(self, **test_block: str) -> None:
        path = self.repo / "_bmad" / "bmm" / "story-automator.policy.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"test": test_block}), encoding="utf-8")

    def _artifact(self, rel: str, body: str = SUITE, age_seconds: float = 0.0) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(path, (stamp, stamp))
        return path

    def _invoke(self, *extra: str, story: str = "1-2") -> tuple[int, dict]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cmd_test_counts(["--repo", str(self.repo), "--story", story, *extra])
        return code, json.loads(out.getvalue())

    def test_tier3_skip_when_unconfigured(self) -> None:
        # Bundled default has empty test.* -> nothing to compute, File List
        # reconcile already ran independently so a skip is fine.
        code, payload = self._invoke("--write")
        self.assertEqual(code, 0)
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "test_not_configured")
        self.assertIsNone(payload["test_counts"])

    def test_tier1_capture_from_fresh_artifact(self) -> None:
        self._policy(junitPath="reports/junit.xml")
        self._artifact("reports/junit.xml")
        code, payload = self._invoke("--write")
        self.assertEqual(code, 0)
        self.assertEqual(payload["source"], "capture")
        self.assertEqual(payload["test_counts"], {"tests": 4, "failures": 0, "errors": 0, "skipped": 1, "assertions": 20})
        self.assertTrue(payload["wrote"])
        text = self.story.read_text(encoding="utf-8")
        self.assertIn("### Test Counts", text)
        self.assertIn("- Tests: 4", text)
        self.assertIn("- Skipped: 1", text)
        self.assertIn("- Assertions: 20", text)
        self.assertIn("- src/a.py", text)  # File List untouched

    def test_assertions_line_omitted_when_absent(self) -> None:
        self._policy(junitPath="reports/junit.xml")
        self._artifact("reports/junit.xml", '<testsuite tests="2" failures="0" errors="0" skipped="0"/>')
        _, payload = self._invoke("--write")
        self.assertIsNone(payload["test_counts"]["assertions"])
        self.assertNotIn("Assertions", self.story.read_text(encoding="utf-8"))

    def test_story_placeholder_in_junit_path(self) -> None:
        self._policy(junitPath="reports/{story}.xml")
        self._artifact("reports/1-2-example.xml")
        _, payload = self._invoke()
        self.assertTrue(payload["junit_path"].endswith("reports/1-2-example.xml"))
        self.assertEqual(payload["test_counts"]["tests"], 4)

    def test_since_gates_stale_artifact_to_skip(self) -> None:
        self._policy(junitPath="reports/junit.xml")  # no command -> no floor
        self._artifact("reports/junit.xml", age_seconds=600)
        _, payload = self._invoke("--since", str(time.time()))
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "test_artifact_stale")

    def test_tier3_missing_artifact_no_command(self) -> None:
        self._policy(junitPath="reports/junit.xml")
        _, payload = self._invoke()
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "test_artifact_missing")

    def test_tier2_rerun_emits_and_parses(self) -> None:
        self._policy(
            junitPath="reports/junit.xml",
            command="printf '<testsuite tests=\"3\" failures=\"1\" errors=\"0\" skipped=\"0\"/>' > {junit}",
        )
        # No artifact on disk -> must fall to the re-run floor.
        code, payload = self._invoke("--write")
        self.assertEqual(code, 0)
        self.assertEqual(payload["source"], "rerun")
        self.assertEqual(payload["test_counts"], {"tests": 3, "failures": 1, "errors": 0, "skipped": 0, "assertions": None})
        self.assertEqual(payload["command_exit"], 0)
        self.assertIn("- Tests: 3", self.story.read_text(encoding="utf-8"))

    def test_stale_artifact_reruns_when_command_set(self) -> None:
        self._policy(
            junitPath="reports/junit.xml",
            command="printf '<testsuite tests=\"9\" failures=\"0\" errors=\"0\" skipped=\"0\"/>' > {junit}",
        )
        self._artifact("reports/junit.xml", age_seconds=600)  # stale capture
        _, payload = self._invoke("--since", str(time.time()))
        self.assertEqual(payload["source"], "rerun")
        self.assertEqual(payload["test_counts"]["tests"], 9)

    def test_rerun_skips_when_artifact_not_emitted(self) -> None:
        self._policy(junitPath="reports/junit.xml", command="true")  # runs, writes nothing
        _, payload = self._invoke()
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["reason"], "test_artifact_not_emitted")
        self.assertEqual(payload["command_exit"], 0)

    def test_write_is_idempotent(self) -> None:
        self._policy(junitPath="reports/junit.xml")
        self._artifact("reports/junit.xml")
        self.assertTrue(self._invoke("--write")[1]["wrote"])
        first = self.story.read_text(encoding="utf-8")
        code, payload = self._invoke("--write")
        self.assertEqual(code, 0)
        self.assertFalse(payload["wrote"])  # counts unchanged -> no churn
        self.assertEqual(self.story.read_text(encoding="utf-8"), first)

    def test_corrupt_artifact_is_an_error(self) -> None:
        self._policy(junitPath="reports/junit.xml")
        self._artifact("reports/junit.xml", "<testsuite tests=")
        code, payload = self._invoke()
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "junit_parse_failed")

    def test_invalid_policy_test_block(self) -> None:
        path = self.repo / "_bmad" / "bmm" / "story-automator.policy.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"test": {"command": 123}}), encoding="utf-8")  # non-string
        code, payload = self._invoke()
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "policy_invalid")

    def test_story_not_found(self) -> None:
        code, payload = self._invoke(story="9-9")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "story_file_not_found")


if __name__ == "__main__":
    unittest.main()
