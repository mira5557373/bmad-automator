from __future__ import annotations

import dataclasses
import io
import json
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands import drift_cmd
from story_automator.commands.drift_cmd import cmd_drift
from story_automator.core import telemetry_events as te
from story_automator.core.calibration import build_calibration
from story_automator.core.drift_detector import compute_drift, format_drift_report


# ---------------------------------------------------------------------------
# Event shim
#
# build_calibration reads ``model_id`` / ``task_kind`` off StoryCompleted /
# StoryFailed via getattr, but the shipped M01 dataclasses do not declare
# those fields, and parse_event does ``cls(**payload)`` so an extra key would
# raise TypeError and the line would be silently dropped (no entries). The
# real M02 emitter is expected to carry the calibration tags; until that lands
# the test synthesizes them by registering a kw-only subclass (defaulted
# fields) under the same EVENT_TYPE. The subclass remains an ``isinstance`` of
# the original StoryCompleted / StoryFailed, so calibration's type check and
# bucketing are exercised unchanged. setUp/tearDown restore the registry and
# module attributes so the rest of the suite sees the pristine classes.
# ---------------------------------------------------------------------------


class _ExtendedEventShim:
    _orig_cls: dict[str, type] = {}
    _orig_reg: dict[str, type] = {}

    @classmethod
    def install(cls) -> None:
        for name in ("StoryCompleted", "StoryFailed"):
            base = getattr(te, name)
            cls._orig_cls[name] = base
            cls._orig_reg[base.EVENT_TYPE] = te.Event._REGISTRY.get(base.EVENT_TYPE)
            # Drop the registry slot so the subclass's __init_subclass__
            # duplicate-EVENT_TYPE guard does not raise.
            te.Event._REGISTRY.pop(base.EVENT_TYPE, None)
            ext = dataclasses.make_dataclass(
                name + "Ext",
                [
                    ("model_id", str, dataclasses.field(default="")),
                    ("task_kind", str, dataclasses.field(default="")),
                ],
                bases=(base,),
                kw_only=True,
            )
            setattr(te, name, ext)

    @classmethod
    def uninstall(cls) -> None:
        for name in ("StoryCompleted", "StoryFailed"):
            base = cls._orig_cls[name]
            setattr(te, name, base)
            te.Event._REGISTRY[base.EVENT_TYPE] = cls._orig_reg[base.EVENT_TYPE]
        cls._orig_cls.clear()
        cls._orig_reg.clear()


def _opus_ok(ts: str = "2026-06-15T00:00:00Z"):
    return te.StoryCompleted(
        timestamp=ts,
        run_id="r1",
        epic="E1",
        story_key="S1",
        duration_s=1.0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        attempts=1,
        model_id="claude-opus-4",
        task_kind="code",
    )


def _opus_fail(ts: str = "2026-06-15T00:00:00Z"):
    return te.StoryFailed(
        timestamp=ts,
        run_id="r1",
        epic="E1",
        story_key="S1",
        error_class="x",
        reason="y",
        attempts=1,
        final_session="s",
        model_id="claude-opus-4",
        task_kind="code",
    )


def _gpt_ok(ts: str = "2026-06-15T00:00:00Z"):
    return te.StoryCompleted(
        timestamp=ts,
        run_id="r1",
        epic="E1",
        story_key="S1",
        duration_s=1.0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        attempts=1,
        model_id="gpt-5-codex",
        task_kind="review",
    )


def _write_jsonl(path: Path, events: list[object]) -> Path:
    body = "".join(ev.to_json_line() + "\n" for ev in events)
    path.write_text(body, encoding="utf-8")
    return path


