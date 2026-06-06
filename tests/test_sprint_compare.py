from __future__ import annotations

import io
import json
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_sprint_compare
from story_automator.core.sprint import sprint_status_done_in_text


SPRINT_STATUS = textwrap.dedent(
    """\
    development_status:
      epic-1: in-progress
      1-1-host-feasibility-probe: done
      1-2-docker-dev-test-environment: done
      1-3-database-wrapper-migrations: done
      1-4-redis-wrapper-clock: done
      2-1-users-schema-permanent-admin: in-progress
    """
)


class SprintStatusDoneInTextTests(unittest.TestCase):
    """`sprint_status_done_in_text` must resolve dotted IDs against descriptive
    slug keys -- the BMAD default `sprint-status.yaml` format."""

    def test_dotted_id_resolves_descriptive_slug(self) -> None:
        self.assertTrue(sprint_status_done_in_text(SPRINT_STATUS, "1.1"))

    def test_dashed_prefix_resolves_descriptive_slug(self) -> None:
        self.assertTrue(sprint_status_done_in_text(SPRINT_STATUS, "1-1"))

    def test_full_slug_key_exact_match(self) -> None:
        self.assertTrue(sprint_status_done_in_text(SPRINT_STATUS, "1-1-host-feasibility-probe"))

    def test_not_done_is_false(self) -> None:
        self.assertFalse(sprint_status_done_in_text(SPRINT_STATUS, "2.1"))

    def test_missing_story_is_false(self) -> None:
        self.assertFalse(sprint_status_done_in_text(SPRINT_STATUS, "9.9"))


class SprintCompareCommandTests(unittest.TestCase):
    """End-to-end regression for the false-positive `incomplete` bug: dotted
    `storyRange` vs descriptive-slug `sprint-status.yaml` keys."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.sprint = root / "sprint-status.yaml"
        self.sprint.write_text(SPRINT_STATUS)
        self.state = root / "orchestration.md"
        self.state.write_text(
            textwrap.dedent(
                """\
                ---
                storyRange: ["1.1", "1.2", "1.3", "1.4", "2.1"]
                currentStory: 2.1
                ---
                # Orchestration
                """
            )
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_sprint_compare(["--state", str(self.state), "--sprint", str(self.sprint)])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_all_earlier_done_reports_nothing_incomplete(self) -> None:
        result = self._run()
        self.assertEqual(result["checked"], ["1.1", "1.2", "1.3", "1.4"])
        self.assertEqual(result["incomplete"], [])

    def test_flags_genuinely_incomplete_story(self) -> None:
        # 2.1 is in-progress; if it were an earlier story it must be flagged.
        self.state.write_text(
            textwrap.dedent(
                """\
                ---
                storyRange: ["1.1", "2.1", "1.2"]
                currentStory: 1.2
                ---
                """
            )
        )
        result = self._run()
        self.assertEqual(result["checked"], ["1.1", "2.1"])
        self.assertEqual(result["incomplete"], ["2.1"])


if __name__ == "__main__":
    unittest.main()
