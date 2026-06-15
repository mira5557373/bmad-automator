from __future__ import annotations

import unittest
from pathlib import Path

from story_automator.core.common import compact_json
from story_automator.core.telemetry_events import (
    BudgetAlert,
    CostCharged,
    StoryStarted,
)
from tests._calibration_fixtures import (
    _ExtendedEventShim,
    _completed_line,
    _failed_line,
    _fixture_dir,
    _write_jsonl,
)


class ModuleSurfaceTests(unittest.TestCase):
    def test_all_symbols_exported(self) -> None:
        import story_automator.core.calibration as cal

        self.assertEqual(
            sorted(cal.__all__),
            sorted(
                [
                    "CalibrationEntry",
                    "CalibrationTable",
                    "build_calibration",
                    "lookup_success_rate",
                    "format_calibration_report",
                ]
            ),
        )

    def test_direct_imports_work(self) -> None:
        from story_automator.core.calibration import (
            CalibrationEntry,
            CalibrationTable,
            build_calibration,
            format_calibration_report,
            lookup_success_rate,
        )

        self.assertTrue(callable(build_calibration))
        self.assertTrue(callable(lookup_success_rate))
        self.assertTrue(callable(format_calibration_report))
        self.assertTrue(isinstance(CalibrationEntry, type))
        self.assertTrue(isinstance(CalibrationTable, type))