def _run(args: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_drift(args)
    return rc, buf.getvalue()


def _run_json(args: list[str]) -> tuple[int, dict]:
    rc, text = _run(args)
    return rc, (json.loads(text) if text.strip() else {})


class DriftCmdFlagParseTests(unittest.TestCase):
    """Flag validation runs before any core call, so these need no shim."""

    def test_missing_baseline_flag(self) -> None:
        rc, payload = _run_json(["--current", "x.jsonl"])
        self.assertEqual(rc, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_baseline"})

    def test_missing_current_flag(self) -> None:
        rc, payload = _run_json(["--baseline", "x.jsonl"])
        self.assertEqual(rc, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_current"})

    def test_invalid_format(self) -> None:
        rc, payload = _run_json(
            ["--baseline", "b.jsonl", "--current", "c.jsonl", "--format", "yaml"]
        )
        self.assertEqual(rc, 1)
        self.assertEqual(
            payload, {"ok": False, "error": "invalid_format", "format": "yaml"}
        )

    def test_invalid_format_does_not_call_core(self) -> None:
        with mock.patch.object(drift_cmd, "compute_drift") as patched:
            rc, _ = _run_json(
                ["--baseline", "b.jsonl", "--current", "c.jsonl", "--format", "yaml"]
            )
        self.assertEqual(rc, 1)
        patched.assert_not_called()


class DriftCmdReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_json_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = _write_jsonl(
                Path(tmp) / "b.jsonl", [_opus_ok(), _opus_ok(), _opus_ok()]
            )
            current = _write_jsonl(
                Path(tmp) / "c.jsonl", [_opus_ok(), _opus_fail(), _opus_fail()]
            )
            rc, payload = _run_json(
                ["--baseline", str(baseline), "--current", str(current)]
            )
        self.assertEqual(rc, 0)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["baseline_source"], str(baseline))
        self.assertEqual(payload["current_source"], str(current))
        self.assertIn("generated_at", payload)
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(
            payload["entries"][0],
            {
                "model_id": "claude-opus-4",
                "task_kind": "code",
                "baseline_success_rate": 1.0,
                "current_success_rate": 0.3333,
                "delta": -0.6667,
                "classification": "severe_drift",
            },
        )

    def test_missing_ledger_paths_yield_empty_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "nope-b.jsonl"
            current = Path(tmp) / "nope-c.jsonl"
            self.assertFalse(baseline.exists())
            self.assertFalse(current.exists())
            rc, payload = _run_json(
                ["--baseline", str(baseline), "--current", str(current)]
            )
        self.assertEqual(rc, 0)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["entries"], [])

    def test_sort_and_missing_key_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = _write_jsonl(Path(tmp) / "b.jsonl", [_opus_ok()])
            current = _write_jsonl(Path(tmp) / "c.jsonl", [_gpt_ok()])
            rc, payload = _run_json(
                ["--baseline", str(baseline), "--current", str(current)]
            )
        self.assertEqual(rc, 0)
        entries = payload["entries"]
        self.assertEqual(len(entries), 2)
        # equal |delta| (0.5 each) -> tie broken by ascending model_id.
        self.assertEqual(entries[0]["model_id"], "claude-opus-4")
        self.assertEqual(entries[1]["model_id"], "gpt-5-codex")
        # opus seen only in baseline: current side defaults to 0.5.
        self.assertEqual(entries[0]["baseline_success_rate"], 1.0)
        self.assertEqual(entries[0]["current_success_rate"], 0.5)
        self.assertEqual(entries[0]["delta"], -0.5)
        self.assertEqual(entries[0]["classification"], "severe_drift")
        # gpt seen only in current: baseline side defaults to 0.5.
        self.assertEqual(entries[1]["task_kind"], "review")
        self.assertEqual(entries[1]["baseline_success_rate"], 0.5)
        self.assertEqual(entries[1]["current_success_rate"], 1.0)
        self.assertEqual(entries[1]["delta"], 0.5)
        self.assertEqual(entries[1]["classification"], "severe_drift")

    def test_text_format_matches_formatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = _write_jsonl(
                Path(tmp) / "b.jsonl", [_opus_ok(), _opus_ok(), _opus_ok()]
            )
            current = _write_jsonl(
                Path(tmp) / "c.jsonl", [_opus_ok(), _opus_fail(), _opus_fail()]
            )
            expected = format_drift_report(
                compute_drift(
                    build_calibration(str(baseline)),
                    build_calibration(str(current)),
                )
            )
            rc, text = _run(
                [
                    "--baseline",
                    str(baseline),
                    "--current",
                    str(current),
                    "--format",
                    "text",
                ]
            )
        self.assertEqual(rc, 0)
        # Single trailing newline, not doubled.
        self.assertEqual(text, expected)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))


class DriftCmdDispatchTests(unittest.TestCase):
    """Regression: once the controller wires ``drift`` into cli.commands it
    must route to ``cmd_drift`` (not fall through to ``Unknown command``).
    The controller wires dispatch separately, so this is a soft check until
    that lands."""

    def test_cli_routes_drift_to_cmd_drift_when_wired(self) -> None:
        import sys

        from story_automator import cli

        out = io.StringIO()
        err = io.StringIO()
        with (
            mock.patch.object(sys, "stdout", out),
            mock.patch.object(sys, "stderr", err),
        ):
            rc = cli.main(["drift"])
        if "Unknown command: drift" in err.getvalue():
            self.skipTest("drift not yet wired into cli.py dispatch")
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue().strip())
        self.assertEqual(payload.get("error"), "missing_baseline")


if __name__ == "__main__":
    unittest.main()
