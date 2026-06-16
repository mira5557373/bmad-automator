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
            {
                "Classification",
                "Confidence",
                "FailureClass",
                "IMPLIES_GRAPH",
                "classify",
                "classify_stream",
            },
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


class ClassifyStoryFailedTests(unittest.TestCase):
    def _make_event(self, *, reason: str, error_class: str = "") -> object:
        from story_automator.core.telemetry_events import StoryFailed

        return StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class=error_class,
            reason=reason,
            attempts=1,
            final_session="sess",
        )

    def test_timeout_substring_returns_timeout_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="job timeout after 600s"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_policy_substring_returns_policy_violation_high_implies_review(
        self,
    ) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="policy refusal: PII"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_guardrail_substring_returns_policy_violation(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="guardrail tripped on output"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)

    def test_test_substring_returns_test_failure_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="unit test assertion failed"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_pytest_substring_returns_test_failure(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="pytest exit code 1"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)

    def test_parse_substring_returns_parse_error_medium(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="failed to parse model output"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_json_substring_returns_parse_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="invalid json payload"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)

    def test_refused_substring_returns_agent_refused_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="agent refused to write code"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_refusal_substring_returns_agent_refused(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="model refusal at turn 3"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)

    def test_budget_substring_returns_budget_exceeded_implies_gate_defer(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="budget cap hit at 110%"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_cost_substring_returns_budget_exceeded(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="cost exceeded epic cap"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)

    def test_unmatched_reason_returns_unknown_low(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="ambient disk pressure"))
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)

    def test_error_class_field_is_inspected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # `reason` is empty; the signal lives on the `error_class` M01
        # field (spec said `error_kind` but M01 names it `error_class`).
        result = classify(self._make_event(reason="", error_class="timeout"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)

    def test_implementation_chooses_timeout_when_both_substrings_present(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 LISTS its substring rules in declaration order but
        # does not literally mandate that order as runtime precedence
        # when multiple substrings co-occur. This test pins the M07b
        # implementation's choice (rules applied in REQ-08 declaration
        # order — timeout first) so a future spec amendment that
        # re-orders the rules has a known regression test to update.
        # Do not delete this test without updating the spec preamble.
        result = classify(self._make_event(reason="timeout policy"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)

    def test_error_kind_injected_attribute_is_inspected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 names the second inspected field `error_kind`;
        # M01 ships `error_class`. The classifier defensively reads
        # BOTH names so the spec-named field still works when injected
        # by a downstream caller (or by a future M01 schema update).
        # This test locks in the `error_kind` injection path so it
        # cannot be silently removed and so the coverage gate sees it.
        event = self._make_event(reason="", error_class="")
        event.error_kind = "budget"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)

    def test_substring_match_is_not_word_bounded_pinned_behaviour(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 specifies *substring* matching, not word-boundary
        # matching. As a documented consequence, `"latest"` matches the
        # `"test"` rule and classifies as TEST_FAILURE. This is the
        # spec's chosen behaviour; tightening to word boundaries would
        # require adding `re` to the M07a import allowlist. This test
        # pins the substring behaviour so the spec change is deliberate.
        result = classify(self._make_event(reason="latest model build"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)


class ClassifyTmuxCrashTests(unittest.TestCase):
    def _make_event(self, *, exit_code: int = 137) -> object:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        return TmuxSessionCrashed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            session_name="sess",
            story_key="S1",
            exit_code=exit_code,
            last_capture_chars=0,
        )

    def test_plain_crash_returns_crash_high_no_implies(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_sigpipe_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        # Spec REQ-09 references an ``exit_signal`` field; M01 does not
        # define one. The M01 dataclass is not frozen and not slotted,
        # so injecting the spec field via setattr is sound.
        event.exit_signal = "SIGPIPE"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_sighup_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "SIGHUP"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_network_substring_in_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "network-unreachable"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_unrelated_exit_signal_does_not_imply_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "SIGTERM"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertNotIn(FailureClass.NETWORK_ERROR, result.implies)


class ClassifyStoryDeferredTests(unittest.TestCase):
    def _make_event(
        self, *, reason: str = "complexity cap", tasks_completed: int = 2
    ) -> object:
        from story_automator.core.telemetry_events import StoryDeferred

        return StoryDeferred(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            reason=reason,
            tasks_completed=tasks_completed,
        )

    def test_default_returns_gate_defer_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_plateau_substring_returns_repeated_retry_implies_plateau(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="plateau detected after 3 cycles"))
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_attempt_count_over_three_returns_repeated_retry_implies_plateau(
        self,
    ) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        # Spec REQ-10 names ``attempt_count`` but M01 ships
        # ``tasks_completed`` only. Inject the spec field via setattr.
        event.attempt_count = 4  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)

    def test_attempt_count_three_does_not_trip_plateau_branch(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.attempt_count = 3  # type: ignore[attr-defined]
        result = classify(event)
        # Spec REQ-10 says "exceeds 3" — 3 itself stays in the default branch.
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)


class ClassifyEscalationTests(unittest.TestCase):
    def _make_event(self) -> object:
        from story_automator.core.telemetry_events import EscalationTriggered

        return EscalationTriggered(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            trigger_id=1,
            severity="warn",
            message="manual review requested",
        )

    def test_default_returns_review_rejected_medium(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_policy_trigger_prefix_upgrades_to_policy_violation_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._make_event()
        # Spec REQ-11 names a ``trigger`` field; M01 has ``trigger_id``
        # (int) and ``severity``/``message`` (strings) only. Inject the
        # spec field on the otherwise-mutable dataclass instance.
        event.trigger = "policy:pii_leak"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_non_policy_trigger_stays_review_rejected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.trigger = "review:manual"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)


class ClassifyStreamTests(unittest.TestCase):
    def test_classify_stream_is_a_generator_function(self) -> None:
        import inspect

        from story_automator.core.failure_triage import classify_stream

        self.assertTrue(inspect.isgeneratorfunction(classify_stream))

    def test_classify_stream_yields_one_classification_per_event(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            FailureClass,
            classify_stream,
        )
        from story_automator.core.telemetry_events import (
            StoryDeferred,
            StoryFailed,
            StoryStarted,
            TmuxSessionCrashed,
        )

        events = [
            StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S1",
                agent="dev",
                model="claude-opus-4-7",
                complexity="medium",
            ),
            StoryFailed(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S2",
                error_class="",
                reason="timeout 600s",
                attempts=1,
                final_session="sess",
            ),
            StoryDeferred(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S3",
                reason="plateau",
                tasks_completed=1,
            ),
            TmuxSessionCrashed(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                session_name="sess",
                story_key="S4",
                exit_code=137,
                last_capture_chars=0,
            ),
        ]
        results = list(classify_stream(events))
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIsInstance(r, Classification)
        self.assertEqual(results[0].primary, FailureClass.UNKNOWN)
        self.assertEqual(results[1].primary, FailureClass.TIMEOUT)
        self.assertEqual(results[2].primary, FailureClass.REPEATED_RETRY)
        self.assertEqual(results[3].primary, FailureClass.CRASH)

    def test_classify_stream_does_not_buffer_lazy_iteration(self) -> None:
        from story_automator.core.failure_triage import classify_stream
        from story_automator.core.telemetry_events import StoryStarted

        consumed: list[int] = []

        def source() -> object:
            for i in range(3):
                consumed.append(i)
                yield StoryStarted(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    epic="E1",
                    story_key=f"S{i}",
                    agent="dev",
                    model="claude-opus-4-7",
                    complexity="medium",
                )

        gen = classify_stream(source())
        # Nothing consumed yet.
        self.assertEqual(consumed, [])
        next(gen)
        self.assertEqual(consumed, [0])
        next(gen)
        self.assertEqual(consumed, [0, 1])

    def test_classify_stream_propagates_iterator_exception(self) -> None:
        from story_automator.core.failure_triage import classify_stream

        class Boom(RuntimeError):
            pass

        def source() -> object:
            yield from ()
            raise Boom("source exploded")

        gen = classify_stream(source())
        with self.assertRaises(Boom):
            list(gen)


class ThirteenClassBehaviouralMatrixTests(unittest.TestCase):
    """One test per ``FailureClass`` member — REQ-14 acceptance matrix.

    Each test asserts on ``primary``, on the membership of the expected
    entries in ``implies``, and on ``confidence`` (REQ-15). No I/O, no
    ``compact_json`` call, no clock read.
    """

    def _story_failed(self, *, reason: str) -> object:
        from story_automator.core.telemetry_events import StoryFailed

        return StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class="",
            reason=reason,
            attempts=1,
            final_session="sess",
        )

    def _story_deferred(self, *, reason: str = "complexity cap") -> object:
        from story_automator.core.telemetry_events import StoryDeferred

        return StoryDeferred(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            reason=reason,
            tasks_completed=1,
        )

    def _tmux_crashed(self) -> object:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        return TmuxSessionCrashed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            session_name="sess",
            story_key="S1",
            exit_code=137,
            last_capture_chars=0,
        )

    def _escalation(self) -> object:
        from story_automator.core.telemetry_events import EscalationTriggered

        return EscalationTriggered(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            trigger_id=1,
            severity="warn",
            message="m",
        )

    def test_crash_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._tmux_crashed())
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertEqual(result.implies, ())  # REQ-15: implies membership asserted
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_timeout_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="timeout 600s"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_policy_violation_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="policy refusal"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_review_rejected_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._escalation())
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_test_failure_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="pytest failure"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_budget_exceeded_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="budget cap"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_parse_error_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="parse error"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_agent_refused_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="agent refused"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_network_error_implied_on_tmux_crash(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._tmux_crashed()
        event.exit_signal = "SIGPIPE"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_gate_defer_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_deferred())
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_plateau_implied_on_story_deferred(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_deferred(reason="plateau"))
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_repeated_retry_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._story_deferred()
        event.attempt_count = 7  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_unknown_primary_on_non_failure_event(self) -> None:
        from story_automator.core.failure_triage import (
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
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)


