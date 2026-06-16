"""Regression tests for the deep-audit bug fixes.

Each test pins a previously-broken behavior that has no other coverage. They
are pure-logic / temp-file tests with no tmux or platform dependency, so they
run identically on Linux, macOS, and Windows.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from story_automator.cli import _cmd_parse_story_range
from story_automator.commands.basic import cmd_stop_hook
from story_automator.commands.orchestrator import _coerce_int, _marker, _scalar_or_empty, _state_update
from story_automator.commands.orchestrator_epic_agents import agents_build_action, agents_resolve_action
from story_automator.commands.state import _max_parallel
from story_automator.core.epic_parser import parse_story
from story_automator.core.frontmatter import extract_frontmatter, parse_simple_frontmatter, split_frontmatter
from story_automator.core.runtime_layout import active_marker_path
from story_automator.core.sprint import sprint_status_in_text
from story_automator.core.success_verifiers import _story_artifact_path
from story_automator.core.tmux_runtime import extract_active_task


def _capture_json(fn, *args) -> dict:
    out = io.StringIO()
    with redirect_stdout(out):
        code = fn(*args)
    return code, json.loads(out.getvalue())


class FrontmatterFenceTests(unittest.TestCase):
    """#02: a '---' inside a value must not truncate the frontmatter."""

    def test_embedded_triple_dash_in_value_preserves_downstream_keys(self) -> None:
        doc = (
            "---\n"
            'epic: "1"\n'
            'customInstructions: "use --- as a separator"\n'
            "status: IN_PROGRESS\n"
            'policyVersion: "2"\n'
            "---\n"
            "# body\n"
        )
        fields = parse_simple_frontmatter(doc)
        self.assertEqual(fields.get("status"), "IN_PROGRESS")
        self.assertEqual(fields.get("policyVersion"), "2")
        self.assertIn("---", fields.get("customInstructions", ""))

    def test_split_frontmatter_keeps_body_horizontal_rule(self) -> None:
        doc = "---\nkey: value\n---\nintro\n\n---\n\nmore body\n"
        front, body = split_frontmatter(doc)
        self.assertEqual(front.strip(), "key: value")
        # The markdown horizontal rule in the body is preserved, not consumed.
        self.assertIn("---", body)
        self.assertIn("more body", body)

    def test_non_fenced_document_returns_empty(self) -> None:
        self.assertEqual(extract_frontmatter("no frontmatter here\n"), "")


class SprintCompareTests(unittest.TestCase):
    """#01: dotted storyRange ids must resolve against dashed full-key rows."""

    def test_dotted_id_matches_dashed_full_key_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content = "1-1-user-authentication: done\n1-2-password-reset: done\n"
            self.assertTrue(sprint_status_in_text(tmp, content, "1.1").done)
            self.assertTrue(sprint_status_in_text(tmp, content, "1.2").done)

    def test_unmatched_id_is_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content = "1-1-user-authentication: ready-for-dev\n"
            self.assertFalse(sprint_status_in_text(tmp, content, "1.1").done)

    def test_literal_dotted_row_still_matches(self) -> None:
        # Preserves the legacy literal-key path used by an existing test.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(sprint_status_in_text(tmp, "1.2: done\n", "1.2").done)


class MaxParallelTests(unittest.TestCase):
    """#05: maxParallel coercion is defensive and clamps to >= 1."""

    def test_absent_defaults_to_one(self) -> None:
        self.assertEqual(_max_parallel({}), 1)

    def test_none_defaults_to_one(self) -> None:
        self.assertEqual(_max_parallel({"maxParallel": None}), 1)

    def test_zero_and_negative_clamp_to_one(self) -> None:
        self.assertEqual(_max_parallel({"maxParallel": 0}), 1)
        self.assertEqual(_max_parallel({"maxParallel": -4}), 1)

    def test_valid_value_preserved(self) -> None:
        self.assertEqual(_max_parallel({"maxParallel": 3}), 3)
        self.assertEqual(_max_parallel({"maxParallel": "5"}), 5)

    def test_non_numeric_returns_none(self) -> None:
        self.assertIsNone(_max_parallel({"maxParallel": "abc"}))
        self.assertIsNone(_max_parallel({"maxParallel": [1]}))


