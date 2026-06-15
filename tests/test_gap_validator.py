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
        from story_automator.core import gap_validator  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import gap_validator

        self.assertEqual(
            sorted(gap_validator.__all__),
            sorted(
                [
                    "Gap",
                    "GapStatus",
                    "ValidationReport",
                    "parse_gap_list",
                    "validate_gaps",
                ]
            ),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        # Force a fresh import in an isolated stream environment.
        sys.modules.pop("story_automator.core.gap_validator", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import gap_validator  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import gap_validator

        self.assertIsInstance(gap_validator.logger, logging.Logger)
        self.assertEqual(
            gap_validator.logger.name,
            "story_automator.core.gap_validator",
        )


class GapDataclassTests(unittest.TestCase):
    """REQ-01: frozen kw_only @dataclass with five fields."""

    def test_gap_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import Gap

        self.assertTrue(dataclasses.is_dataclass(Gap))
        params = Gap.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_gap_field_names_and_types(self) -> None:
        from story_automator.core.gap_validator import Gap

        fields = {f.name: f.type for f in dataclasses.fields(Gap)}
        self.assertEqual(
            sorted(fields.keys()),
            ["description", "file_path", "line", "severity", "symbol"],
        )

    def test_gap_construction_requires_keyword_args(self) -> None:
        from story_automator.core.gap_validator import Gap

        with self.assertRaises(TypeError):
            Gap("a", 1, "s", "d", "minor")  # type: ignore[misc]

    def test_gap_instances_are_immutable(self) -> None:
        from story_automator.core.gap_validator import Gap

        g = Gap(
            file_path="a.py",
            line=1,
            symbol="x",
            description="d",
            severity="minor",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            g.line = 2  # type: ignore[misc]

    def test_gap_does_not_subclass_other_dataclasses(self) -> None:
        # NFR: dataclasses must not subclass other dataclasses.
        from story_automator.core.gap_validator import Gap

        ancestors = [
            base for base in Gap.__mro__ if base is not Gap and base is not object
        ]
        for base in ancestors:
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"Gap unexpectedly inherits from dataclass {base!r}",
            )


class GapStatusDataclassTests(unittest.TestCase):
    """REQ-02: frozen kw_only @dataclass with six fields."""

    def test_gap_status_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import GapStatus

        self.assertTrue(dataclasses.is_dataclass(GapStatus))
        params = GapStatus.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_gap_status_field_names(self) -> None:
        from story_automator.core.gap_validator import GapStatus

        names = sorted(f.name for f in dataclasses.fields(GapStatus))
        self.assertEqual(
            names,
            [
                "confidence",
                "gap",
                "line_in_range",
                "notes",
                "path_exists",
                "symbol_present",
            ],
        )

    def test_gap_status_construction(self) -> None:
        from story_automator.core.gap_validator import Gap, GapStatus

        g = Gap(
            file_path="a.py",
            line=1,
            symbol="x",
            description="d",
            severity="minor",
        )
        s = GapStatus(
            gap=g,
            path_exists=True,
            line_in_range=True,
            symbol_present=True,
            confidence=0.95,
            notes=[],
        )
        self.assertIs(s.gap, g)
        self.assertEqual(s.notes, [])
        self.assertEqual(s.confidence, 0.95)


class ValidationReportDataclassTests(unittest.TestCase):
    """REQ-03: frozen kw_only @dataclass with three fields."""

    def test_validation_report_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import ValidationReport

        self.assertTrue(dataclasses.is_dataclass(ValidationReport))
        params = ValidationReport.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_validation_report_field_names(self) -> None:
        from story_automator.core.gap_validator import ValidationReport

        names = sorted(f.name for f in dataclasses.fields(ValidationReport))
        self.assertEqual(
            names,
            ["overall_confidence", "statuses", "validated_at"],
        )


class ParseGapListHappyPathTests(unittest.TestCase):
    """REQ-06: accepts {"gaps": [...]} and returns list[Gap]."""

    def test_parses_single_gap(self) -> None:
        from story_automator.core.gap_validator import Gap, parse_gap_list

        payload = """
        {
          "gaps": [
            {
              "file_path": "src/a.py",
              "line": 42,
              "symbol": "do_thing",
              "description": "missing nil check",
              "severity": "major"
            }
          ]
        }
        """
        gaps = parse_gap_list(payload)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(
            gaps[0],
            Gap(
                file_path="src/a.py",
                line=42,
                symbol="do_thing",
                description="missing nil check",
                severity="major",
            ),
        )

    def test_parses_empty_gap_list(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        gaps = parse_gap_list('{"gaps": []}')
        self.assertEqual(gaps, [])

    def test_parses_multiple_gaps_preserving_order(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = """{
          "gaps": [
            {"file_path": "a.py", "line": 1, "symbol": "x",
             "description": "d1", "severity": "blocker"},
            {"file_path": "b.py", "line": 2, "symbol": "y",
             "description": "d2", "severity": "minor"}
          ]
        }"""
        gaps = parse_gap_list(payload)
        self.assertEqual([g.file_path for g in gaps], ["a.py", "b.py"])
        self.assertEqual([g.severity for g in gaps], ["blocker", "minor"])


class ParseGapListErrorTests(unittest.TestCase):
    """REQ-06: precise field-locating ValueError on each malformed shape."""

    def test_rejects_non_object_top_level(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "top-level 'gaps' key"):
            parse_gap_list("[]")

    def test_rejects_missing_gaps_key(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "top-level 'gaps' key"):
            parse_gap_list('{"other": []}')

    def test_rejects_non_list_gaps_value(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "'gaps' must be a JSON array"):
            parse_gap_list('{"gaps": {}}')

    def test_rejects_non_object_gap_entry(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, r"gaps\[0\] must be a JSON object"):
            parse_gap_list('{"gaps": ["a string"]}')

    def test_rejects_missing_required_key_with_field_locator(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = '{"gaps": [{"file_path": "a", "line": 1, "symbol": "s", "description": "d"}]}'
        with self.assertRaisesRegex(
            ValueError, r"gaps\[0\] missing required key 'severity'"
        ):
            parse_gap_list(payload)

    def test_rejects_non_integer_line(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": "42", "symbol": "s",'
            ' "description": "d", "severity": "minor"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].line must be an integer"):
            parse_gap_list(payload)

    def test_rejects_boolean_line_even_though_bool_is_subclass_of_int(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": true, "symbol": "s",'
            ' "description": "d", "severity": "minor"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].line must be an integer"):
            parse_gap_list(payload)

    def test_rejects_unknown_severity(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": 1, "symbol": "s",'
            ' "description": "d", "severity": "catastrophic"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].severity must be one of"):
            parse_gap_list(payload)

    def test_malformed_json_raises_value_error(self) -> None:
        # json.JSONDecodeError is a ValueError, so callers catching
        # ValueError catch malformed JSON uniformly.
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaises(ValueError):
            parse_gap_list("{not json")
