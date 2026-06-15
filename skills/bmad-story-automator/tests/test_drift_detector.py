from __future__ import annotations

import unittest

from story_automator.core.drift_detector import DriftClassification, DriftEntry


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


if __name__ == "__main__":
    unittest.main()
