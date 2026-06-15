from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import (
    BudgetAlert,
    CostCharged,
    StoryStarted,
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


@contextlib.contextmanager
def _fixture_dir():
    """REQ-14 compliant fixture directory.

    Creates the parent via `ensure_dir` before opening the
    `tempfile.TemporaryDirectory`. Yields a `pathlib.Path`.
    """
    parent = Path(tempfile.gettempdir()) / "m08_calibration_fixtures"
    ensure_dir(parent)
    with tempfile.TemporaryDirectory(dir=str(parent)) as tmpdir:
        yield Path(tmpdir)


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


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
