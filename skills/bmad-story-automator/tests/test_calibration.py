from __future__ import annotations

import contextlib
import tempfile
import unittest
from dataclasses import dataclass as _dc
from pathlib import Path

from story_automator.core import telemetry_events as _events_mod
from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import (
    BudgetAlert,
    CostCharged,
    StoryCompleted,
    StoryFailed,
    StoryStarted,
)


class ModuleSurfaceTests(unittest.TestCase):
    def test_all_symbols_exported(self) -> None:
        import story_automator.core.calibration as cal

        self.assertEqual(
            sorted(cal.__all__),
            sorted(
                [
                    "CalibrationEntry",
                    "CalibrationTable",
                    "build_calibration",
                    "lookup_success_rate",
                    "format_calibration_report",
                ]
            ),
        )

    def test_direct_imports_work(self) -> None:
        from story_automator.core.calibration import (
            CalibrationEntry,
            CalibrationTable,
            build_calibration,
            format_calibration_report,
            lookup_success_rate,
        )

        self.assertTrue(callable(build_calibration))
        self.assertTrue(callable(lookup_success_rate))
        self.assertTrue(callable(format_calibration_report))
        self.assertTrue(isinstance(CalibrationEntry, type))
        self.assertTrue(isinstance(CalibrationTable, type))