class EpicParserDependencyTests(unittest.TestCase):
    """#12: a Dependencies line is metadata, not description/AC prose."""

    def _rules_file(self, tmp: Path) -> Path:
        rules = tmp / "rules.json"
        rules.write_text(json.dumps({"rules": [], "structural_rules": {}}), encoding="utf-8")
        return rules

    def test_dependency_line_excluded_from_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            epic = tmp / "epic.md"
            epic.write_text(
                "## Epic 1: Sample\n"
                "### Story 1.1: Login\n"
                "As a user I want to log in.\n"
                "Dependencies: 1.0 auth service\n"
                "#### Acceptance Criteria\n"
                "- Given valid creds, login succeeds\n",
                encoding="utf-8",
            )
            result = parse_story(epic, "1.1", self._rules_file(tmp))
            self.assertNotIn("Dependencies", result["description"])
            self.assertNotIn("auth service", result["description"])
            self.assertIn("log in", result["description"])
            self.assertNotIn("Dependencies", " ".join(result["acceptanceCriteria"]))


class ScalarOrEmptyTests(unittest.TestCase):
    """#14: null sentinels render as empty, not the literal 'null'."""

    def test_null_sentinels_map_to_empty(self) -> None:
        self.assertEqual(_scalar_or_empty(None), "")
        self.assertEqual(_scalar_or_empty("null"), "")
        self.assertEqual(_scalar_or_empty("~"), "")

    def test_real_value_preserved(self) -> None:
        self.assertEqual(_scalar_or_empty("1.2"), "1.2")
        self.assertEqual(_scalar_or_empty(3), "3")


class CoerceIntTests(unittest.TestCase):
    """#26: marker int parsing is defensive."""

    def test_empty_uses_default(self) -> None:
        self.assertEqual(_coerce_int("", 0), 0)
        self.assertEqual(_coerce_int(None, 7), 7)

    def test_valid_and_invalid(self) -> None:
        self.assertEqual(_coerce_int("42", 0), 42)
        self.assertIsNone(_coerce_int("abc", 0))


class StateUpdateTests(unittest.TestCase):
    """#15/#16 + #07/#13: --set is guarded and the write is atomic."""

    def test_set_without_equals_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.md"
            state.write_text("---\nstatus: READY\n---\n", encoding="utf-8")
            code, payload = _capture_json(_state_update, [str(state), "--set", "DONE"])
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "invalid_set")
            # File is untouched / intact.
            self.assertIn("status: READY", state.read_text(encoding="utf-8"))

    def test_valid_set_updates_and_preserves_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.md"
            state.write_text("---\nstatus: READY\nepic: \"1\"\n---\n", encoding="utf-8")
            code, payload = _capture_json(_state_update, [str(state), "--set", "status=COMPLETE"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["updated"], ["status"])
            text = state.read_text(encoding="utf-8")
            self.assertIn("status: COMPLETE", text)
            self.assertIn('epic: "1"', text)


class StoryArtifactTraversalTests(unittest.TestCase):
    """#21: a crafted sprint-status key cannot escape the artifacts dir."""

    def test_traversal_preferred_story_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _story_artifact_path(tmp, "1-2", "../../../etc/passwd", allow_prefix_fallback=False)
            self.assertIsNone(result)

    def test_separator_bearing_key_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _story_artifact_path(tmp, "1-2", "sub/dir/key", allow_prefix_fallback=False)
            self.assertIsNone(result)


class ParseStoryRangeTests(unittest.TestCase):
    """#25: a non-numeric --total returns a structured error, not a crash."""

    def test_non_numeric_total_returns_error(self) -> None:
        code, payload = _capture_json(_cmd_parse_story_range, ["--input", "1", "--total", "abc"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "missing_input_or_total")


class MarkerRobustnessTests(unittest.TestCase):
    """#26: marker create/heartbeat degrade gracefully on bad input."""

    def test_create_with_non_numeric_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PROJECT_ROOT": tmp}, clear=False):
                code, payload = _capture_json(
                    _marker,
                    ["create", "--epic", "1", "--story", "1.1", "--remaining", "abc"],
                )
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "invalid_int")

    def test_heartbeat_on_corrupt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PROJECT_ROOT": tmp}, clear=False):
                marker = active_marker_path(Path(tmp))
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("{not valid json", encoding="utf-8")
                code, payload = _capture_json(_marker, ["heartbeat"])
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "marker_invalid")


