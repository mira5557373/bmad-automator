from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

import story_automator.core.drift_detector as drift_module
from story_automator.core.calibration import CalibrationEntry, CalibrationTable
from story_automator.core.drift_detector import (
    MAJOR_MAX,
    MINOR_MAX,
    STABLE_MAX,
    DriftClassification,
    DriftEntry,
    DriftReport,
    _classify,
    compute_drift,
    format_drift_report,
)


class DriftClassificationTests(unittest.TestCase):
    def test_members_and_order(self) -> None:
        self.assertEqual(
            [m.name for m in DriftClassification],
            ["STABLE", "MINOR_DRIFT", "MAJOR_DRIFT", "SEVERE_DRIFT"],
        )

    def test_values_equal_lowercase_names(self) -> None:
        for member in DriftClassification:
            self.assertEqual(member.value, member.name.lower())


class DriftEntryTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        entry = DriftEntry(
            model_id="gpt-4o-mini",
            task_kind="story",
            baseline_success_rate=0.80,
            current_success_rate=0.75,
            delta=round(0.75 - 0.80, 4),
            classification=DriftClassification.STABLE,
        )
        self.assertEqual(entry.model_id, "gpt-4o-mini")
        self.assertEqual(entry.task_kind, "story")
        self.assertEqual(entry.baseline_success_rate, 0.80)
        self.assertEqual(entry.current_success_rate, 0.75)
        self.assertEqual(entry.delta, -0.05)
        self.assertIs(entry.classification, DriftClassification.STABLE)

    def test_is_frozen(self) -> None:
        import dataclasses

        entry = DriftEntry(
            model_id="m",
            task_kind="t",
            baseline_success_rate=0.0,
            current_success_rate=0.0,
            delta=0.0,
            classification=DriftClassification.STABLE,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.model_id = "other"  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DriftEntry(  # type: ignore[call-arg]
                "m",
                "t",
                0.0,
                0.0,
                0.0,
                DriftClassification.STABLE,
            )


class DriftReportTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="/tmp/base.jsonl",
            current_source="/tmp/now.jsonl",
        )
        self.assertEqual(report.entries, [])
        self.assertEqual(report.generated_at, "2026-06-15T00:00:00Z")
        self.assertEqual(report.baseline_source, "/tmp/base.jsonl")
        self.assertEqual(report.current_source, "/tmp/now.jsonl")

    def test_entries_is_mutable_list(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="b",
            current_source="c",
        )
        report.entries.append(
            DriftEntry(
                model_id="m",
                task_kind="t",
                baseline_success_rate=0.0,
                current_success_rate=0.0,
                delta=0.0,
                classification=DriftClassification.STABLE,
            )
        )
        self.assertEqual(len(report.entries), 1)


class ClassifyHelperTests(unittest.TestCase):
    def test_zero_is_stable(self) -> None:
        self.assertIs(_classify(0.0), DriftClassification.STABLE)

    def test_just_below_stable_max_is_stable(self) -> None:
        self.assertIs(_classify(0.0499), DriftClassification.STABLE)
        self.assertIs(_classify(-0.0499), DriftClassification.STABLE)

    def test_stable_max_is_minor(self) -> None:
        self.assertIs(_classify(STABLE_MAX), DriftClassification.MINOR_DRIFT)
        self.assertIs(_classify(-STABLE_MAX), DriftClassification.MINOR_DRIFT)

    def test_just_below_minor_max_is_minor(self) -> None:
        self.assertIs(_classify(0.0999), DriftClassification.MINOR_DRIFT)

    def test_minor_max_is_major(self) -> None:
        self.assertIs(_classify(MINOR_MAX), DriftClassification.MAJOR_DRIFT)
        self.assertIs(_classify(-MINOR_MAX), DriftClassification.MAJOR_DRIFT)

    def test_just_below_major_max_is_major(self) -> None:
        self.assertIs(_classify(0.1999), DriftClassification.MAJOR_DRIFT)

    def test_major_max_is_severe(self) -> None:
        self.assertIs(_classify(MAJOR_MAX), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-MAJOR_MAX), DriftClassification.SEVERE_DRIFT)

    def test_large_magnitude_is_severe(self) -> None:
        self.assertIs(_classify(0.95), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-0.95), DriftClassification.SEVERE_DRIFT)

    def test_boundary_constants_match_spec(self) -> None:
        self.assertEqual(STABLE_MAX, 0.05)
        self.assertEqual(MINOR_MAX, 0.10)
        self.assertEqual(MAJOR_MAX, 0.20)