class CalibrationEntryShapeTests(unittest.TestCase):
    def test_construction_kw_only_and_frozen(self) -> None:
        from story_automator.core.calibration import CalibrationEntry

        entry = CalibrationEntry(
            model_id="claude-opus-4",
            task_kind="code",
            success_rate=0.8750,
            sample_count=8,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        self.assertEqual(entry.model_id, "claude-opus-4")
        self.assertEqual(entry.task_kind, "code")
        self.assertEqual(entry.success_rate, 0.8750)
        self.assertEqual(entry.sample_count, 8)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T12:00:00Z")

    def test_entry_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        from story_automator.core.calibration import CalibrationEntry

        entry = CalibrationEntry(
            model_id="m",
            task_kind="t",
            success_rate=0.5,
            sample_count=1,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        with self.assertRaises(FrozenInstanceError):
            entry.success_rate = 0.9  # type: ignore[misc]

    def test_entry_requires_kw_only(self) -> None:
        from story_automator.core.calibration import CalibrationEntry

        with self.assertRaises(TypeError):
            CalibrationEntry("m", "t", 0.5, 1, "2026-06-14T12:00:00Z")  # type: ignore[misc]


class CalibrationTableShapeTests(unittest.TestCase):
    def test_construction(self) -> None:
        from story_automator.core.calibration import CalibrationEntry, CalibrationTable

        entry = CalibrationEntry(
            model_id="m",
            task_kind="t",
            success_rate=0.5,
            sample_count=2,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        table = CalibrationTable(
            entries={("m", "t"): entry},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=2,
        )
        self.assertEqual(table.entries[("m", "t")], entry)
        self.assertEqual(table.generated_at, "2026-06-14T13:00:00Z")
        self.assertEqual(table.source_path, "/tmp/telemetry.jsonl")
        self.assertEqual(table.total_events_scanned, 2)

    def test_table_is_kw_only_mutable(self) -> None:
        from story_automator.core.calibration import CalibrationTable

        table = CalibrationTable(
            entries={},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/empty.jsonl",
            total_events_scanned=0,
        )
        table.total_events_scanned = 5
        self.assertEqual(table.total_events_scanned, 5)

        with self.assertRaises(TypeError):
            CalibrationTable({}, "x", "y", 0)  # type: ignore[misc]


class BuildCalibrationMissingPathTests(unittest.TestCase):
    def test_missing_path_returns_empty_table_without_raising(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            missing = tmpdir / "does-not-exist.jsonl"
            table = build_calibration(missing)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 0)
        self.assertEqual(table.source_path, str(missing))
        self.assertTrue(table.generated_at.endswith("Z"))


class BuildCalibrationEmptyAndIgnoredTests(unittest.TestCase):
    def test_empty_file_returns_empty_table(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            ledger.write_text("", encoding="utf-8")
            table = build_calibration(ledger)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 0)
        self.assertEqual(table.source_path, str(ledger))

    def test_unrelated_event_types_are_counted_but_not_aggregated(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            started = StoryStarted(
                timestamp="2026-06-14T10:00:00Z",
                run_id="r1",
                epic="EP-1",
                story_key="S-1",
                agent="ag",
                model="claude-opus-4",
                complexity="M",
            )
            cost = CostCharged(
                timestamp="2026-06-14T10:01:00Z",
                run_id="r1",
                epic="EP-1",
                story_key="S-1",
                phase="impl",
                cost_usd=0.12,
                tokens_in=1000,
                tokens_out=200,
                model="claude-opus-4",
            )
            budget = BudgetAlert(
                timestamp="2026-06-14T10:02:00Z",
                run_id="r1",
                threshold_pct=50,
                total_cost_usd=5.0,
                max_budget_usd=10.0,
                epic="EP-1",
                story_key="S-1",
            )
            _write_jsonl(
                ledger,
                [compact_json(e.to_dict()) for e in (started, cost, budget)],
            )
            table = build_calibration(ledger)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 3)
        self.assertEqual(table.source_path, str(ledger))


class BuildCalibrationAggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_single_completed_yields_success_rate_one(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            line = _completed_line(
                "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
            )
            _write_jsonl(ledger, [line])
            table = build_calibration(ledger)

        self.assertEqual(table.total_events_scanned, 1)
        self.assertEqual(set(table.entries.keys()), {("claude-opus-4", "code")})
        entry = table.entries[("claude-opus-4", "code")]
        self.assertEqual(entry.success_rate, 1.0)
        self.assertEqual(entry.sample_count, 1)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T10:00:00Z")

    def test_single_failed_yields_success_rate_zero(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            line = _failed_line(
                "2026-06-14T11:00:00Z", "r1", "S-2", "claude-sonnet-4-5", "review"
            )
            _write_jsonl(ledger, [line])
            table = build_calibration(ledger)

        entry = table.entries[("claude-sonnet-4-5", "review")]
        self.assertEqual(entry.success_rate, 0.0)
        self.assertEqual(entry.sample_count, 1)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T11:00:00Z")


class BuildCalibrationMixedAggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_mixed_completed_and_failed_for_same_key_rounds_to_four_places(
        self,
    ) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            lines = [
                _completed_line(
                    "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
                ),
                _completed_line(
                    "2026-06-14T11:00:00Z", "r2", "S-2", "claude-opus-4", "code"
                ),
                _failed_line(
                    "2026-06-14T12:00:00Z", "r3", "S-3", "claude-opus-4", "code"
                ),
            ]
            _write_jsonl(ledger, lines)
            table = build_calibration(ledger)

        entry = table.entries[("claude-opus-4", "code")]
        self.assertEqual(entry.success_rate, 0.6667)
        self.assertEqual(entry.sample_count, 3)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T12:00:00Z")
        self.assertEqual(table.total_events_scanned, 3)

    def test_last_seen_iso_picks_lexicographic_max(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            lines = [
                _completed_line("2026-06-14T15:00:00Z", "r1", "S-1", "m", "t"),
                _completed_line("2026-06-14T09:00:00Z", "r2", "S-2", "m", "t"),
                _failed_line("2026-06-14T12:00:00Z", "r3", "S-3", "m", "t"),
            ]
            _write_jsonl(ledger, lines)
            table = build_calibration(ledger)

        entry = table.entries[("m", "t")]
        self.assertEqual(entry.last_seen_iso, "2026-06-14T15:00:00Z")

    def test_two_distinct_keys_aggregate_independently(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            lines = [
                _completed_line(
                    "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
                ),
                _failed_line(
                    "2026-06-14T10:01:00Z", "r2", "S-2", "claude-opus-4", "code"
                ),
                _completed_line(
                    "2026-06-14T10:02:00Z", "r3", "S-3", "gpt-5-codex", "review"
                ),
                _completed_line(
                    "2026-06-14T10:03:00Z", "r4", "S-4", "gpt-5-codex", "review"
                ),
            ]
            _write_jsonl(ledger, lines)
            table = build_calibration(ledger)

        self.assertEqual(
            set(table.entries.keys()),
            {("claude-opus-4", "code"), ("gpt-5-codex", "review")},
        )
        opus = table.entries[("claude-opus-4", "code")]
        gpt = table.entries[("gpt-5-codex", "review")]
        self.assertEqual(opus.success_rate, 0.5)
        self.assertEqual(opus.sample_count, 2)
        self.assertEqual(opus.last_seen_iso, "2026-06-14T10:01:00Z")
        self.assertEqual(gpt.success_rate, 1.0)
        self.assertEqual(gpt.sample_count, 2)
        self.assertEqual(gpt.last_seen_iso, "2026-06-14T10:03:00Z")
        self.assertEqual(table.total_events_scanned, 4)


class BuildCalibrationParsingTolerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_crlf_line_endings_and_trailing_blanks_are_tolerated(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            line1 = _completed_line("2026-06-14T10:00:00Z", "r1", "S-1", "m", "t")
            line2 = _completed_line("2026-06-14T10:01:00Z", "r2", "S-2", "m", "t")
            ledger.write_bytes(
                (line1 + "\r\n" + line2 + "\r\n" + "\r\n").encode("utf-8")
            )
            table = build_calibration(ledger)

        entry = table.entries[("m", "t")]
        self.assertEqual(entry.sample_count, 2)
        self.assertEqual(table.total_events_scanned, 2)

    def test_unknown_event_type_is_counted_but_skipped(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            unknown = compact_json(
                {
                    "event_type": "future_event_kind",
                    "timestamp": "2026-06-14T13:00:00Z",
                    "run_id": "r1",
                    "some_field": 42,
                }
            )
            good = _completed_line("2026-06-14T10:00:00Z", "r1", "S-1", "m", "t")
            _write_jsonl(ledger, [unknown, good])
            table = build_calibration(ledger)

        self.assertEqual(table.total_events_scanned, 2)
        self.assertEqual(set(table.entries.keys()), {("m", "t")})

    def test_non_string_model_id_or_task_kind_is_skipped(self) -> None:
        from story_automator.core.calibration import build_calibration
        from story_automator.core.telemetry_events import StoryCompleted

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            good = _completed_line(
                "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
            )
            base = StoryCompleted(
                timestamp="2026-06-14T10:01:00Z",
                run_id="r2",
                epic="EP-1",
                story_key="S-2",
                duration_s=10.0,
                cost_usd=0.1,
                tokens_in=10,
                tokens_out=10,
                attempts=1,
            ).to_dict()
            bad_model = dict(base)
            bad_model["model_id"] = 42
            bad_model["task_kind"] = "code"
            bad_task = dict(base)
            bad_task["model_id"] = "claude-opus-4"
            bad_task["task_kind"] = None
            _write_jsonl(
                ledger,
                [good, compact_json(bad_model), compact_json(bad_task)],
            )
            table = build_calibration(ledger)

        self.assertEqual(table.total_events_scanned, 3)
        self.assertEqual(set(table.entries.keys()), {("claude-opus-4", "code")})
        self.assertEqual(table.entries[("claude-opus-4", "code")].sample_count, 1)


class BuildCalibrationMalformedLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_malformed_json_line_is_skipped_without_counting(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            good = _completed_line(
                "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
            )
            ledger.write_text(
                "\n".join(["{not json", good, "[1, 2, 3]"]) + "\n",
                encoding="utf-8",
            )
            table = build_calibration(ledger)

        self.assertEqual(set(table.entries.keys()), {("claude-opus-4", "code")})
        self.assertEqual(table.entries[("claude-opus-4", "code")].sample_count, 1)
        self.assertEqual(table.total_events_scanned, 1)

    def test_json_object_missing_event_type_is_skipped(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            good = _completed_line("2026-06-14T10:00:00Z", "r1", "S-1", "m", "t")
            from story_automator.core.common import compact_json as _cj

            no_type = _cj({"timestamp": "2026-06-14T11:00:00Z", "run_id": "r2"})
            _write_jsonl(ledger, [no_type, good])
            table = build_calibration(ledger)

        self.assertEqual(set(table.entries.keys()), {("m", "t")})
        self.assertEqual(table.total_events_scanned, 1)


class LookupSuccessRateTests(unittest.TestCase):
    def _make_table(self):
        from story_automator.core.calibration import CalibrationEntry, CalibrationTable

        entry = CalibrationEntry(
            model_id="claude-opus-4",
            task_kind="code",
            success_rate=0.8750,
            sample_count=8,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        return CalibrationTable(
            entries={("claude-opus-4", "code"): entry},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/t.jsonl",
            total_events_scanned=8,
        )

    def test_hit_returns_stored_rate(self) -> None:
        from story_automator.core.calibration import lookup_success_rate

        table = self._make_table()
        self.assertEqual(lookup_success_rate(table, "claude-opus-4", "code"), 0.8750)

    def test_miss_returns_default_0_5(self) -> None:
        from story_automator.core.calibration import lookup_success_rate

        table = self._make_table()
        self.assertEqual(lookup_success_rate(table, "gpt-5-codex", "code"), 0.5)
        self.assertEqual(lookup_success_rate(table, "claude-opus-4", "docs"), 0.5)

    def test_miss_returns_custom_default(self) -> None:
        from story_automator.core.calibration import lookup_success_rate

        table = self._make_table()
        self.assertEqual(
            lookup_success_rate(table, "unknown", "unknown", default=0.123),
            0.123,
        )


class FormatCalibrationReportTests(unittest.TestCase):
    def test_empty_table_emits_header_and_trailing_newline(self) -> None:
        from story_automator.core.calibration import (
            CalibrationTable,
            format_calibration_report,
        )

        table = CalibrationTable(
            entries={},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=0,
        )
        text = format_calibration_report(table)

        expected = (
            "source: /tmp/telemetry.jsonl\n"
            "model_id\ttask_kind\tsuccess_rate\tsample_count\tlast_seen_iso\n"
        )
        self.assertEqual(text, expected)

    def test_rows_sorted_by_model_id_then_task_kind(self) -> None:
        from story_automator.core.calibration import (
            CalibrationEntry,
            CalibrationTable,
            format_calibration_report,
        )

        entries = {
            ("claude-sonnet-4-5", "review"): CalibrationEntry(
                model_id="claude-sonnet-4-5",
                task_kind="review",
                success_rate=0.5000,
                sample_count=4,
                last_seen_iso="2026-06-14T10:00:00Z",
            ),
            ("claude-opus-4", "code"): CalibrationEntry(
                model_id="claude-opus-4",
                task_kind="code",
                success_rate=0.8750,
                sample_count=8,
                last_seen_iso="2026-06-14T11:00:00Z",
            ),
            ("claude-opus-4", "docs"): CalibrationEntry(
                model_id="claude-opus-4",
                task_kind="docs",
                success_rate=1.0000,
                sample_count=2,
                last_seen_iso="2026-06-14T12:00:00Z",
            ),
        }
        table = CalibrationTable(
            entries=entries,
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=14,
        )
        text = format_calibration_report(table)

        expected = (
            "source: /tmp/telemetry.jsonl\n"
            "model_id\ttask_kind\tsuccess_rate\tsample_count\tlast_seen_iso\n"
            "claude-opus-4\tcode\t0.8750\t8\t2026-06-14T11:00:00Z\n"
            "claude-opus-4\tdocs\t1.0000\t2\t2026-06-14T12:00:00Z\n"
            "claude-sonnet-4-5\treview\t0.5000\t4\t2026-06-14T10:00:00Z\n"
        )
        self.assertEqual(text, expected)

    def test_report_is_plain_ascii(self) -> None:
        from story_automator.core.calibration import (
            CalibrationEntry,
            CalibrationTable,
            format_calibration_report,
        )

        entries = {
            ("m", "t"): CalibrationEntry(
                model_id="m",
                task_kind="t",
                success_rate=0.6667,
                sample_count=3,
                last_seen_iso="2026-06-14T12:00:00Z",
            ),
        }
        table = CalibrationTable(
            entries=entries,
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/t.jsonl",
            total_events_scanned=3,
        )
        text = format_calibration_report(table)
        text.encode("ascii")


if __name__ == "__main__":
    unittest.main()
