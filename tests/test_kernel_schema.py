from __future__ import annotations

import unittest

from story_automator.core.kernel_schema import (
    REQUIRED_H2_SECTIONS,
    KernelSchemaError,
    has_section,
    kernel_completeness_score,
    parse_kernel,
    validate_kernel,
)


FULL_KERNEL = """# Story Kernel

## Problem
Operators cannot tell whether a story is ready to enter the gate.

## Capabilities
- Validate kernel sections exist
- Score kernel completeness

## Constraints
- Must run with stdlib only.
- Must be deterministic.

## Non-goals
- Authoring the story body.

## Success signal
Kernel validation passes in CI without warnings.
"""


PARTIAL_KERNEL = """# Story Kernel

## Problem
Operators cannot tell whether a story is ready to enter the gate.

## Capabilities
- Validate kernel sections exist

## Constraints
- Must run with stdlib only.
"""


EMPTY_BODIES_KERNEL = """# Story Kernel

## Problem

## Capabilities

## Constraints

## Non-goals

## Success signal
"""


class RequiredH2SectionsTests(unittest.TestCase):
    def test_required_sections_is_tuple_and_exact(self) -> None:
        self.assertIsInstance(REQUIRED_H2_SECTIONS, tuple)
        self.assertEqual(
            REQUIRED_H2_SECTIONS,
            ("Problem", "Capabilities", "Constraints", "Non-goals", "Success signal"),
        )

    def test_required_sections_is_immutable(self) -> None:
        with self.assertRaises(AttributeError):
            REQUIRED_H2_SECTIONS.append("Other")  # type: ignore[attr-defined]

    def test_kernel_schema_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(KernelSchemaError, ValueError))


class ParseKernelTests(unittest.TestCase):
    def test_parse_full_kernel_returns_all_sections(self) -> None:
        sections = parse_kernel(FULL_KERNEL)
        self.assertIsInstance(sections, dict)
        for name in REQUIRED_H2_SECTIONS:
            self.assertIn(name, sections)
        self.assertIn(
            "Operators cannot tell", sections["Problem"]
        )
        self.assertIn("Validate kernel sections exist", sections["Capabilities"])

    def test_parse_strips_section_bodies(self) -> None:
        sections = parse_kernel(FULL_KERNEL)
        for body in sections.values():
            # Each parsed body is whitespace-trimmed at the ends.
            self.assertEqual(body, body.strip())

    def test_parse_partial_kernel_only_has_present_sections(self) -> None:
        sections = parse_kernel(PARTIAL_KERNEL)
        self.assertIn("Problem", sections)
        self.assertIn("Capabilities", sections)
        self.assertIn("Constraints", sections)
        self.assertNotIn("Non-goals", sections)
        self.assertNotIn("Success signal", sections)

    def test_parse_empty_bodies_map_to_empty_strings(self) -> None:
        sections = parse_kernel(EMPTY_BODIES_KERNEL)
        for name in REQUIRED_H2_SECTIONS:
            self.assertIn(name, sections)
            self.assertEqual(sections[name], "")

    def test_parse_kernel_rejects_non_string(self) -> None:
        with self.assertRaises(KernelSchemaError):
            parse_kernel(None)  # type: ignore[arg-type]
        with self.assertRaises(KernelSchemaError):
            parse_kernel(123)  # type: ignore[arg-type]

    def test_parse_kernel_ignores_h3_and_deeper(self) -> None:
        text = (
            "## Problem\nBody\n### Sub\nNot a top section\n"
            "## Capabilities\nCaps\n"
        )
        sections = parse_kernel(text)
        self.assertIn("Problem", sections)
        self.assertIn("Capabilities", sections)
        self.assertNotIn("Sub", sections)
        self.assertIn("### Sub", sections["Problem"])


class ValidateKernelTests(unittest.TestCase):
    def test_validate_full_kernel_returns_none(self) -> None:
        self.assertIsNone(validate_kernel(FULL_KERNEL))

    def test_validate_missing_section_raises(self) -> None:
        with self.assertRaises(KernelSchemaError) as ctx:
            validate_kernel(PARTIAL_KERNEL)
        self.assertIn("Non-goals", str(ctx.exception))

    def test_validate_empty_body_raises(self) -> None:
        with self.assertRaises(KernelSchemaError) as ctx:
            validate_kernel(EMPTY_BODIES_KERNEL)
        # At least one of the required sections is named in the error.
        msg = str(ctx.exception)
        self.assertTrue(any(name in msg for name in REQUIRED_H2_SECTIONS))

    def test_validate_rejects_non_string(self) -> None:
        with self.assertRaises(KernelSchemaError):
            validate_kernel(None)  # type: ignore[arg-type]


class HasSectionTests(unittest.TestCase):
    def test_has_section_true_for_present_section(self) -> None:
        self.assertTrue(has_section(FULL_KERNEL, "Problem"))
        self.assertTrue(has_section(FULL_KERNEL, "Success signal"))

    def test_has_section_false_for_missing_section(self) -> None:
        self.assertFalse(has_section(PARTIAL_KERNEL, "Non-goals"))
        self.assertFalse(has_section(PARTIAL_KERNEL, "Success signal"))

    def test_has_section_false_when_body_empty(self) -> None:
        # Empty body means section is "not really there" from a content
        # standpoint.
        self.assertFalse(has_section(EMPTY_BODIES_KERNEL, "Problem"))

    def test_has_section_rejects_non_string_text(self) -> None:
        with self.assertRaises(KernelSchemaError):
            has_section(None, "Problem")  # type: ignore[arg-type]

    def test_has_section_rejects_non_string_name(self) -> None:
        with self.assertRaises(KernelSchemaError):
            has_section(FULL_KERNEL, None)  # type: ignore[arg-type]


class KernelCompletenessScoreTests(unittest.TestCase):
    def test_full_kernel_scores_one(self) -> None:
        self.assertEqual(kernel_completeness_score(FULL_KERNEL), 1.0)

    def test_empty_kernel_scores_zero(self) -> None:
        self.assertEqual(kernel_completeness_score(""), 0.0)

    def test_partial_kernel_scores_proportionally(self) -> None:
        score = kernel_completeness_score(PARTIAL_KERNEL)
        # 3 of 5 sections present with non-empty bodies.
        self.assertAlmostEqual(score, 3 / 5)

    def test_empty_bodies_score_zero(self) -> None:
        # All H2 headings exist but every body is empty.
        self.assertEqual(kernel_completeness_score(EMPTY_BODIES_KERNEL), 0.0)

    def test_score_is_bounded(self) -> None:
        score = kernel_completeness_score(FULL_KERNEL)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_rejects_non_string(self) -> None:
        with self.assertRaises(KernelSchemaError):
            kernel_completeness_score(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
