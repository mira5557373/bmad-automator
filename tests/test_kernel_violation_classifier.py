"""Tests for ``core.innovation.kernel_classifier``.

The classifier inspects a story kernel — represented as either Markdown text
or an already-parsed ``{section_name: body}`` dict — and reports which of the
four closed violation categories it triggers:

* ``mixed-concerns`` — the kernel bundles multiple unrelated problem domains
  into a single brief (one Problem, many disjoint Capabilities).
* ``non-falsifiable`` — the Success signal has no measurable predicate
  (no numbers, no comparison, no observable threshold).
* ``solution-disguised`` — the Problem statement reads as an implementation
  spec, not a user pain (mentions specific tech, classes, or "we should
  add ..." patterns).
* ``vendor-soup`` — Constraints or Capabilities lock in multiple competing
  vendors / SaaS products without justification.

The module exposes a closed tuple ``VIOLATION_TYPES`` and a single
``classify_kernel(...)`` entry point that returns a list of
``KernelViolation`` records, in deterministic order (the order of
``VIOLATION_TYPES``).
"""

from __future__ import annotations

import unittest

from story_automator.core.innovation import kernel_classifier as kc


class ViolationTypesTests(unittest.TestCase):
    def test_violation_types_is_a_closed_tuple_of_exactly_four_strings(self) -> None:
        self.assertIsInstance(kc.VIOLATION_TYPES, tuple)
        self.assertEqual(
            kc.VIOLATION_TYPES,
            (
                "mixed-concerns",
                "non-falsifiable",
                "solution-disguised",
                "vendor-soup",
            ),
        )


class ClassifyKernelInputTests(unittest.TestCase):
    def test_rejects_non_string_non_mapping_input(self) -> None:
        with self.assertRaises(kc.KernelClassifierError):
            kc.classify_kernel(42)  # type: ignore[arg-type]

    def test_accepts_pre_parsed_mapping_and_returns_list(self) -> None:
        clean = {
            "Problem": "Operators lose audit context when reviewing failed runs.",
            "Capabilities": "- Surface the failing collector\n- Replay a single run",
            "Constraints": "Must run on Python 3.11+ stdlib only.",
            "Non-goals": "Not introducing a new web UI.",
            "Success signal": "Operators resolve 95% of failures in under 5 minutes.",
        }
        result = kc.classify_kernel(clean)
        self.assertIsInstance(result, list)
        # A well-formed kernel triggers none of the violation rules.
        self.assertEqual(result, [])

    def test_returns_deterministic_order_when_multiple_violations_fire(self) -> None:
        # Construct a brief that trips at least two distinct categories:
        # non-falsifiable success + vendor-soup constraints.
        bad = {
            "Problem": "Users want better insights.",
            "Capabilities": "- Dashboards\n- Alerts",
            "Constraints": (
                "Must integrate with Datadog, New Relic, Splunk, "
                "and Grafana Cloud."
            ),
            "Non-goals": "Not replacing the CRM.",
            "Success signal": "Users feel more confident.",
        }
        result = kc.classify_kernel(bad)
        codes = [v.code for v in result]
        # Deterministic order = VIOLATION_TYPES order; filter to the ones that fired.
        expected_order = [c for c in kc.VIOLATION_TYPES if c in codes]
        self.assertEqual(codes, expected_order)


class NonFalsifiableTests(unittest.TestCase):
    def test_vague_success_signal_is_flagged(self) -> None:
        bad = {
            "Problem": "Devs hate flaky tests.",
            "Capabilities": "- Quarantine flaky tests",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not redesigning the test runner.",
            "Success signal": "Developers feel happier.",
        }
        codes = [v.code for v in kc.classify_kernel(bad)]
        self.assertIn("non-falsifiable", codes)

    def test_measurable_success_signal_is_not_flagged(self) -> None:
        good = {
            "Problem": "Devs lose 30 min/week chasing flaky tests.",
            "Capabilities": "- Quarantine flaky tests",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not redesigning the test runner.",
            "Success signal": "Flaky-test debug time drops below 5 minutes per week.",
        }
        codes = [v.code for v in kc.classify_kernel(good)]
        self.assertNotIn("non-falsifiable", codes)

    def test_missing_success_signal_is_flagged_as_non_falsifiable(self) -> None:
        # A kernel that omits Success signal entirely cannot be falsified.
        bad = {
            "Problem": "Users want X.",
            "Capabilities": "- Do X",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not Y.",
        }
        codes = [v.code for v in kc.classify_kernel(bad)]
        self.assertIn("non-falsifiable", codes)


