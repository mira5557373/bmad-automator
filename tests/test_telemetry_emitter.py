# tests/test_telemetry_emitter.py
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from story_automator.core.telemetry_emitter import TelemetryEmitter


class TelemetryEmitterScaffoldTests(unittest.TestCase):
    def test_constructor_accepts_str_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(os.path.join(tmp, "events.jsonl"))
            self.assertIsInstance(emitter, TelemetryEmitter)

    def test_constructor_accepts_pathlib_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            self.assertIsInstance(emitter, TelemetryEmitter)

    def test_constructor_accepts_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl", run_id="run-1")
            self.assertIsInstance(emitter, TelemetryEmitter)
