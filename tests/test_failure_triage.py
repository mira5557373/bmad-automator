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

    def test_failure_class_is_enum_subclass(self) -> None:
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
        import dataclasses

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
        with self.assertRaises(dataclasses.FrozenInstanceError):
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


class TaxonomyCompletenessGateTests(unittest.TestCase):
    def test_exactly_thirteen_failure_class_members(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        self.assertEqual(
            len(list(FailureClass)),
            13,
            "FailureClass must have exactly 13 members; "
            "silent additions break downstream M08/M09/M10 contracts.",
        )

    def test_failure_class_member_set_matches_agreed_taxonomy(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        expected = {
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
        }
        self.assertEqual({m.name for m in FailureClass}, expected)

    def test_no_unresolved_four_letter_placeholder_tokens_in_source(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        forbidden = ("TODO", "FIXM", "XXXX", "HACK", "TKTK")
        for token in forbidden:
            self.assertNotIn(
                token,
                text,
                f"unresolved placeholder token {token!r} found in "
                f"{source_path}; resolve or remove before shipping.",
            )


class ImportAndSizeDisciplineTests(unittest.TestCase):
    def test_no_third_party_or_io_imports(self) -> None:
        import ast
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        allowed_roots = {"enum", "dataclasses", "typing", "collections"}
        allowed_local_prefixes = ("story_automator.core",)
        forbidden_roots = {
            "filelock",
            "psutil",
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "socket",
            "http",
            "urllib",
            "asyncio",
            "threading",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(root, forbidden_roots)
                    self.assertTrue(
                        root in allowed_roots
                        or alias.name.startswith(allowed_local_prefixes),
                        f"unexpected import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                self.assertNotIn(root, forbidden_roots)
                self.assertTrue(
                    root in allowed_roots
                    or module.startswith(allowed_local_prefixes)
                    or root == "__future__",
                    f"unexpected from-import: {module}",
                )

    def test_module_under_five_hundred_lines(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        line_count = len(source_path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"failure_triage.py has {line_count} lines; cap is 500.",
        )

    def test_future_annotations_on_first_non_comment_line(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        import ast

        tree = ast.parse(text)
        first_stmt = tree.body[0] if tree.body else None
        if (
            isinstance(first_stmt, ast.Expr)
            and isinstance(first_stmt.value, ast.Constant)
            and isinstance(first_stmt.value.value, str)
        ):
            first_stmt = tree.body[1] if len(tree.body) > 1 else None
        self.assertIsInstance(first_stmt, ast.ImportFrom)
        assert isinstance(first_stmt, ast.ImportFrom)
        self.assertEqual(first_stmt.module, "__future__")
        self.assertEqual(
            [alias.name for alias in first_stmt.names],
            ["annotations"],
        )

    def test_no_typing_optional_or_union(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        for token in ("Optional", "Union"):
            self.assertNotIn(
                token,
                text,
                f"forbidden typing alias {token!r} found in "
                f"{source_path}; use PEP 604 `X | Y` syntax instead.",
            )

    def test_lf_line_endings(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        raw = source_path.read_bytes()
        self.assertNotIn(
            b"\r\n",
            raw,
            f"{source_path} contains CRLF line endings; spec requires "
            f"LF under core.autocrlf=false. Re-save with LF endings.",
        )

    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {"Classification", "Confidence", "FailureClass", "IMPLIES_GRAPH"},
        )


class ClassifyDispatchSkeletonTests(unittest.TestCase):
    def test_classify_is_callable(self) -> None:
        from story_automator.core.failure_triage import classify

        self.assertTrue(callable(classify))

    def test_classify_returns_unknown_for_non_failure_event(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
            classify,
        )
        from story_automator.core.telemetry_events import StoryStarted

        event = StoryStarted(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            agent="dev",
            model="claude-opus-4-7",
            complexity="medium",
        )
        result = classify(event)
        self.assertIsInstance(result, Classification)
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)
        self.assertEqual(result.reason, "non_failure_event")
        self.assertIsNone(result.event_id)