def _entry(model_id: str, task_kind: str, success_rate: float) -> CalibrationEntry:
    return CalibrationEntry(
        model_id=model_id,
        task_kind=task_kind,
        success_rate=round(success_rate, 4),
        sample_count=10,
        last_seen_iso="2026-06-15T00:00:00Z",
    )


def _table(
    *entries: CalibrationEntry,
    source_path: str = "/fixtures/table.jsonl",
) -> CalibrationTable:
    return CalibrationTable(
        entries={(e.model_id, e.task_kind): e for e in entries},
        generated_at="2026-06-15T00:00:00Z",
        source_path=source_path,
        total_events_scanned=sum(e.sample_count for e in entries),
    )


class ComputeDriftBaselineTests(unittest.TestCase):
    def test_identical_tables_produce_all_stable(self) -> None:
        baseline = _table(
            _entry("gpt-4o-mini", "story", 0.80),
            _entry("opus-4-1", "review", 0.92),
            source_path="/fixtures/base.jsonl",
        )
        current = _table(
            _entry("gpt-4o-mini", "story", 0.80),
            _entry("opus-4-1", "review", 0.92),
            source_path="/fixtures/now.jsonl",
        )
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(report.baseline_source, "/fixtures/base.jsonl")
        self.assertEqual(report.current_source, "/fixtures/now.jsonl")
        self.assertEqual(len(report.entries), 2)
        for entry in report.entries:
            self.assertEqual(entry.delta, 0.0)
            self.assertIs(entry.classification, DriftClassification.STABLE)
        self.assertRegex(report.generated_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_inputs_not_mutated(self) -> None:
        baseline = _table(_entry("m", "t", 0.5))
        current = _table(_entry("m", "t", 0.6))
        baseline_snapshot = dict(baseline.entries)
        current_snapshot = dict(current.entries)
        compute_drift(baseline=baseline, current=current)
        self.assertEqual(baseline.entries, baseline_snapshot)
        self.assertEqual(current.entries, current_snapshot)


class ComputeDriftBoundaryTests(unittest.TestCase):
    def _drift_entry(self, baseline_rate: float, current_rate: float) -> DriftEntry:
        baseline = _table(_entry("m", "t", baseline_rate))
        current = _table(_entry("m", "t", current_rate))
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        return report.entries[0]

    def test_stable_below_then_minor_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.8499)
        at = self._drift_entry(0.80, 0.85)
        self.assertIs(below.classification, DriftClassification.STABLE)
        self.assertIs(at.classification, DriftClassification.MINOR_DRIFT)

    def test_minor_below_then_major_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.8999)
        at = self._drift_entry(0.80, 0.90)
        self.assertIs(below.classification, DriftClassification.MINOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.MAJOR_DRIFT)

    def test_major_below_then_severe_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.9999)
        at = self._drift_entry(0.60, 0.80)
        self.assertIs(below.classification, DriftClassification.MAJOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.SEVERE_DRIFT)

    def test_negative_deltas_classify_symmetrically_stable_minor(self) -> None:
        below = self._drift_entry(0.80, 0.7501)
        at = self._drift_entry(0.85, 0.80)
        self.assertIs(below.classification, DriftClassification.STABLE)
        self.assertIs(at.classification, DriftClassification.MINOR_DRIFT)

    def test_negative_deltas_classify_symmetrically_minor_major(self) -> None:
        below = self._drift_entry(0.80, 0.7001)
        at = self._drift_entry(0.90, 0.80)
        self.assertIs(below.classification, DriftClassification.MINOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.MAJOR_DRIFT)

    def test_negative_deltas_classify_symmetrically_major_severe(self) -> None:
        below = self._drift_entry(0.80, 0.6001)
        at = self._drift_entry(0.80, 0.60)
        self.assertIs(below.classification, DriftClassification.MAJOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.SEVERE_DRIFT)


