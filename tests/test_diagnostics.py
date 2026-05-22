from __future__ import annotations

import json
import tempfile
import unittest
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

        self.assertIn("token=<redacted>", payload["message"])
        self.assertIn("<path:state.json>", payload["message"])
        self.assertNotIn("abc123", payload["message"])
        self.assertNotIn("/tmp/private", payload["message"])

    def test_redact_actual_masks_sensitive_dict_keys(self) -> None:
        payload = redact_actual({"token": "abc123", "safe": "visible", "nested": {"password": "pw"}})

        self.assertEqual(payload["token"], "<redacted>")
        self.assertEqual(payload["safe"], "visible")
        self.assertEqual(payload["nested"]["password"], "<redacted>")

    def test_redact_actual_masks_secret_assignments_in_strings(self) -> None:
        redacted = redact_actual("token=abc123 password:pw keep=this")

        self.assertIn("token=<redacted>", redacted)
        self.assertIn("password=<redacted>", redacted)
        self.assertIn("keep=this", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("password:pw", redacted)

    def test_redact_actual_shortens_absolute_paths_and_long_strings(self) -> None:
        redacted = redact_actual(f"/Users/joon/project/private/story.md {'x' * 220}")

        self.assertIn("<path:story.md>", redacted)
        self.assertNotIn("/Users/joon/project/private", redacted)
        self.assertIn("<truncated", redacted)

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
            message="validation complete",
            severity="warning",
            issues=[DiagnosticIssue(type="missing_field", field="status", source="validate-state")],
            context={"path": "/tmp/state.md", "apiKey": "secret"},
        )

        payload = serialize_event(event)

        self.assertEqual(payload["name"], "state.validation")
        self.assertEqual(payload["issues"][0]["field"], "status")
        self.assertEqual(payload["context"]["path"], "<path:state.md>")
        self.assertEqual(payload["context"]["apiKey"], "<redacted>")

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
