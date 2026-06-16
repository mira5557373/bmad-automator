# tests/test_run_identity.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.run_identity import current_run_id
from story_automator.core.utils import md5_hex8


class RunIdentityTests(unittest.TestCase):
    def _write_marker(self, tmp: Path, payload) -> Path:
        marker = tmp / ".story-automator-active"
        marker.write_text(json.dumps(payload), encoding="utf-8")
        return marker

    def test_returns_empty_when_marker_absent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=tmp / "nope",
            ):
                self.assertEqual(current_run_id(str(tmp)), "")

    def test_returns_empty_on_malformed_marker_json(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = tmp / ".story-automator-active"
            marker.write_text("{ not json", encoding="utf-8")
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                self.assertEqual(current_run_id(str(tmp)), "")

    def test_returns_empty_when_payload_not_dict(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = self._write_marker(tmp, ["createdAt", "epic"])
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                self.assertEqual(current_run_id(str(tmp)), "")

    def test_returns_empty_when_createdAt_missing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = self._write_marker(tmp, {"epic": "8", "pid": 1})
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                self.assertEqual(current_run_id(str(tmp)), "")

    def test_stable_id_for_same_marker(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = self._write_marker(
                tmp,
                {"createdAt": "2026-06-16T10:00:00Z", "epic": "8", "pid": 4242},
            )
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                first = current_run_id(str(tmp))
                second = current_run_id(str(tmp))
            self.assertTrue(first.startswith("run-"))
            self.assertNotEqual(first, "run-")
            self.assertEqual(first, second)

    def test_id_changes_when_createdAt_changes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = tmp / ".story-automator-active"
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                marker.write_text(
                    json.dumps(
                        {"createdAt": "2026-06-16T10:00:00Z", "epic": "8", "pid": 1}
                    ),
                    encoding="utf-8",
                )
                first = current_run_id(str(tmp))
                marker.write_text(
                    json.dumps(
                        {"createdAt": "2026-06-16T11:30:00Z", "epic": "8", "pid": 1}
                    ),
                    encoding="utf-8",
                )
                second = current_run_id(str(tmp))
            self.assertNotEqual(first, second)

    def test_id_value_matches_md5_of_components(self):
        created, epic, pid = "2026-06-16T10:00:00Z", "8", "4242"
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = self._write_marker(
                tmp, {"createdAt": created, "epic": epic, "pid": int(pid)}
            )
            with mock.patch(
                "story_automator.core.run_identity.active_marker_path",
                return_value=marker,
            ):
                got = current_run_id(str(tmp))
            self.assertEqual(got, "run-" + md5_hex8(f"{created}|{epic}|{pid}"))


if __name__ == "__main__":
    unittest.main()
