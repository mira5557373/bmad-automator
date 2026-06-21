"""Tests for ``core/innovation/replay_diff.py`` — cross-CLI replay diff.

The replay-diff module is given evidence records produced by replaying the
same target_ref/collector across multiple CLIProfiles (e.g. claude-code,
codex, gemini-cli). It aligns those records into a (collector, target) ->
{cli -> record} table and reports verdict divergence with a closed status
vocabulary, so downstream tooling can spot CLI-specific factory drift
without re-running the full gate.
"""

from __future__ import annotations

import json
import unittest

from story_automator.core.innovation.replay_diff import (
    AGREEMENT,
    DIVERGENCE,
    MISSING_CLI,
    UNKNOWN_CLI,
    VALID_STATUSES,
    CLIProfileRef,
    EvidenceRecord,
    ReplayDiffError,
    ReplayDiffReport,
    ReplayDiffRow,
    align_records,
    format_report,
    replay_diff,
    verdict_divergence,
)


def _profiles() -> tuple[CLIProfileRef, ...]:
    return (
        CLIProfileRef(cli_id="claude-code", label="Claude Code"),
        CLIProfileRef(cli_id="codex", label="Codex"),
        CLIProfileRef(cli_id="gemini-cli", label="Gemini CLI"),
    )


def _rec(
    cli_id: str,
    collector_id: str,
    target_ref: str,
    verdict: str,
    *,
    evidence_hash: str = "h",
    exit_code: int = 0,
) -> EvidenceRecord:
    return EvidenceRecord(
        cli_id=cli_id,
        collector_id=collector_id,
        target_ref=target_ref,
        verdict=verdict,
        evidence_hash=evidence_hash,
        started_at="2026-06-21T00:00:00Z",
        ended_at="2026-06-21T00:00:01Z",
        exit_code=exit_code,
        attrs={},
    )


class AlignmentTests(unittest.TestCase):
    def test_alignment_groups_by_collector_and_target(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
            _rec("claude-code", "static", "story-1.1", "fail"),
            _rec("codex", "static", "story-1.1", "fail"),
        ]
        aligned = align_records(records, profiles)
        self.assertEqual(
            set(aligned.keys()),
            {("correctness", "story-1.1"), ("static", "story-1.1")},
        )
        correctness = aligned[("correctness", "story-1.1")]
        self.assertEqual(set(correctness.keys()), {"claude-code", "codex", "gemini-cli"})
        self.assertEqual(correctness["codex"].verdict, "pass")

    def test_duplicate_records_for_same_key_raise(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass", evidence_hash="a"),
            _rec("claude-code", "correctness", "story-1.1", "fail", evidence_hash="b"),
        ]
        with self.assertRaises(ReplayDiffError) as ctx:
            align_records(records, profiles)
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_unknown_cli_id_raises(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("not-a-cli", "correctness", "story-1.1", "pass"),
        ]
        with self.assertRaises(ReplayDiffError) as ctx:
            align_records(records, profiles)
        self.assertIn("not-a-cli", str(ctx.exception))


class DivergenceTests(unittest.TestCase):
    def test_full_agreement_reports_agreement(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
        ]
        aligned = align_records(records, profiles)
        rows = verdict_divergence(aligned, profiles)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.status, AGREEMENT)
        self.assertEqual(row.collector_id, "correctness")
        self.assertEqual(row.target_ref, "story-1.1")
        self.assertEqual(row.dominant_verdict, "pass")

    def test_divergence_reports_per_cli_verdicts(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "fail"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
        ]
        aligned = align_records(records, profiles)
        rows = verdict_divergence(aligned, profiles)
        self.assertEqual(rows[0].status, DIVERGENCE)
        self.assertEqual(
            rows[0].verdicts_by_cli,
            {"claude-code": "pass", "codex": "fail", "gemini-cli": "pass"},
        )
        # Dominant verdict is the majority; tie-break is alphabetical.
        self.assertEqual(rows[0].dominant_verdict, "pass")

    def test_missing_cli_reported(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            # gemini-cli intentionally missing
        ]
        aligned = align_records(records, profiles)
        rows = verdict_divergence(aligned, profiles)
        row = rows[0]
        self.assertEqual(row.status, MISSING_CLI)
        self.assertEqual(row.missing_clis, ("gemini-cli",))

    def test_row_sort_order_is_collector_then_target(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "static", "story-1.2", "pass"),
            _rec("codex", "static", "story-1.2", "pass"),
            _rec("gemini-cli", "static", "story-1.2", "pass"),
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
        ]
        aligned = align_records(records, profiles)
        rows = verdict_divergence(aligned, profiles)
        self.assertEqual(
            [(r.collector_id, r.target_ref) for r in rows],
            [("correctness", "story-1.1"), ("static", "story-1.2")],
        )


