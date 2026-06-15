from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass as _dc
from pathlib import Path

from story_automator.core import telemetry_events as _events_mod
from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import StoryCompleted, StoryFailed


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