class ComputeDriftMissingKeyTests(unittest.TestCase):
    def test_key_only_in_baseline_gets_current_default(self) -> None:
        baseline = _table(_entry("gpt-4o-mini", "story", 0.95))
        current = _table()
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        entry = report.entries[0]
        self.assertEqual(entry.model_id, "gpt-4o-mini")
        self.assertEqual(entry.task_kind, "story")
        self.assertEqual(entry.baseline_success_rate, 0.95)
        self.assertEqual(entry.current_success_rate, 0.5)
        self.assertEqual(entry.delta, round(0.5 - 0.95, 4))
        self.assertIs(entry.classification, DriftClassification.SEVERE_DRIFT)

    def test_key_only_in_current_gets_baseline_default(self) -> None:
        baseline = _table()
        current = _table(_entry("opus-4-1", "review", 0.30))
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        entry = report.entries[0]
        self.assertEqual(entry.model_id, "opus-4-1")
        self.assertEqual(entry.task_kind, "review")
        self.assertEqual(entry.baseline_success_rate, 0.5)
        self.assertEqual(entry.current_success_rate, 0.30)
        self.assertEqual(entry.delta, round(0.30 - 0.5, 4))
        self.assertIs(entry.classification, DriftClassification.SEVERE_DRIFT)

    def test_empty_inputs_produce_empty_entries(self) -> None:
        report = compute_drift(baseline=_table(), current=_table())
        self.assertEqual(report.entries, [])


class ComputeDriftSortOrderTests(unittest.TestCase):
    def test_entries_sorted_by_abs_delta_then_model_then_task(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.50),  # delta = +0.30 -> severe
            _entry("beta", "story", 0.50),  # delta = +0.05 -> minor
            _entry("gamma", "review", 0.50),  # delta = -0.15 -> major
            _entry(
                "alpha", "review", 0.50
            ),  # delta = +0.30 -> severe (ties on |delta|)
            _entry("beta", "review", 0.50),  # delta = 0.00 -> stable
        )
        current = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "story", 0.55),
            _entry("gamma", "review", 0.35),
            _entry("alpha", "review", 0.80),
            _entry("beta", "review", 0.50),
        )
        report = compute_drift(baseline=baseline, current=current)
        observed = [(e.model_id, e.task_kind, e.delta) for e in report.entries]
        self.assertEqual(
            observed,
            [
                ("alpha", "review", 0.30),
                ("alpha", "story", 0.30),
                ("gamma", "review", -0.15),
                ("beta", "story", 0.05),
                ("beta", "review", 0.0),
            ],
        )

    def test_repeated_calls_return_identical_entries_modulo_generated_at(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.60),
            _entry("beta", "review", 0.40),
        )
        current = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "review", 0.10),
        )
        first = compute_drift(baseline=baseline, current=current)
        second = compute_drift(baseline=baseline, current=current)
        self.assertEqual(first.entries, second.entries)
        self.assertEqual(first.baseline_source, second.baseline_source)
        self.assertEqual(first.current_source, second.current_source)


