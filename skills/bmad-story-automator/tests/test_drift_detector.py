from __future__ import annotations

import unittest

from story_automator.core.drift_detector import (
    MAJOR_MAX,
    MINOR_MAX,
    STABLE_MAX,
    DriftClassification,
    DriftEntry,
    DriftReport,
    _classify,
)


class DriftClassificationTests(unittest.TestCase):
    def test_members_and_order(self) -> None:
        self.assertEqual(
            [m.name for m in DriftClassification],
            ["STABLE", "MINOR_DRIFT", "MAJOR_DRIFT", "SEVERE_DRIFT"],
        )

    def test_values_equal_lowercase_names(self) -> None:
        for member in DriftClassification:
            self.assertEqual(member.value, member.name.lower())


class DriftEntryTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        entry = DriftEntry(
            model_id="gpt-4o-mini",
            task_kind="story",
            baseline_success_rate=0.80,
            current_success_rate=0.75,
            delta=round(0.75 - 0.80, 4),
            classification=DriftClassification.STABLE,
        )
        self.assertEqual(entry.model_id, "gpt-4o-mini")
        self.assertEqual(entry.task_kind, "story")
        self.assertEqual(entry.baseline_success_rate, 0.80)
        self.assertEqual(entry.current_success_rate, 0.75)
        self.assertEqual(entry.delta, -0.05)
        self.assertIs(entry.classification, DriftClassification.STABLE)

    def test_is_frozen(self) -> None:
        import dataclasses

        entry = DriftEntry(
            model_id="m",
            task_kind="t",
            baseline_success_rate=0.0,
            current_success_rate=0.0,
            delta=0.0,
            classification=DriftClassification.STABLE,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.model_id = "other"  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DriftEntry(  # type: ignore[call-arg]
                "m",
                "t",
                0.0,
                0.0,
                0.0,
                DriftClassification.STABLE,
            )


class DriftReportTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="/tmp/base.jsonl",
            current_source="/tmp/now.jsonl",
        )
        self.assertEqual(report.entries, [])
        self.assertEqual(report.generated_at, "2026-06-15T00:00:00Z")
        self.assertEqual(report.baseline_source, "/tmp/base.jsonl")
        self.assertEqual(report.current_source, "/tmp/now.jsonl")

    def test_entries_is_mutable_list(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="b",
            current_source="c",
        )
        report.entries.append(
            DriftEntry(
                model_id="m",
                task_kind="t",
                baseline_success_rate=0.0,
                current_success_rate=0.0,
                delta=0.0,
                classification=DriftClassification.STABLE,
            )
        )
        self.assertEqual(len(report.entries), 1)


class ClassifyHelperTests(unittest.TestCase):
    def test_zero_is_stable(self) -> None:
        self.assertIs(_classify(0.0), DriftClassification.STABLE)

    def test_just_below_stable_max_is_stable(self) -> None:
        self.assertIs(_classify(0.0499), DriftClassification.STABLE)
        self.assertIs(_classify(-0.0499), DriftClassification.STABLE)

    def test_stable_max_is_minor(self) -> None:
        self.assertIs(_classify(STABLE_MAX), DriftClassification.MINOR_DRIFT)
        self.assertIs(_classify(-STABLE_MAX), DriftClassification.MINOR_DRIFT)

    def test_just_below_minor_max_is_minor(self) -> None:
        self.assertIs(_classify(0.0999), DriftClassification.MINOR_DRIFT)

    def test_minor_max_is_major(self) -> None:
        self.assertIs(_classify(MINOR_MAX), DriftClassification.MAJOR_DRIFT)
        self.assertIs(_classify(-MINOR_MAX), DriftClassification.MAJOR_DRIFT)

    def test_just_below_major_max_is_major(self) -> None:
        self.assertIs(_classify(0.1999), DriftClassification.MAJOR_DRIFT)

    def test_major_max_is_severe(self) -> None:
        self.assertIs(_classify(MAJOR_MAX), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-MAJOR_MAX), DriftClassification.SEVERE_DRIFT)

    def test_large_magnitude_is_severe(self) -> None:
        self.assertIs(_classify(0.95), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-0.95), DriftClassification.SEVERE_DRIFT)

    def test_boundary_constants_match_spec(self) -> None:
        self.assertEqual(STABLE_MAX, 0.05)
        self.assertEqual(MINOR_MAX, 0.10)
        self.assertEqual(MAJOR_MAX, 0.20)


if __name__ == "__main__":
    unittest.main()
