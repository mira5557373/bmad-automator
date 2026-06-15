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


class ClassificationDataclassTests(unittest.TestCase):
    def test_classification_is_a_dataclass(self) -> None:
        from dataclasses import is_dataclass

        from story_automator.core.failure_triage import Classification

        self.assertTrue(is_dataclass(Classification))

    def test_classification_is_frozen(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        c = Classification(
            primary=FailureClass.UNKNOWN,
            implies=(),
            confidence=Confidence.LOW,
            reason="x",
            event_id=None,
        )
        with self.assertRaises(Exception):
            c.reason = "y"  # type: ignore[misc]

    def test_classification_field_names_and_order(self) -> None:
        from dataclasses import fields

        from story_automator.core.failure_triage import Classification

        names = [f.name for f in fields(Classification)]
        self.assertEqual(
            names,
            ["primary", "implies", "confidence", "reason", "event_id"],
        )

    def test_classification_field_types_are_pep604_strings(self) -> None:
        from dataclasses import fields

        from story_automator.core.failure_triage import Classification

        types_by_name = {f.name: f.type for f in fields(Classification)}
        self.assertEqual(types_by_name["primary"], "FailureClass")
        self.assertEqual(types_by_name["implies"], "tuple[FailureClass, ...]")
        self.assertEqual(types_by_name["confidence"], "Confidence")
        self.assertEqual(types_by_name["reason"], "str")
        self.assertEqual(types_by_name["event_id"], "str | None")

    def test_classification_requires_kw_only_construction(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        with self.assertRaises(TypeError):
            Classification(  # type: ignore[misc]
                FailureClass.UNKNOWN,
                (),
                Confidence.LOW,
                "x",
                None,
            )

    def test_classification_round_trip_construction(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        c = Classification(
            primary=FailureClass.POLICY_VIOLATION,
            implies=(FailureClass.REVIEW_REJECTED,),
            confidence=Confidence.HIGH,
            reason="guardrail tripped",
            event_id=None,
        )
        self.assertEqual(c.primary, FailureClass.POLICY_VIOLATION)
        self.assertEqual(c.implies, (FailureClass.REVIEW_REJECTED,))
        self.assertEqual(c.confidence, Confidence.HIGH)
        self.assertEqual(c.reason, "guardrail tripped")
        self.assertIsNone(c.event_id)


class ImpliesGraphTests(unittest.TestCase):
    def test_implies_graph_is_dict(self) -> None:
        from story_automator.core.failure_triage import IMPLIES_GRAPH

        self.assertIsInstance(IMPLIES_GRAPH, dict)

    def test_implies_graph_keys_are_failure_class_members(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        for key in IMPLIES_GRAPH:
            self.assertIsInstance(key, FailureClass)

    def test_implies_graph_values_are_tuples_of_failure_class(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        for value in IMPLIES_GRAPH.values():
            self.assertIsInstance(value, tuple)
            for member in value:
                self.assertIsInstance(member, FailureClass)

    def test_implies_graph_required_edges(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.POLICY_VIOLATION],
            (FailureClass.REVIEW_REJECTED,),
        )
        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.BUDGET_EXCEEDED],
            (FailureClass.GATE_DEFER,),
        )
        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.REPEATED_RETRY],
            (FailureClass.PLATEAU,),
        )

    def test_implies_graph_has_no_self_loops(self) -> None:
        from story_automator.core.failure_triage import IMPLIES_GRAPH

        for key, value in IMPLIES_GRAPH.items():
            self.assertNotIn(key, value)
