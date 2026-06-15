from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