class DeterminismGateTests(unittest.TestCase):
    def test_classify_is_byte_identical_over_100_runs(self) -> None:
        """Determinism quality gate — REQ-15-adjacent.

        Classify the same synthetic event 100 times and assert every
        result is structurally equal *and* produces a byte-identical
        ``repr()``. Guards against accidental nondeterminism from set
        iteration or dict ordering inside any future implies-aggregation
        logic.
        """
        from story_automator.core.failure_triage import classify
        from story_automator.core.telemetry_events import StoryFailed

        event = StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class="",
            reason="policy guardrail tripped on PII",
            attempts=3,
            final_session="sess",
        )
        first = classify(event)
        first_repr = repr(first)
        for _ in range(99):
            other = classify(event)
            self.assertEqual(other, first)
            self.assertEqual(repr(other), first_repr)

    def test_classify_stream_is_byte_identical_over_100_runs(self) -> None:
        """Same gate as above but for the stream path."""
        from story_automator.core.failure_triage import classify_stream
        from story_automator.core.telemetry_events import (
            StoryDeferred,
            TmuxSessionCrashed,
        )

        def make_events() -> list[object]:
            return [
                StoryDeferred(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    epic="E1",
                    story_key="S1",
                    reason="plateau",
                    tasks_completed=1,
                ),
                TmuxSessionCrashed(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    session_name="sess",
                    story_key="S1",
                    exit_code=137,
                    last_capture_chars=0,
                ),
            ]

        first = list(classify_stream(make_events()))
        first_repr = [repr(c) for c in first]
        for _ in range(99):
            other = list(classify_stream(make_events()))
            self.assertEqual(other, first)
            self.assertEqual([repr(c) for c in other], first_repr)