class SolutionDisguisedTests(unittest.TestCase):
    def test_problem_that_prescribes_implementation_is_flagged(self) -> None:
        bad = {
            "Problem": (
                "We should add a Redis cache in front of the Postgres queries "
                "to make things faster."
            ),
            "Capabilities": "- Cache reads",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not Y.",
            "Success signal": "p95 read latency drops below 10ms.",
        }
        codes = [v.code for v in kc.classify_kernel(bad)]
        self.assertIn("solution-disguised", codes)

    def test_problem_phrased_as_user_pain_is_not_flagged(self) -> None:
        good = {
            "Problem": (
                "Operators wait more than 30 seconds for the dashboard to load, "
                "which makes them skip incident review."
            ),
            "Capabilities": "- Faster dashboards",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not redesigning the dashboard.",
            "Success signal": "Dashboard p95 load time below 2 seconds.",
        }
        codes = [v.code for v in kc.classify_kernel(good)]
        self.assertNotIn("solution-disguised", codes)


class VendorSoupTests(unittest.TestCase):
    def test_constraints_naming_three_or_more_vendors_is_flagged(self) -> None:
        bad = {
            "Problem": "Operators lack visibility into deploys.",
            "Capabilities": "- Cross-deploy timeline",
            "Constraints": "Must integrate with Datadog, Splunk, and New Relic.",
            "Non-goals": "Not replacing the CRM.",
            "Success signal": "Deploy-to-detect time drops below 60 seconds.",
        }
        codes = [v.code for v in kc.classify_kernel(bad)]
        self.assertIn("vendor-soup", codes)

    def test_single_vendor_constraint_is_not_flagged(self) -> None:
        good = {
            "Problem": "Operators lack visibility into deploys.",
            "Capabilities": "- Cross-deploy timeline",
            "Constraints": "Must integrate with Datadog (the existing vendor).",
            "Non-goals": "Not replacing the CRM.",
            "Success signal": "Deploy-to-detect time drops below 60 seconds.",
        }
        codes = [v.code for v in kc.classify_kernel(good)]
        self.assertNotIn("vendor-soup", codes)


class MixedConcernsTests(unittest.TestCase):
    def test_unrelated_capability_groups_are_flagged(self) -> None:
        # Capabilities cover two clearly disjoint domains: auth and billing.
        bad = {
            "Problem": "We want to improve the product.",
            "Capabilities": (
                "- Add OAuth single-sign-on\n"
                "- Add monthly invoice generation\n"
                "- Rotate refresh tokens\n"
                "- Compute pro-rated charges\n"
                "- Add password reset emails\n"
                "- Reconcile Stripe webhooks\n"
            ),
            "Constraints": "Stdlib only.",
            "Non-goals": "Not Y.",
            "Success signal": "Auth + billing failures drop below 1%.",
        }
        codes = [v.code for v in kc.classify_kernel(bad)]
        self.assertIn("mixed-concerns", codes)

    def test_focused_capability_list_is_not_flagged(self) -> None:
        good = {
            "Problem": "Operators cannot tell which collector failed.",
            "Capabilities": (
                "- Surface the failing collector name\n"
                "- Surface the failing collector exit code\n"
                "- Surface the failing collector stderr tail\n"
            ),
            "Constraints": "Stdlib only.",
            "Non-goals": "Not redesigning the dashboard.",
            "Success signal": "Operators identify the failing collector in under 10 seconds.",
        }
        codes = [v.code for v in kc.classify_kernel(good)]
        self.assertNotIn("mixed-concerns", codes)


class ViolationRecordShapeTests(unittest.TestCase):
    def test_violation_record_carries_code_and_evidence(self) -> None:
        bad = {
            "Problem": "Users want X.",
            "Capabilities": "- Do X",
            "Constraints": "Stdlib only.",
            "Non-goals": "Not Y.",
            "Success signal": "Users feel happier.",
        }
        result = kc.classify_kernel(bad)
        self.assertTrue(result, "expected at least one violation")
        first = result[0]
        self.assertIn(first.code, kc.VIOLATION_TYPES)
        self.assertIsInstance(first.evidence, str)
        self.assertTrue(first.evidence, "evidence must be a non-empty string")


class MarkdownInputTests(unittest.TestCase):
    def test_classify_kernel_accepts_markdown_text(self) -> None:
        markdown = (
            "# Brief\n\n"
            "## Problem\n"
            "Operators lose 5 minutes per failure.\n\n"
            "## Capabilities\n"
            "- Surface failing collector\n\n"
            "## Constraints\n"
            "Stdlib only.\n\n"
            "## Non-goals\n"
            "Not redesigning the dashboard.\n\n"
            "## Success signal\n"
            "Operators resolve failures in under 60 seconds.\n"
        )
        result = kc.classify_kernel(markdown)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
