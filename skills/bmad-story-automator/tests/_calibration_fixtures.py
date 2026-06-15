from __future__ import annotations

import contextlib
import tempfile
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
from story_automator.core.calibration import CalibrationEntry, CalibrationTable


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


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _completed_line(
    timestamp: str,
    run_id: str,
    story_key: str,
    model_id: str,
    task_kind: str,
    *,
    epic: str = "EP-1",
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
    timestamp: str,
    run_id: str,
    story_key: str,
    model_id: str,
    task_kind: str,
    *,
    epic: str = "EP-1",
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


def _unrelated_event_lines() -> list[str]:
    """Return JSONL lines for three non-story events (Started, Cost, Budget).

    Used to assert that unrelated event types are counted in
    `total_events_scanned` but never aggregated into `entries`.
    """

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
    return [compact_json(e.to_dict()) for e in (started, cost, budget)]


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


def _make_entry(
    *,
    model_id: str = "claude-opus-4",
    task_kind: str = "code",
    success_rate: float = 0.8750,
    sample_count: int = 8,
    last_seen_iso: str = "2026-06-14T12:00:00Z",
) -> CalibrationEntry:
    """Build a CalibrationEntry for tests. Defaults are the canonical
    opus/code/0.875/8 fixture used by lookup and report tests.
    """

    return CalibrationEntry(
        model_id=model_id,
        task_kind=task_kind,
        success_rate=success_rate,
        sample_count=sample_count,
        last_seen_iso=last_seen_iso,
    )


def _make_table(
    entries=None,
    *,
    generated_at: str = "2026-06-14T13:00:00Z",
    source_path: str = "/tmp/t.jsonl",
    total_events_scanned: int | None = None,
) -> CalibrationTable:
    """Build a CalibrationTable for tests.

    `entries` may be an iterable of CalibrationEntry (keyed by
    (model_id, task_kind)) or a pre-built dict. `total_events_scanned`
    defaults to `sum(e.sample_count for e in entries)` when omitted.
    """

    if entries is None:
        entries_dict: dict[tuple[str, str], CalibrationEntry] = {}
    elif isinstance(entries, dict):
        entries_dict = entries
    else:
        entries_dict = {(e.model_id, e.task_kind): e for e in entries}
    scanned: int = (
        total_events_scanned
        if total_events_scanned is not None
        else sum(e.sample_count for e in entries_dict.values())
    )
    return CalibrationTable(
        entries=entries_dict,
        generated_at=generated_at,
        source_path=source_path,
        total_events_scanned=scanned,
    )