class FormatDriftReportTests(unittest.TestCase):
    def test_snapshot_for_known_fixture(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "review", 0.90),
            source_path="/fixtures/base.jsonl",
        )
        current = _table(
            _entry("alpha", "story", 0.60),  # delta = -0.20 -> severe
            _entry("beta", "review", 0.93),  # delta = +0.03 -> stable
            source_path="/fixtures/now.jsonl",
        )
        report = compute_drift(baseline=baseline, current=current)
        rendered = format_drift_report(report)
        expected = (
            "baseline: /fixtures/base.jsonl\tcurrent: /fixtures/now.jsonl\n"
            "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification\n"
            "alpha\tstory\t0.8000\t0.6000\t-0.2000\tsevere_drift\n"
            "beta\treview\t0.9000\t0.9300\t+0.0300\tstable\n"
        )
        self.assertEqual(rendered, expected)

    def test_ends_with_single_trailing_newline(self) -> None:
        rendered = format_drift_report(
            compute_drift(baseline=_table(), current=_table())
        )
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_empty_report_still_has_header(self) -> None:
        rendered = format_drift_report(
            DriftReport(
                entries=[],
                generated_at="2026-06-15T00:00:00Z",
                baseline_source="b",
                current_source="c",
            )
        )
        expected = (
            "baseline: b\tcurrent: c\n"
            "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification\n"
        )
        self.assertEqual(rendered, expected)

    def test_signed_delta_formatting(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.60))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        self.assertIn("\t+0.1000\t", rendered)

    def test_is_ascii_only(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.55))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        rendered.encode("ascii")  # raises if non-ASCII slipped in


_FORBIDDEN_TOKENS = (
    "requests",
    "httpx",
    "aiohttp",
    "subprocess",
    "os.system",
    "psutil",
    "filelock",
)
_FORBIDDEN_WRITE_PATTERNS = (
    "open(",
    "write_text",
    "read_text",
    "Path.mkdir",
    "write_atomic",
)


def _module_source() -> str:
    path = Path(drift_module.__file__)
    return path.read_text(encoding="utf-8")


class ModuleSurfaceTests(unittest.TestCase):
    def test_all_lists_exact_symbols(self) -> None:
        self.assertEqual(
            set(drift_module.__all__),
            {
                "DriftClassification",
                "DriftEntry",
                "DriftReport",
                "compute_drift",
                "format_drift_report",
            },
        )

    def test_starts_with_future_annotations(self) -> None:
        source = _module_source()
        tree = ast.parse(source)
        body = tree.body
        self.assertTrue(body, "module body is empty")
        first = body[0]
        is_docstring = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        if is_docstring:
            self.assertGreaterEqual(
                len(body), 2, "docstring present but no __future__ import follows"
            )
            future_node = body[1]
        else:
            future_node = first
        self.assertIsInstance(future_node, ast.ImportFrom)
        self.assertEqual(future_node.module, "__future__")
        self.assertEqual([alias.name for alias in future_node.names], ["annotations"])

    def test_import_allowlist(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_TOKENS:
            self.assertNotIn(token, source, f"forbidden import token: {token}")

    def test_no_filesystem_mutators(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_WRITE_PATTERNS:
            self.assertNotIn(token, source, f"forbidden write pattern: {token}")

    def test_no_unresolved_four_letter_placeholder(self) -> None:
        source = _module_source()
        tokens = (
            "TO" + "DO",
            "FI" + "XME",
            "XX" + "XX",
            "TB" + "DX",
        )
        for token in tokens:
            self.assertNotIn(token, source, f"placeholder token leaked: {token}")

    def test_module_under_300_lines(self) -> None:
        line_count = len(_module_source().splitlines())
        self.assertLessEqual(line_count, 300, f"module is {line_count} lines (>300)")


class GeneratedAtSourcingTests(unittest.TestCase):
    def test_compute_drift_calls_iso_now(self) -> None:
        baseline = _table(_entry("m", "t", 0.5))
        current = _table(_entry("m", "t", 0.5))
        with mock.patch(
            "story_automator.core.drift_detector.iso_now",
            return_value="2099-01-01T00:00:00Z",
        ) as patched:
            report = compute_drift(baseline=baseline, current=current)
        patched.assert_called_once()
        self.assertEqual(report.generated_at, "2099-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
