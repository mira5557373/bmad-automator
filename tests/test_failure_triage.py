from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import failure_triage  # noqa: F401


class FailureClassTests(unittest.TestCase):
    def test_failure_class_has_exactly_thirteen_members(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        self.assertEqual(len(list(FailureClass)), 13)

    def test_failure_class_members_in_declaration_order(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        expected = [
            "CRASH",
            "TIMEOUT",
            "POLICY_VIOLATION",
            "REVIEW_REJECTED",
            "TEST_FAILURE",
            "BUDGET_EXCEEDED",
            "PARSE_ERROR",
            "AGENT_REFUSED",
            "NETWORK_ERROR",
            "GATE_DEFER",
            "PLATEAU",
            "REPEATED_RETRY",
            "UNKNOWN",
        ]
        self.assertEqual([m.name for m in FailureClass], expected)

    def test_failure_class_values_equal_member_names(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        for member in FailureClass:
            self.assertEqual(member.value, member.name)

    def test_failure_class_is_str_enum_subclass(self) -> None:
        import enum

        from story_automator.core.failure_triage import FailureClass

        self.assertTrue(issubclass(FailureClass, enum.Enum))


class ConfidenceTests(unittest.TestCase):
    def test_confidence_members_are_high_medium_low(self) -> None:
        from story_automator.core.failure_triage import Confidence

        self.assertEqual([m.name for m in Confidence], ["HIGH", "MEDIUM", "LOW"])

    def test_confidence_values_equal_names(self) -> None:
        from story_automator.core.failure_triage import Confidence

        for member in Confidence:
            self.assertEqual(member.value, member.name)

    def test_confidence_is_case_sensitive_enum(self) -> None:
        import enum

        from story_automator.core.failure_triage import Confidence

        self.assertTrue(issubclass(Confidence, enum.Enum))
        with self.assertRaises(KeyError):
            Confidence["high"]
