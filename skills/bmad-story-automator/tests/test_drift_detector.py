from __future__ import annotations

import unittest

from story_automator.core.drift_detector import DriftClassification


class DriftClassificationTests(unittest.TestCase):
    def test_members_and_order(self) -> None:
        self.assertEqual(
            [m.name for m in DriftClassification],
            ["STABLE", "MINOR_DRIFT", "MAJOR_DRIFT", "SEVERE_DRIFT"],
        )

    def test_values_equal_lowercase_names(self) -> None:
        for member in DriftClassification:
            self.assertEqual(member.value, member.name.lower())


if __name__ == "__main__":
    unittest.main()
