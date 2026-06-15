# tests/test_wire_tmux_runtime.py
from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_automator.core import tmux_runtime
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class StoryKeyFromSessionNameTests(unittest.TestCase):
    def test_extracts_dotted_story_id_from_runner_session_name(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e2-s2-7-dev"
            ),
            "2.7",
        )

    def test_extracts_with_cycle_suffix(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e10-s10-12-review-r2"
            ),
            "10.12",
        )

    def test_returns_empty_for_unparseable_name(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name("manual"), "")

    def test_returns_empty_for_empty_string(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name(""), "")
