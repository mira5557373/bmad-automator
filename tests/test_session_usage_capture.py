"""Tests for :mod:`story_automator.core.innovation.session_usage_capture`.

C3 closing milestone — verifies the auto-capture adapter that bridges
on-disk CLI transcripts to :class:`UsageMetrics` and ultimately to
:func:`story_automator.core.gate_orchestrator.run_production_gate`'s
``session_usage`` parameter.

Test groups:

* Group 1 — unit tests around :func:`capture_session_usage`.
* Group 2 — tmux convenience wrapper.
* Group 3 — end-to-end: capture -> run_production_gate ->
  ``gate_file["cost_total_usd"]`` populated.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import CollectorConfig, CollectorOutcome
from story_automator.core.innovation.session_usage_capture import (
    SessionUsageCapture,
    SessionUsageCaptureError,
    capture_session_usage,
    capture_session_usage_for_tmux,
)
from story_automator.core.usage_parsers import (
    KNOWN_PARSERS,
    UsageMetrics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _claude_jsonl_blob(input_tokens: int = 1000, output_tokens: int = 250) -> str:
    """Minimal Claude Code JSONL transcript with one result-with-usage entry."""

    return json.dumps(
        {
            "type": "result",
            "message": {
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            },
        }
    ) + "\n"


def _write_fixture(tmp: Path, name: str, contents: str) -> Path:
    path = tmp / name
    path.write_text(contents, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Group 1 — capture_session_usage unit tests
# ---------------------------------------------------------------------------


class CaptureSessionUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_capture_known_parsers_set_closed(self) -> None:
        # Mirrors the contract test in test_usage_parsers.py — the
        # session-usage-capture surface must accept exactly the four
        # cli_ids documented by KNOWN_PARSERS, no more.
        self.assertEqual(
            set(KNOWN_PARSERS.keys()),
            {"claude-code", "codex", "gemini-cli", "none"},
        )

    def test_capture_uses_correct_parser_per_cli_id(self) -> None:
        # Each of the four cli_ids must accept an empty transcript
        # without raising and return a UsageMetrics zero (the only
        # cross-parser invariant — token counts differ by dialect).
        for cli_id in sorted(KNOWN_PARSERS):
            path = _write_fixture(self.root, f"empty-{cli_id}.txt", "")
            result = capture_session_usage(cli_id, path)
            self.assertEqual(result.cli_id, cli_id)
            self.assertEqual(result.usage, UsageMetrics())
            # parser_id is downgraded to the runtime sentinel when
            # usage is zero — see module docstring for why.
            self.assertEqual(result.parser_id, "none")

    def test_capture_unknown_cli_id_raises(self) -> None:
        path = _write_fixture(self.root, "any.txt", "")
        with self.assertRaises(SessionUsageCaptureError):
            capture_session_usage("openai-gpt", path)
        with self.assertRaises(SessionUsageCaptureError):
            capture_session_usage("", path)

    def test_capture_missing_file_raises(self) -> None:
        # Loud failure — silently returning zeros would hide
        # misconfiguration.
        missing = self.root / "does-not-exist.jsonl"
        with self.assertRaises(SessionUsageCaptureError):
            capture_session_usage("claude-code", missing)

    def test_capture_directory_path_raises(self) -> None:
        # The capture path must point at a regular file; a directory
        # should raise the same loud error as a missing file.
        with self.assertRaises(SessionUsageCaptureError):
            capture_session_usage("claude-code", self.root)

    def test_capture_empty_file_returns_zero_usage(self) -> None:
        path = _write_fixture(self.root, "empty.jsonl", "")
        result = capture_session_usage("claude-code", path)
        self.assertEqual(result.usage, UsageMetrics())
        self.assertEqual(result.bytes_read, 0)
        # Empty file -> parser_id downgrades to the runtime sentinel.
        self.assertEqual(result.parser_id, "none")

    def test_capture_synthetic_claude_jsonl_produces_real_usage(self) -> None:
        path = _write_fixture(
            self.root,
            "session.jsonl",
            _claude_jsonl_blob(input_tokens=1000, output_tokens=250),
        )
        result = capture_session_usage("claude-code", path)
        self.assertEqual(result.usage.input_tokens, 1000)
        self.assertEqual(result.usage.output_tokens, 250)
        # parser_id stays at the real dialect when usage is non-zero.
        self.assertEqual(result.parser_id, "claude-jsonl")
        # Cost is positive because the Claude parser computes it.
        self.assertGreater(result.usage.total_cost_usd, 0.0)

    def test_capture_corrupt_jsonl_returns_zero_usage_no_crash(self) -> None:
        # A mix of malformed JSON, empty lines, and non-dict entries
        # must all be skipped silently — never raise.
        corrupt = "\n".join(
            [
                "not json",
                "{",
                "[1, 2, 3]",
                '"just a string"',
                "42",
            ]
        )
        path = _write_fixture(self.root, "corrupt.jsonl", corrupt)
        result = capture_session_usage("claude-code", path)
        self.assertEqual(result.usage, UsageMetrics())
        # bytes_read still reflects what was on disk.
        self.assertGreater(result.bytes_read, 0)
        self.assertEqual(result.parser_id, "none")

    def test_capture_returns_frozen_dataclass(self) -> None:
        path = _write_fixture(self.root, "empty.txt", "")
        result = capture_session_usage("none", path)
        self.assertIsInstance(result, SessionUsageCapture)
        with self.assertRaises(FrozenInstanceError):
            result.cli_id = "mutated"  # type: ignore[misc]

    def test_capture_source_path_preserved(self) -> None:
        path = _write_fixture(self.root, "session.jsonl", _claude_jsonl_blob())
        result = capture_session_usage("claude-code", path)
        # Compare resolved-form to handle macOS /private/var symlink, etc.
        self.assertEqual(result.source_path, path.resolve())

    def test_capture_bytes_read_matches_file_size(self) -> None:
        contents = _claude_jsonl_blob(input_tokens=1234, output_tokens=567)
        path = _write_fixture(self.root, "session.jsonl", contents)
        result = capture_session_usage("claude-code", path)
        self.assertEqual(result.bytes_read, path.stat().st_size)

    def test_capture_accepts_string_path(self) -> None:
        # Sanity check: callers passing a str path (e.g. from a config
        # dict) get the same behavior as a Path.
        path = _write_fixture(self.root, "session.jsonl", _claude_jsonl_blob())
        result = capture_session_usage("claude-code", str(path))
        self.assertEqual(result.usage.input_tokens, 1000)


# ---------------------------------------------------------------------------
# Group 2 — tmux convenience wrapper
# ---------------------------------------------------------------------------


class CaptureForTmuxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_capture_for_tmux_convenience(self) -> None:
        # Stub tmux_runtime.session_paths to point at a transcript we
        # control. Confirms the wrapper composes the two APIs.
        contents = _claude_jsonl_blob(input_tokens=2000, output_tokens=500)
        output_path = _write_fixture(self.root, "session-out.txt", contents)

        from story_automator.core import tmux_runtime as tmux_module
        from story_automator.core.tmux_runtime import SessionPaths

        fake_paths = SessionPaths(
            state=self.root / "state.json",
            command=self.root / "cmd.sh",
            runner=self.root / "runner.sh",
            output=output_path,
        )

        with patch.object(
            tmux_module, "session_paths", return_value=fake_paths,
        ) as mocked:
            result = capture_session_usage_for_tmux(
                "sa-test-e1-s1-1-build",
                cli_id="claude-code",
                project_root=str(self.root),
            )
            mocked.assert_called_once()

        self.assertEqual(result.usage.input_tokens, 2000)
        self.assertEqual(result.cli_id, "claude-code")
        self.assertEqual(result.parser_id, "claude-jsonl")

    def test_capture_for_tmux_default_cli_id_is_claude_code(self) -> None:
        # The convenience wrapper defaults cli_id to "claude-code"
        # because that is the production dialect. Verify by passing
        # only the session name.
        path = _write_fixture(
            self.root, "session-out.txt", _claude_jsonl_blob(),
        )
        from story_automator.core import tmux_runtime as tmux_module
        from story_automator.core.tmux_runtime import SessionPaths

        fake_paths = SessionPaths(
            state=self.root / "state.json",
            command=self.root / "cmd.sh",
            runner=self.root / "runner.sh",
            output=path,
        )
        with patch.object(
            tmux_module, "session_paths", return_value=fake_paths,
        ):
            result = capture_session_usage_for_tmux(
                "sa-test-e1-s1-1-build",
                project_root=str(self.root),
            )
        self.assertEqual(result.cli_id, "claude-code")

    def test_capture_for_tmux_unknown_cli_id_raises_before_tmux_call(
        self,
    ) -> None:
        # Validation happens BEFORE the tmux_runtime call so a typo
        # doesn't waste a session_paths() lookup.
        from story_automator.core import tmux_runtime as tmux_module

        with patch.object(tmux_module, "session_paths") as mocked:
            with self.assertRaises(SessionUsageCaptureError):
                capture_session_usage_for_tmux(
                    "sa-test", cli_id="openai-gpt",
                )
            mocked.assert_not_called()


# ---------------------------------------------------------------------------
# Group 3 — end-to-end: capture -> run_production_gate
# ---------------------------------------------------------------------------


def _make_outcome(
    collector_id: str,
    category: str,
    *,
    duration_ms: int = 1000,
    status: str = "ok",
) -> CollectorOutcome:
    """Build a minimal CollectorOutcome — mirrors test_cost_evidence.py."""

    config = CollectorConfig(
        collector_id=collector_id,
        tool="tool-" + collector_id,
        category=category,
        build_cmd=lambda checkout, profile: [],
    )
    evidence: dict[str, Any] = {
        "collector": collector_id,
        "tool": "tool-" + collector_id,
        "category": category,
        "status": status,
        "duration_ms": duration_ms,
        "tool_calls_count": 0,
    }
    return CollectorOutcome(config=config, evidence=evidence)


def _run_minimal_gate(
    project_root: Path,
    gate_id: str,
    *,
    session_usage: UsageMetrics | None = None,
) -> dict[str, Any]:
    """Drive run_production_gate through patched collaborators.

    Mirrors the helper in tests/test_cost_evidence.py so the end-to-end
    test wires capture -> run_production_gate without a real subprocess
    or git checkout.
    """

    from story_automator.core import gate_orchestrator

    target = {"kind": "story", "id": "S-1"}
    profile = {"id": "test", "version": 1}
    commit_sha = "deadbeef" * 5
    factory_version = "test-v1"

    fake_outcomes = [
        _make_outcome("ruff", "static", duration_ms=1000),
        _make_outcome("mypy", "static", duration_ms=2000),
    ]
    fake_gate_file: dict[str, Any] = {
        "gate_id": gate_id,
        "commit_sha": commit_sha,
        "overall": "PASS",
        "categories": {},
    }

    with (
        patch.object(gate_orchestrator, "assert_host_context"),
        patch.object(gate_orchestrator, "run_cleanup_janitor"),
        patch.object(
            gate_orchestrator,
            "_recover_from_crash_locked",
            return_value=({"recovered": False}, []),
        ),
        patch.object(
            gate_orchestrator, "check_gate_reuse", return_value=(None, ""),
        ),
        patch.object(gate_orchestrator, "write_gate_marker"),
        patch.object(gate_orchestrator, "clear_gate_marker"),
        patch.object(
            gate_orchestrator,
            "_run_collectors",
            return_value=fake_outcomes,
        ),
        patch.object(
            gate_orchestrator, "evaluate_gate", return_value=fake_gate_file,
        ),
        patch.object(gate_orchestrator, "compute_profile_hash", return_value="h"),
        patch(
            "story_automator.core.evidence_cache."
            "cached_load_evidence_bundle",
            return_value=[],
        ),
        patch(
            "story_automator.core.innovation.lineage_ledger.load_lineage_root",
            return_value="",
        ),
    ):
        kwargs: dict[str, Any] = {}
        if session_usage is not None:
            kwargs["session_usage"] = session_usage
        return gate_orchestrator.run_production_gate(
            project_root, gate_id,
            commit_sha=commit_sha, target=target,
            profile=profile, factory_version=factory_version,
            registry=None,  # type: ignore[arg-type]  # patched _run_collectors
            **kwargs,
        )


class EndToEndCaptureToGateTests(unittest.TestCase):
    """Group 3 — capture a synthetic transcript and feed it into the gate.

    Mirrors the orchestrator wiring tests in tests/test_cost_evidence.py
    but drives the input via the public capture API rather than building
    UsageMetrics by hand. This is the actual contract the milestone
    promises: a caller with a transcript on disk can light up
    ``cost_total_usd`` end-to-end.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_end_to_end_capture_then_run_production_gate(self) -> None:
        # Synthesize a Claude JSONL transcript, capture it, then drive
        # run_production_gate with the result.
        transcript = _claude_jsonl_blob(input_tokens=10_000, output_tokens=2_500)
        transcript_path = _write_fixture(
            self.root, "session-out.jsonl", transcript,
        )
        capture = capture_session_usage("claude-code", transcript_path)
        self.assertGreater(capture.usage.total_cost_usd, 0.0)

        gate_file = _run_minimal_gate(
            self.root, "g-e2e-1", session_usage=capture.usage,
        )
        # Contract: cost_total_usd is present on the gate file.
        self.assertIn("cost_total_usd", gate_file)
        # And the cost evidence files were emitted.
        cost_dir = self.root / "_bmad" / "gate" / "cost" / "g-e2e-1"
        self.assertTrue(cost_dir.is_dir())
        self.assertTrue((cost_dir / "summary.json").is_file())

    def test_gate_file_cost_total_usd_populated_from_captured_usage(
        self,
    ) -> None:
        # The cost on the gate file should equal the captured cost
        # (the orchestrator distributes by duration but the total is
        # preserved — see emit_gate_cost_report contract).
        transcript = _claude_jsonl_blob(input_tokens=5_000, output_tokens=1_000)
        transcript_path = _write_fixture(
            self.root, "session-out.jsonl", transcript,
        )
        capture = capture_session_usage("claude-code", transcript_path)
        gate_file = _run_minimal_gate(
            self.root, "g-e2e-2", session_usage=capture.usage,
        )
        self.assertAlmostEqual(
            gate_file["cost_total_usd"],
            capture.usage.total_cost_usd,
            places=6,
        )

    def test_capture_with_zero_session_usage_emits_zero_shares(self) -> None:
        # A capture from an empty transcript yields zero UsageMetrics;
        # feeding that into the gate still produces a cost report
        # (zeros all the way down) — the orchestrator's contract is
        # "best-effort emission", not "skip on zero".
        empty_path = _write_fixture(self.root, "empty.jsonl", "")
        capture = capture_session_usage("claude-code", empty_path)
        self.assertEqual(capture.usage, UsageMetrics())

        gate_file = _run_minimal_gate(
            self.root, "g-e2e-zero", session_usage=capture.usage,
        )
        self.assertIn("cost_total_usd", gate_file)
        self.assertEqual(gate_file["cost_total_usd"], 0.0)
        cost_dir = self.root / "_bmad" / "gate" / "cost" / "g-e2e-zero"
        self.assertTrue(cost_dir.is_dir())
        summary = json.loads((cost_dir / "summary.json").read_text())
        self.assertEqual(summary["total_cost_usd"], 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
