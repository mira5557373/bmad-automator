from __future__ import annotations

import dataclasses
import io
import logging
import sys
import unittest


class ModuleImportContractTests(unittest.TestCase):
    """REQ-16: importable in any order, no import-time side effects beyond
    logging.getLogger(__name__), declares __all__."""

    def test_module_imports_cleanly(self) -> None:
        from story_automator.core import feature_tester  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import feature_tester

        self.assertEqual(
            sorted(feature_tester.__all__),
            sorted(["TestPlanEntry", "plan_feature_tests"]),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        sys.modules.pop("story_automator.core.feature_tester", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import feature_tester  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import feature_tester

        self.assertIsInstance(feature_tester.logger, logging.Logger)
        self.assertEqual(
            feature_tester.logger.name,
            "story_automator.core.feature_tester",
        )

    def test_module_does_not_import_spec_compliance_at_runtime(self) -> None:
        """REQ-16 / quality gate: no runtime cross-layer imports."""
        sys.modules.pop("story_automator.core.feature_tester", None)
        sys.modules.pop("story_automator.core.spec_compliance", None)
        from story_automator.core import feature_tester  # noqa: F401

        self.assertNotIn("story_automator.core.spec_compliance", sys.modules)

    def test_module_does_not_import_gap_validator_at_runtime(self) -> None:
        sys.modules.pop("story_automator.core.feature_tester", None)
        sys.modules.pop("story_automator.core.gap_validator", None)
        from story_automator.core import feature_tester  # noqa: F401

        self.assertNotIn("story_automator.core.gap_validator", sys.modules)


class TestPlanEntryDataclassTests(unittest.TestCase):
    """REQ-12: frozen kw_only @dataclass with four fields."""

    def test_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        self.assertTrue(dataclasses.is_dataclass(TestPlanEntry))
        params = TestPlanEntry.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_does_not_subclass_other_dataclass(self) -> None:
        """NFR: dataclasses must not subclass other dataclasses."""
        from story_automator.core.feature_tester import TestPlanEntry

        for base in TestPlanEntry.__mro__[1:]:
            if base is object:
                continue
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"{TestPlanEntry.__name__} must not subclass dataclass {base.__name__}",
            )

    def test_has_required_fields(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        field_map = {f.name: f.type for f in dataclasses.fields(TestPlanEntry)}
        self.assertEqual(
            set(field_map),
            {"req_id", "existing_test_path", "created_test_path", "action"},
        )

    def test_positional_construction_rejected(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        with self.assertRaises(TypeError):
            TestPlanEntry("REQ-07", None, None, "found")  # type: ignore[misc]

    def test_kw_construction_round_trips(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        entry = TestPlanEntry(
            req_id="REQ-07",
            existing_test_path="tests/test_compliance_req_07.py",
            created_test_path=None,
            action="found",
        )
        self.assertEqual(entry.req_id, "REQ-07")
        self.assertEqual(entry.action, "found")

    def test_frozen_rejects_attribute_assignment(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        entry = TestPlanEntry(
            req_id="REQ-07",
            existing_test_path=None,
            created_test_path="tests/test_compliance_req_07.py",
            action="created",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.action = "skipped"  # type: ignore[misc]


class NormalizeReqIdTests(unittest.TestCase):
    """Internal helper: normalizes REQ-NN into its three rendered forms."""

    def test_normalizes_well_formed_id(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        underscored_lower, class_suffix = _normalize_req_id("REQ-07")
        self.assertEqual(underscored_lower, "req_07")
        self.assertEqual(class_suffix, "REQ_07")

    def test_normalizes_multi_digit_id(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        underscored_lower, class_suffix = _normalize_req_id("REQ-123")
        self.assertEqual(underscored_lower, "req_123")
        self.assertEqual(class_suffix, "REQ_123")

    def test_rejects_lowercase_prefix(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError) as ctx:
            _normalize_req_id("req-07")
        self.assertIn("REQ-", str(ctx.exception))

    def test_rejects_missing_dash(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("REQ07")

    def test_rejects_empty_string(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("")

    def test_rejects_trailing_whitespace(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("REQ-07 ")


# Golden skeleton for REQ-07. ANY change to _SKELETON_TEMPLATE must
# update this string verbatim — that's the entire point of the
# byte-equality assertion.
_GOLDEN_SKELETON_REQ_07 = (
    '"""Feature test for REQ-07."""\n'
    "\n"
    "from __future__ import annotations\n"
    "\n"
    "import unittest\n"
    "\n"
    "\n"
    "class TestComplianceREQ_07(unittest.TestCase):\n"
    '    """REQ-07: skeleton — fill in once the feature is wired."""\n'
    "\n"
    "    def test_req_07_skeleton(self) -> None:\n"
    '        self.fail("REQ-07 not yet covered by feature test")\n'
)


class SkeletonRenderGoldenTests(unittest.TestCase):
    """REQ-14 + quality gate: byte-equality against a frozen golden string."""

    def test_render_matches_golden_for_req_07(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-07")
        self.assertEqual(rendered, _GOLDEN_SKELETON_REQ_07)

    def test_render_contains_req_id_verbatim_in_class_docstring(self) -> None:
        """REQ-14: must place the REQ id verbatim in the class docstring."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-123")
        # The class docstring is the line beginning with `    """REQ-`
        self.assertIn('    """REQ-123: ', rendered)

    def test_render_imports_future_annotations(self) -> None:
        """REQ-14: must import from __future__ import annotations."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-07")
        self.assertIn("from __future__ import annotations\n", rendered)

    def test_render_calls_self_fail_with_exact_message(self) -> None:
        """REQ-14: body is exactly self.fail("REQ-NN not yet covered ...")."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-42")
        self.assertIn(
            '        self.fail("REQ-42 not yet covered by feature test")\n',
            rendered,
        )

    def test_render_method_name_uses_lower_underscored_id(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-42")
        self.assertIn("    def test_req_42_skeleton(self) -> None:\n", rendered)

    def test_render_rejects_malformed_req_id(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        with self.assertRaises(ValueError):
            _render_skeleton("not-a-req")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
