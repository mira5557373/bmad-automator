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


if __name__ == "__main__":
    unittest.main()
