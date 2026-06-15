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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
