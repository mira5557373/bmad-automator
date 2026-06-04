from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from story_automator.core.diagnostics import (
    DIAGNOSTIC_EVENTS_FILE_ENV,
    DiagnosticEvent,
    DiagnosticIssue,
    emit_diagnostic_event,
    issues_from_exception,
    legacy_issue_message,
    redact_actual,
    serialize_event,
    serialize_issue,
    serialize_issues,
)
from story_automator.core.orchestration_events import emit_policy_decision


class DiagnosticsTests(unittest.TestCase):
    def test_issue_serializes_stable_shape(self) -> None:
        issue = DiagnosticIssue(
            type="missing_field",
            field="frontmatter.status",
            expected="READY",
            actual="",
            message="Missing status",
            recovery="Add status frontmatter.",
            code="STATE001",
            severity="error",
            source="validate-state",
        )

        self.assertEqual(
            serialize_issue(issue),
            {
                "type": "missing_field",
                "field": "frontmatter.status",
                "expected": "READY",
                "actual": "",
                "message": "Missing status",
                "recovery": "Add status frontmatter.",
                "code": "STATE001",
                "severity": "error",
                "source": "validate-state",
            },
        )
        self.assertEqual(json.dumps(serialize_issue(issue), separators=(",", ":")).count("\n"), 0)

    def test_serialize_issues_preserves_order(self) -> None:
        issues = [
            DiagnosticIssue(type="missing_field", field="a", source="state"),
            DiagnosticIssue(type="invalid_type", field="b", source="state"),
        ]

        payload = serialize_issues(issues)

        self.assertEqual([item["field"] for item in payload], ["a", "b"])
        self.assertTrue(all("severity" in item and "source" in item for item in payload))

    def test_legacy_issue_message_prefers_message(self) -> None:
        issue = DiagnosticIssue(type="invalid_type", field="count", expected="integer", message="count must be integer")

        self.assertEqual(legacy_issue_message(issue), "count must be integer")

    def test_legacy_issue_message_redacts_message(self) -> None:
        issue = DiagnosticIssue(type="ValueError", message="token=abc123 failed at /tmp/private/state.md")

        message = legacy_issue_message(issue)

        self.assertIn("token=<redacted>", message)
        self.assertIn("<path:state.md>", message)
        self.assertNotIn("abc123", message)

    def test_legacy_issue_message_falls_back_to_field_and_expected(self) -> None:
        issue = DiagnosticIssue(type="invalid_type", field="count", expected="integer")

        self.assertEqual(legacy_issue_message(issue), "count: expected integer")

    def test_issues_from_exception_uses_exception_class_and_source(self) -> None:
        issues = issues_from_exception(ValueError("bad json"), source="parse-output", field="payload")

        self.assertEqual(len(issues), 1)
        payload = serialize_issue(issues[0])
        self.assertEqual(payload["type"], "ValueError")
        self.assertEqual(payload["field"], "payload")
        self.assertEqual(payload["source"], "parse-output")
        self.assertEqual(payload["message"], "bad json")

    def test_issues_from_exception_redacts_message(self) -> None:
        issues = issues_from_exception(ValueError("token=abc123 failed at /tmp/private/state.json"), source="parse-output", field="payload")

        payload = serialize_issue(issues[0])

        self.assertIn("token=<redacted>", issues[0].actual)
        self.assertIn("<path:state.json>", issues[0].actual)
        self.assertNotIn("abc123", issues[0].actual)
        self.assertIn("token=<redacted>", payload["message"])
        self.assertIn("<path:state.json>", payload["message"])
        self.assertNotIn("abc123", payload["message"])
        self.assertNotIn("/tmp/private", payload["message"])

    def test_redact_actual_masks_sensitive_dict_keys(self) -> None:
        payload = redact_actual({"token": "abc123", "safe": "visible", "nested": {"password": "pw"}})

        self.assertEqual(payload["token"], "<redacted>")
        self.assertEqual(payload["safe"], "visible")
        self.assertEqual(payload["nested"]["password"], "<redacted>")

    def test_redact_actual_masks_sensitive_dict_key_text(self) -> None:
        payload = redact_actual(
            {
                "GITHUB_TOKEN=ghp_secret": "x",
                "/Users/joon/My Project/private/state.md": "x",
            }
        )

        serialized = json.dumps(payload, separators=(",", ":"))
        self.assertIn("GITHUB_TOKEN=<redacted>", payload)
        self.assertIn("<path:state.md>", payload)
        self.assertNotIn("ghp_secret", serialized)
        self.assertNotIn("My Project", serialized)

    def test_redact_actual_masks_secret_assignments_in_strings(self) -> None:
        redacted = redact_actual("token=abc123 password:pw keep=this")

        self.assertIn("token=<redacted>", redacted)
        self.assertIn("password=<redacted>", redacted)
        self.assertIn("keep=this", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("password:pw", redacted)

    def test_redact_actual_masks_prefixed_env_secret_assignments(self) -> None:
        redacted = redact_actual("OPENAI_API_KEY=sk-test123 GITHUB_TOKEN=ghp_abc123 keep=this")

        self.assertIn("OPENAI_API_KEY=<redacted>", redacted)
        self.assertIn("GITHUB_TOKEN=<redacted>", redacted)
        self.assertIn("keep=this", redacted)
        self.assertNotIn("sk-test123", redacted)
        self.assertNotIn("ghp_abc123", redacted)

    def test_redact_actual_preserves_non_secret_token_words(self) -> None:
        redacted = redact_actual({"tokenized": "true", "my_token_count": 5, "GITHUB_TOKEN": "ghp_abc123"})
        text = redact_actual("tokenized=value my_token_count=5 token_value=abc123")

        self.assertEqual(redacted["tokenized"], "true")
        self.assertEqual(redacted["my_token_count"], 5)
        self.assertEqual(redacted["GITHUB_TOKEN"], "<redacted>")
        self.assertIn("tokenized=value", text)
        self.assertIn("my_token_count=5", text)
        self.assertIn("token_value=<redacted>", text)
        self.assertNotIn("abc123", text)

    def test_redact_actual_masks_bearer_and_quoted_secret_values(self) -> None:
        redacted = redact_actual('Authorization: Bearer abc123 token="abc 123" api_key=Basic xyz')

        self.assertIn("Authorization=<redacted>", redacted)
        self.assertIn("token=<redacted>", redacted)
        self.assertIn("api_key=<redacted>", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("abc 123", redacted)
        self.assertNotIn("xyz", redacted)

    def test_redact_actual_shortens_absolute_paths_and_long_strings(self) -> None:
        redacted = redact_actual(f"/Users/joon/project/private/story.md {'x' * 220}")

        self.assertIn("<path:story.md>", redacted)
        self.assertNotIn("/Users/joon/project/private", redacted)
        self.assertIn("<truncated", redacted)

    def test_redact_actual_masks_absolute_paths_with_spaces(self) -> None:
        redacted = redact_actual("/Users/joon/My Project/private/state.md token=abc123")

        self.assertEqual(redacted, "<path:state.md> token=<redacted>")
        self.assertNotIn("My Project", redacted)
        self.assertNotIn("private/state.md", redacted)

    def test_redact_actual_masks_absolute_path_filenames_with_spaces(self) -> None:
        redacted = redact_actual("failed at /Users/joon/My Project/private/my file.md token=abc123")

        self.assertEqual(redacted, "failed at <path:my file.md> token=<redacted>")
        self.assertNotIn("My Project", redacted)
        self.assertNotIn("private/my file.md", redacted)

    def test_redact_actual_masks_extensionless_absolute_paths_with_spaces(self) -> None:
        redacted = redact_actual("failed at /Users/joon/My Project/private token=abc123")

        self.assertEqual(redacted, "failed at <path:private> token=<redacted>")
        self.assertNotIn("My Project", redacted)
        self.assertNotIn("private", redacted.removeprefix("failed at <path:private>"))

    def test_redact_actual_masks_extensionless_absolute_paths_with_spaced_leaf(self) -> None:
        redacted = redact_actual("failed at /Users/joon/My Project/private folder token=abc123")

        self.assertEqual(redacted, "failed at <path:private folder> token=<redacted>")
        self.assertNotIn("My Project", redacted)
        self.assertNotIn("private folder", redacted.removeprefix("failed at <path:private folder>"))

    def test_redact_actual_keeps_distinct_extensionless_paths_separate(self) -> None:
        posix = redact_actual("failed at /tmp/foo and /tmp/bar")
        windows = redact_actual(r"C:\tmp\foo and C:\tmp\bar")

        self.assertEqual(posix, "failed at <path:foo> and <path:bar>")
        self.assertEqual(windows, r"<path:foo> and <path:bar>")

    def test_redact_actual_keeps_distinct_extensionless_paths_before_secret_separate(self) -> None:
        redacted = redact_actual("failed at /tmp/foo and /tmp/bar token=abc123")

        self.assertEqual(redacted, "failed at <path:foo> and <path:bar> token=<redacted>")

    def test_redact_actual_masks_secret_values_in_path_segments(self) -> None:
        for raw in ("/tmp/token=abc123", "/tmp/foo/GITHUB_TOKEN=ghp_secret/bar"):
            with self.subTest(raw=raw):
                redacted = redact_actual(raw)

                self.assertNotIn("abc123", redacted)
                self.assertNotIn("ghp_secret", redacted)
                self.assertIn("<redacted>", redacted)

    def test_redact_actual_masks_path_values_in_secret_assignments(self) -> None:
        for raw in (
            "token=/Users/joon/My Project/private/my file.md",
            "Authorization: Bearer /Users/joon/My Project/private/token file.txt",
        ):
            with self.subTest(raw=raw):
                redacted = redact_actual(raw)

                self.assertIn("<redacted>", redacted)
                self.assertNotIn("My Project", redacted)
                self.assertNotIn("file.md", redacted)
                self.assertNotIn("file.txt", redacted)

    def test_redact_actual_masks_windows_absolute_paths(self) -> None:
        redacted = redact_actual(r"C:\Users\joon\private\state.md token=abc123")

        self.assertEqual(redacted, "<path:state.md> token=<redacted>")
        self.assertNotIn(r"C:\Users", redacted)
        self.assertNotIn(r"private\state.md", redacted)

    def test_redact_actual_limits_nested_collections(self) -> None:
        payload = redact_actual({"values": list(range(10)), **{f"k{i}": i for i in range(10)}})

        self.assertEqual(payload["values"][-1], "... 4 more")
        self.assertIn("...", payload)

    def test_non_json_values_become_json_safe(self) -> None:
        issue = DiagnosticIssue(type="path", expected=Path("/tmp/state.md"), actual=Path("/tmp/state.md"), source="test")

        payload = serialize_issue(issue)

        self.assertEqual(payload["expected"], "/tmp/state.md")
        self.assertEqual(payload["actual"], "<path:state.md>")

    def test_event_serializes_without_stdout_side_effects(self) -> None:
        event = DiagnosticEvent(
            name="state.validation",
            source="validate-state",
            message="validation complete token=abc123 at /tmp/private/state.md",
            severity="warning",
            issues=[DiagnosticIssue(type="missing_field", field="status", source="validate-state")],
            context={"path": "/tmp/state.md", "apiKey": "secret"},
        )

        payload = serialize_event(event)

        self.assertEqual(payload["name"], "state.validation")
        self.assertIn("token=<redacted>", payload["message"])
        self.assertNotIn("abc123", payload["message"])
        self.assertNotIn("/tmp/private", payload["message"])
        self.assertEqual(payload["issues"][0]["field"], "status")
        self.assertEqual(payload["context"]["path"], "<path:state.md>")
        self.assertEqual(payload["context"]["apiKey"], "<redacted>")

    def test_policy_decision_keeps_canonical_trigger_and_escalate(self) -> None:
        captured: list[DiagnosticEvent] = []

        def capture(event: DiagnosticEvent) -> bool:
            captured.append(event)
            return True

        with unittest.mock.patch("story_automator.core.orchestration_events.emit_diagnostic_event", side_effect=capture):
            emit_policy_decision("real-trigger", True, {"trigger": "fake-trigger", "escalate": False, "stateFile": "state.md"})

        self.assertEqual(captured[0].context["trigger"], "real-trigger")
        self.assertTrue(captured[0].context["escalate"])
        self.assertEqual(captured[0].context["stateFile"], "state.md")

    def test_emit_diagnostic_event_appends_jsonl_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            event = DiagnosticEvent(
                name="state.transition",
                source="state-update",
                context={"stateFile": "/tmp/private/state.md", "token": "abc123"},
            )

            self.assertTrue(emit_diagnostic_event(event, path))

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["name"], "state.transition")
            self.assertEqual(payload["context"]["stateFile"], "<path:state.md>")
            self.assertEqual(payload["context"]["token"], "<redacted>")

    def test_emit_diagnostic_event_is_disabled_without_target(self) -> None:
        with unittest.mock.patch.dict("os.environ", {DIAGNOSTIC_EVENTS_FILE_ENV: ""}, clear=False):
            self.assertFalse(emit_diagnostic_event(DiagnosticEvent(name="noop", source="test")))


if __name__ == "__main__":
    unittest.main()