class StopHookRemainingTests(unittest.TestCase):
    """#20: a non-numeric storiesRemaining must not block forever."""

    def _run_stop_hook(self, tmp: str, remaining) -> int:
        with mock.patch.dict(os.environ, {"PROJECT_ROOT": tmp}, clear=False):
            os.environ.pop("STORY_AUTOMATOR_CHILD", None)
            marker = active_marker_path()
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"storiesRemaining": remaining}), encoding="utf-8")
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO("")), redirect_stdout(out):
                code = cmd_stop_hook([])
            return code, out.getvalue()

    def test_non_numeric_remaining_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self._run_stop_hook(tmp, "unknown")
            self.assertEqual(code, 0)
            self.assertNotIn("block", output)

    def test_positive_remaining_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self._run_stop_hook(tmp, 2)
            self.assertEqual(code, 0)
            self.assertIn("block", output)


class AgentsBuildResolveTests(unittest.TestCase):
    """#06/#27: malformed agents/complexity input returns a clean error."""

    def test_agents_resolve_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents.md"
            agents.write_text("```json\n{ truncated", encoding="utf-8")
            code, payload = _capture_json(
                agents_resolve_action,
                ["--agents-file", str(agents), "--story", "1.1", "--task", "dev"],
            )
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "agents_file_invalid")

    def test_agents_build_skips_entry_without_story_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.md"
            state.write_text("---\nepic: \"1\"\nepicName: \"E\"\n---\n", encoding="utf-8")
            complexity = Path(tmp) / "complexity.json"
            complexity.write_text(
                json.dumps({"stories": [{"title": "no id"}, {"storyId": "1.2", "complexity": "high"}]}),
                encoding="utf-8",
            )
            output = Path(tmp) / "agents.md"
            code, payload = _capture_json(
                agents_build_action,
                [
                    "--state-file", str(state),
                    "--complexity-file", str(complexity),
                    "--output", str(output),
                    "--config-json", "{}",
                ],
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["stories"], 1)
            self.assertEqual(payload.get("skipped"), 1)

    def test_agents_build_on_corrupt_complexity_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.md"
            state.write_text("---\nepic: \"1\"\n---\n", encoding="utf-8")
            complexity = Path(tmp) / "complexity.json"
            complexity.write_text("{ not json", encoding="utf-8")
            output = Path(tmp) / "agents.md"
            code, payload = _capture_json(
                agents_build_action,
                [
                    "--state-file", str(state),
                    "--complexity-file", str(complexity),
                    "--output", str(output),
                    "--config-json", "{}",
                ],
            )
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "complexity_file_invalid")


class ActiveTaskCsvTests(unittest.TestCase):
    """#08: active_task must not contain commas that break the status CSV."""

    def test_commas_collapsed_to_spaces(self) -> None:
        result = extract_active_task("⏺ Updated a.py, b.py, c.py\n")
        self.assertNotIn(",", result)
        self.assertIn("a.py", result)


class ProjectRootIdiomTests(unittest.TestCase):
    """An explicitly-empty PROJECT_ROOT must fall back to cwd, not return ''."""

    def test_empty_project_root_falls_back_to_cwd(self) -> None:
        from story_automator.core.utils import get_project_root

        with mock.patch.dict(os.environ, {"PROJECT_ROOT": ""}, clear=False):
            self.assertTrue(get_project_root())  # not empty
        with mock.patch.dict(os.environ, {"PROJECT_ROOT": "/tmp/some-root"}, clear=False):
            self.assertEqual(get_project_root(), "/tmp/some-root")


class SpawnCollisionTests(unittest.TestCase):
    """R05: a name collision with a live session must not clobber its state."""

    def test_spawn_refuses_when_session_already_live(self) -> None:
        from story_automator.core import tmux_runtime as tr

        with mock.patch.object(tr, "command_exists", return_value=True), \
            mock.patch.object(tr.shutil, "which", return_value="/bin/bash"), \
            mock.patch.object(tr, "resolve_command_shell", return_value="/bin/bash"), \
            mock.patch.object(tr, "tmux_has_session", return_value=True), \
            mock.patch.object(tr, "cleanup_runtime_artifacts") as cleanup, \
            mock.patch.object(tr, "run_cmd") as run_cmd:
            out, code = tr._spawn_runner("sa-proj-260101-000000-e1-s1-1-dev", "echo hi", "claude", "/tmp/x")
        self.assertEqual(code, 1)
        self.assertIn("session already exists", out)
        # The destructive cleanup and tmux new-session must NOT have run.
        cleanup.assert_not_called()
        run_cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
