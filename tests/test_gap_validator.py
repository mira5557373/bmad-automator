from __future__ import annotations

import dataclasses
import io
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from story_automator.core.gap_validator import Gap


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


class ValidateGapsAggregationTests(unittest.TestCase):
    """REQ-03 + REQ-04: aggregate fields and base-confidence formula."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_empty_gap_list_returns_overall_confidence_one(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([], repo_root=self.root)
        self.assertEqual(report.statuses, [])
        self.assertEqual(report.overall_confidence, 1.0)
        self.assertRegex(report.validated_at, r"^\d{4}-\d{2}-\d{2}T")

    def test_overall_confidence_is_mean_of_per_gap_confidence(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        # Two gaps that both fail all three checks (no file exists in an
        # empty repo) → each gets base 0.8 → mean = 0.8.
        gaps = [
            Gap(
                file_path="missing_a.py",
                line=1,
                symbol="x",
                description="d",
                severity="minor",
            ),
            Gap(
                file_path="missing_b.py",
                line=1,
                symbol="y",
                description="d",
                severity="minor",
            ),
        ]
        report = validate_gaps(gaps, repo_root=self.root)
        self.assertEqual(len(report.statuses), 2)
        for status in report.statuses:
            self.assertFalse(status.path_exists)
            self.assertFalse(status.line_in_range)
            self.assertFalse(status.symbol_present)
            self.assertAlmostEqual(status.confidence, 0.8)
        self.assertAlmostEqual(report.overall_confidence, 0.8)


class PathExistsAndEscapeTests(unittest.TestCase):
    """REQ-04 (path_exists bonus) + REQ-05 (escape rejection)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def _gap(self, file_path: str) -> Gap:
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path=file_path,
            line=1,
            symbol="anything",
            description="d",
            severity="minor",
        )

    def test_relative_path_existing_inside_root_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

        report = validate_gaps([self._gap("src/a.py")], repo_root=self.root)
        self.assertTrue(report.statuses[0].path_exists)
        # The path-exists note must NOT appear when path_exists is True.
        joined = " | ".join(report.statuses[0].notes)
        self.assertNotIn("path does not exist", joined)

    def test_missing_relative_path_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("missing.py")], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("missing.py", joined)

    def test_absolute_path_outside_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        outside = self.root.parent / "definitely-outside.py"
        report = validate_gaps([self._gap(str(outside))], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("escapes repo_root", joined)

    def test_parent_traversal_escaping_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps(
            [self._gap("../../../etc/passwd")],
            repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].path_exists)

    def test_parent_traversal_resolving_inside_root_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

        report = validate_gaps(
            [self._gap("src/../src/a.py")],
            repo_root=self.root,
        )
        self.assertTrue(report.statuses[0].path_exists)

    @unittest.skipIf(os.name == "nt", "symlink creation requires admin on Windows")
    def test_symlink_pointing_outside_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        outside_dir = self.root.parent / "outside-symlink-target"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "leak.py"
        outside_file.write_text("secret = 1\n", encoding="utf-8")
        self.addCleanup(lambda: outside_file.unlink(missing_ok=True))
        self.addCleanup(lambda: outside_dir.rmdir())

        link = self.root / "leak.py"
        link.symlink_to(outside_file)

        report = validate_gaps([self._gap("leak.py")], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)


class LineInRangeTests(unittest.TestCase):
    """REQ-04: `line_in_range` is True iff 1 <= line <= number-of-lines."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "a.py").write_text(
            "line1\nline2\nline3\n",
            encoding="utf-8",
        )

    def _gap(self, line: int) -> Gap:
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path="a.py",
            line=line,
            symbol="anything",
            description="d",
            severity="minor",
        )

    def test_line_inside_range_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(2)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_at_lower_bound_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(1)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_at_upper_bound_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(3)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_zero_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(0)], repo_root=self.root)
        self.assertFalse(report.statuses[0].line_in_range)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("line 0", joined)

    def test_line_beyond_end_of_file_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(999)], repo_root=self.root)
        self.assertFalse(report.statuses[0].line_in_range)

    def test_missing_path_implies_line_not_in_range(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        report = validate_gaps(
            [
                Gap(
                    file_path="missing.py",
                    line=1,
                    symbol="x",
                    description="d",
                    severity="minor",
                )
            ],
            repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].line_in_range)


class SymbolPresentTests(unittest.TestCase):
    """REQ-04: `symbol_present` is True iff the literal symbol occurs in the source."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "a.py").write_text(
            "def do_thing():\n    return 42\n",
            encoding="utf-8",
        )

    def _gap(self, symbol: str) -> Gap:
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path="a.py",
            line=1,
            symbol=symbol,
            description="d",
            severity="minor",
        )

    def test_present_symbol_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("do_thing")], repo_root=self.root)
        self.assertTrue(report.statuses[0].symbol_present)

    def test_absent_symbol_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("not_there")], repo_root=self.root)
        self.assertFalse(report.statuses[0].symbol_present)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("not_there", joined)

    def test_all_three_checks_passing_yields_confidence_0_95(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("do_thing")], repo_root=self.root)
        s = report.statuses[0]
        self.assertTrue(s.path_exists)
        self.assertTrue(s.line_in_range)
        self.assertTrue(s.symbol_present)
        self.assertAlmostEqual(s.confidence, 0.95)
        self.assertEqual(s.notes, [])

    def test_missing_path_implies_symbol_not_present(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        report = validate_gaps(
            [
                Gap(
                    file_path="missing.py",
                    line=1,
                    symbol="x",
                    description="d",
                    severity="minor",
                )
            ],
            repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].symbol_present)

    def test_empty_symbol_string_is_rejected(self) -> None:
        # An empty string is trivially a substring of any text; reject
        # explicitly so the verifier cannot be silently bypassed.
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("")], repo_root=self.root)
        self.assertFalse(report.statuses[0].symbol_present)