class CalibrationEntryShapeTests(unittest.TestCase):
    def test_construction_kw_only_and_frozen(self) -> None:
        from story_automator.core.calibration import CalibrationEntry

        entry = CalibrationEntry(
            model_id="claude-opus-4",
            task_kind="code",
            success_rate=0.8750,
            sample_count=8,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        self.assertEqual(entry.model_id, "claude-opus-4")
        self.assertEqual(entry.task_kind, "code")
        self.assertEqual(entry.success_rate, 0.8750)
        self.assertEqual(entry.sample_count, 8)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T12:00:00Z")

    def test_entry_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        from story_automator.core.calibration import CalibrationEntry

        entry = CalibrationEntry(
            model_id="m",
            task_kind="t",
            success_rate=0.5,
            sample_count=1,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        with self.assertRaises(FrozenInstanceError):
            entry.success_rate = 0.9  # type: ignore[misc]

    def test_entry_requires_kw_only(self) -> None:
        from story_automator.core.calibration import CalibrationEntry

        with self.assertRaises(TypeError):
            CalibrationEntry("m", "t", 0.5, 1, "2026-06-14T12:00:00Z")  # type: ignore[misc]


class CalibrationTableShapeTests(unittest.TestCase):
    def test_construction(self) -> None:
        from story_automator.core.calibration import CalibrationEntry, CalibrationTable

        entry = CalibrationEntry(
            model_id="m",
            task_kind="t",
            success_rate=0.5,
            sample_count=2,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        table = CalibrationTable(
            entries={("m", "t"): entry},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=2,
        )
        self.assertEqual(table.entries[("m", "t")], entry)
        self.assertEqual(table.generated_at, "2026-06-14T13:00:00Z")
        self.assertEqual(table.source_path, "/tmp/telemetry.jsonl")
        self.assertEqual(table.total_events_scanned, 2)

    def test_table_is_kw_only_mutable(self) -> None:
        from story_automator.core.calibration import CalibrationTable

        table = CalibrationTable(
            entries={},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/empty.jsonl",
            total_events_scanned=0,
        )
        table.total_events_scanned = 5
        self.assertEqual(table.total_events_scanned, 5)

        with self.assertRaises(TypeError):
            CalibrationTable({}, "x", "y", 0)  # type: ignore[misc]


@contextlib.contextmanager
def _fixture_dir():
    """REQ-14 compliant fixture directory.

    Creates the parent via `ensure_dir` before opening the
    `tempfile.TemporaryDirectory`. Yields a `pathlib.Path`.
    """
    parent = Path(tempfile.gettempdir()) / "m08_calibration_fixtures"
    ensure_dir(parent)
    with tempfile.TemporaryDirectory(dir=str(parent)) as tmpdir:
        yield Path(tmpdir)


class BuildCalibrationMissingPathTests(unittest.TestCase):
    def test_missing_path_returns_empty_table_without_raising(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            missing = tmpdir / "does-not-exist.jsonl"
            table = build_calibration(missing)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 0)
        self.assertEqual(table.source_path, str(missing))
        self.assertTrue(table.generated_at.endswith("Z"))


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class BuildCalibrationEmptyAndIgnoredTests(unittest.TestCase):
    def test_empty_file_returns_empty_table(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            ledger.write_text("", encoding="utf-8")
            table = build_calibration(ledger)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 0)
        self.assertEqual(table.source_path, str(ledger))

    def test_unrelated_event_types_are_counted_but_not_aggregated(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            started = StoryStarted(
                timestamp="2026-06-14T10:00:00Z",
                run_id="r1",
                epic="EP-1",
                story_key="S-1",
                agent="ag",
                model="claude-opus-4",
                complexity="M",
            )
            cost = CostCharged(
                timestamp="2026-06-14T10:01:00Z",
                run_id="r1",
                epic="EP-1",
                story_key="S-1",
                phase="impl",
                cost_usd=0.12,
                tokens_in=1000,
                tokens_out=200,
                model="claude-opus-4",
            )
            budget = BudgetAlert(
                timestamp="2026-06-14T10:02:00Z",
                run_id="r1",
                threshold_pct=50,
                total_cost_usd=5.0,
                max_budget_usd=10.0,
                epic="EP-1",
                story_key="S-1",
            )
            _write_jsonl(
                ledger,
                [compact_json(e.to_dict()) for e in (started, cost, budget)],
            )
            table = build_calibration(ledger)

        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 3)
        self.assertEqual(table.source_path, str(ledger))


def _completed_line(
    *,
    timestamp: str,
    run_id: str,
    epic: str,
    story_key: str,
    model_id: str,
    task_kind: str,
    duration_s: float = 100.0,
    cost_usd: float = 0.5,
    tokens_in: int = 1000,
    tokens_out: int = 200,
    attempts: int = 1,
) -> str:
    event = StoryCompleted(
        timestamp=timestamp,
        run_id=run_id,
        epic=epic,
        story_key=story_key,
        duration_s=duration_s,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        attempts=attempts,
    )
    payload = event.to_dict()
    payload["model_id"] = model_id
    payload["task_kind"] = task_kind
    return compact_json(payload)


def _failed_line(
    *,
    timestamp: str,
    run_id: str,
    epic: str,
    story_key: str,
    model_id: str,
    task_kind: str,
    error_class: str = "TimeoutError",
    reason: str = "exceeded",
    attempts: int = 5,
    final_session: str = "sess-1",
) -> str:
    event = StoryFailed(
        timestamp=timestamp,
        run_id=run_id,
        epic=epic,
        story_key=story_key,
        error_class=error_class,
        reason=reason,
        attempts=attempts,
        final_session=final_session,
    )
    payload = event.to_dict()
    payload["model_id"] = model_id
    payload["task_kind"] = task_kind
    return compact_json(payload)


class _ExtendedEventShim:
    """Per-test-class shim: temporarily widens StoryCompleted/StoryFailed
    so test fixtures can carry `model_id` and `task_kind` without
    requiring an M01 change. Restored in tearDownClass.

    This is strictly a TEST scaffold for M08. M01 is the right place to
    add `model_id` and `task_kind` to the event dataclasses; until then
    the production aggregator reads them defensively via getattr.
    """

    _saved: dict[str, type] = {}

    @classmethod
    def install(cls) -> None:
        cls._saved = {
            "StoryCompleted": _events_mod.StoryCompleted,
            "StoryFailed": _events_mod.StoryFailed,
        }
        _events_mod.Event._REGISTRY.pop("story_completed", None)
        _events_mod.Event._REGISTRY.pop("story_failed", None)
        new_completed = cls._widen(_events_mod.StoryCompleted, "story_completed")
        new_failed = cls._widen(_events_mod.StoryFailed, "story_failed")
        _events_mod.StoryCompleted = new_completed
        _events_mod.StoryFailed = new_failed
        import story_automator.core.calibration as cal_mod

        cal_mod.StoryCompleted = new_completed
        cal_mod.StoryFailed = new_failed

    @classmethod
    def uninstall(cls) -> None:
        _events_mod.Event._REGISTRY.pop("story_completed", None)
        _events_mod.Event._REGISTRY.pop("story_failed", None)
        _events_mod.StoryCompleted = cls._saved["StoryCompleted"]
        _events_mod.StoryFailed = cls._saved["StoryFailed"]
        _events_mod.Event._REGISTRY["story_completed"] = cls._saved["StoryCompleted"]
        _events_mod.Event._REGISTRY["story_failed"] = cls._saved["StoryFailed"]
        import story_automator.core.calibration as cal_mod

        cal_mod.StoryCompleted = cls._saved["StoryCompleted"]
        cal_mod.StoryFailed = cls._saved["StoryFailed"]

    @staticmethod
    def _widen(base: type, event_type: str) -> type:
        @_dc(kw_only=True)
        class _Widened(base):  # type: ignore[misc, valid-type]
            model_id: str = ""
            task_kind: str = ""

        _Widened.__name__ = base.__name__
        _Widened.__qualname__ = base.__qualname__
        _Widened.EVENT_TYPE = event_type
        _events_mod.Event._REGISTRY[event_type] = _Widened
        return _Widened


class BuildCalibrationAggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_single_completed_yields_success_rate_one(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            _write_jsonl(
                ledger,
                [
                    _completed_line(
                        timestamp="2026-06-14T10:00:00Z",
                        run_id="r1",
                        epic="EP-1",
                        story_key="S-1",
                        model_id="claude-opus-4",
                        task_kind="code",
                    )
                ],
            )
            table = build_calibration(ledger)

        self.assertEqual(table.total_events_scanned, 1)
        self.assertEqual(set(table.entries.keys()), {("claude-opus-4", "code")})
        entry = table.entries[("claude-opus-4", "code")]
        self.assertEqual(entry.success_rate, 1.0)
        self.assertEqual(entry.sample_count, 1)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T10:00:00Z")

    def test_single_failed_yields_success_rate_zero(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            _write_jsonl(
                ledger,
                [
                    _failed_line(
                        timestamp="2026-06-14T11:00:00Z",
                        run_id="r1",
                        epic="EP-1",
                        story_key="S-2",
                        model_id="claude-sonnet-4-5",
                        task_kind="review",
                    )
                ],
            )
            table = build_calibration(ledger)

        entry = table.entries[("claude-sonnet-4-5", "review")]
        self.assertEqual(entry.success_rate, 0.0)
        self.assertEqual(entry.sample_count, 1)
        self.assertEqual(entry.last_seen_iso, "2026-06-14T11:00:00Z")


if __name__ == "__main__":
    unittest.main()
