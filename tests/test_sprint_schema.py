from __future__ import annotations

import unittest

from story_automator.core.sprint_schema import (
    ALLOWED_TOP_LEVEL,
    REQUIRED_TOP_LEVEL,
    SprintSchemaError,
    validate_sprint_status,
)


def _valid_payload() -> dict:
    return {
        "epic": "epic-1",
        "sprint_id": "S001",
        "started_at": "2026-06-20T00:00:00Z",
        "stories": [
            {"key": "1.1", "status": "Draft"},
            {"key": "1.2", "status": "Approved"},
        ],
    }


class SprintSchemaTests(unittest.TestCase):
    def test_required_constants_match_documented_set(self) -> None:
        self.assertEqual(
            REQUIRED_TOP_LEVEL,
            ("epic", "sprint_id", "started_at", "stories"),
        )
        # ALLOWED must be a superset of REQUIRED
        for key in REQUIRED_TOP_LEVEL:
            self.assertIn(key, ALLOWED_TOP_LEVEL)
        # And specifically include the optional keys
        self.assertIn("notes", ALLOWED_TOP_LEVEL)
        self.assertIn("carry_over", ALLOWED_TOP_LEVEL)

    def test_valid_payload_passes(self) -> None:
        # Must not raise
        validate_sprint_status(_valid_payload())

    def test_valid_payload_with_optional_keys(self) -> None:
        payload = _valid_payload()
        payload["notes"] = "some notes"
        payload["carry_over"] = ["3.1"]
        validate_sprint_status(payload)

    def test_missing_required_key_raises(self) -> None:
        payload = _valid_payload()
        del payload["epic"]
        with self.assertRaises(SprintSchemaError) as ctx:
            validate_sprint_status(payload)
        self.assertIn("epic", str(ctx.exception))

    def test_unknown_top_level_key_raises(self) -> None:
        payload = _valid_payload()
        payload["mystery"] = 42
        with self.assertRaises(SprintSchemaError) as ctx:
            validate_sprint_status(payload)
        self.assertIn("mystery", str(ctx.exception))

    def test_invalid_status_raises(self) -> None:
        payload = _valid_payload()
        payload["stories"][0]["status"] = "WeirdStatus"
        with self.assertRaises(SprintSchemaError) as ctx:
            validate_sprint_status(payload)
        self.assertIn("WeirdStatus", str(ctx.exception))

    def test_non_dict_raises(self) -> None:
        with self.assertRaises(SprintSchemaError):
            validate_sprint_status([])  # type: ignore[arg-type]

    def test_stories_must_be_list(self) -> None:
        payload = _valid_payload()
        payload["stories"] = {"not": "a list"}
        with self.assertRaises(SprintSchemaError):
            validate_sprint_status(payload)

    def test_story_entry_must_be_dict(self) -> None:
        payload = _valid_payload()
        payload["stories"] = ["not-a-dict"]
        with self.assertRaises(SprintSchemaError):
            validate_sprint_status(payload)

    def test_canonicalized_status_accepted(self) -> None:
        # Lowercase and weird capitalizations should still validate, because
        # validate uses canonicalize to normalize before comparing.
        payload = _valid_payload()
        payload["stories"][0]["status"] = "draft"
        payload["stories"][1]["status"] = "in progress"
        validate_sprint_status(payload)

    def test_schema_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(SprintSchemaError, ValueError))


if __name__ == "__main__":
    unittest.main()