class ReportTests(unittest.TestCase):
    def test_replay_diff_report_summary_counts(self) -> None:
        profiles = _profiles()
        records = [
            # agreement
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
            # divergence
            _rec("claude-code", "static", "story-1.1", "pass"),
            _rec("codex", "static", "story-1.1", "fail"),
            _rec("gemini-cli", "static", "story-1.1", "pass"),
            # missing-cli
            _rec("claude-code", "docs", "story-1.1", "pass"),
            _rec("codex", "docs", "story-1.1", "pass"),
        ]
        report = replay_diff(records, profiles)
        self.assertIsInstance(report, ReplayDiffReport)
        self.assertEqual(report.total_rows(), 3)
        self.assertEqual(report.count(AGREEMENT), 1)
        self.assertEqual(report.count(DIVERGENCE), 1)
        self.assertEqual(report.count(MISSING_CLI), 1)
        self.assertEqual(
            report.cli_ids(), ("claude-code", "codex", "gemini-cli")
        )

    def test_replay_diff_to_dict_is_json_serializable(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "fail"),
        ]
        report = replay_diff(records, profiles)
        as_dict = report.to_dict()
        # Round-trip through JSON: must succeed.
        encoded = json.dumps(as_dict, sort_keys=True)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["summary"]["total_rows"], 1)
        self.assertEqual(decoded["summary"]["counts"][DIVERGENCE], 1)
        self.assertEqual(decoded["cli_ids"], ["claude-code", "codex", "gemini-cli"])
        self.assertEqual(decoded["rows"][0]["status"], DIVERGENCE)

    def test_format_report_text_contains_divergence_summary(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "fail"),
        ]
        report = replay_diff(records, profiles)
        text = format_report(report)
        self.assertIn("correctness", text)
        self.assertIn("story-1.1", text)
        self.assertIn(DIVERGENCE, text)


class ConstantsTests(unittest.TestCase):
    def test_valid_statuses_are_a_closed_set(self) -> None:
        self.assertEqual(
            set(VALID_STATUSES),
            {AGREEMENT, DIVERGENCE, MISSING_CLI, UNKNOWN_CLI},
        )

    def test_evidence_record_is_frozen(self) -> None:
        rec = _rec("claude-code", "correctness", "story-1.1", "pass")
        with self.assertRaises(Exception):
            rec.verdict = "fail"  # type: ignore[misc]

    def test_replay_diff_row_to_dict_includes_required_keys(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "pass"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
        ]
        aligned = align_records(records, profiles)
        rows = verdict_divergence(aligned, profiles)
        row_dict = rows[0].to_dict()
        for key in (
            "collector_id",
            "target_ref",
            "status",
            "dominant_verdict",
            "verdicts_by_cli",
            "missing_clis",
        ):
            self.assertIn(key, row_dict)
        self.assertIsInstance(rows[0], ReplayDiffRow)


class ValidationTests(unittest.TestCase):
    def test_empty_profile_list_raises(self) -> None:
        with self.assertRaises(ReplayDiffError):
            replay_diff([], ())

    def test_duplicate_profile_ids_raise(self) -> None:
        profiles = (
            CLIProfileRef(cli_id="claude-code", label="Claude"),
            CLIProfileRef(cli_id="claude-code", label="ClaudeDup"),
        )
        with self.assertRaises(ReplayDiffError):
            replay_diff([], profiles)

    def test_invalid_verdict_string_raises(self) -> None:
        profiles = _profiles()
        records = [
            _rec("claude-code", "correctness", "story-1.1", "MAYBE"),
            _rec("codex", "correctness", "story-1.1", "pass"),
            _rec("gemini-cli", "correctness", "story-1.1", "pass"),
        ]
        with self.assertRaises(ReplayDiffError) as ctx:
            replay_diff(records, profiles)
        self.assertIn("verdict", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
