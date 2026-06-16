"""Cross-process safe append-only JSONL emitter for M01 typed events.

REQ-01..REQ-05 + REQ-14/15. Uses ``filelock.FileLock`` on ``<path>.lock``
plus an instance-level ``threading.Lock`` to serialize concurrent emits.
``os.fsync`` runs before either lock is released so a crash between
emits cannot leave a partial line. Parent dir is lazily created on
first emit via ``ensure_dir`` from ``story_automator.core.common``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from filelock import FileLock

from .common import compact_json, ensure_dir
from .telemetry_events import Event


class TelemetryEmitter:
    def __init__(self, path: str | Path, run_id: str | None = None) -> None:
        self._path: Path = Path(path)
        self._lock_path: Path = self._path.with_name(self._path.name + ".lock")
        self._run_id: str | None = run_id
        self._thread_lock: threading.Lock = threading.Lock()
        self._file_lock: FileLock = FileLock(str(self._lock_path))

    def emit(self, event: Event) -> None:
        ensure_dir(self._path.parent)
        line = self._serialize(event) + "\n"
        with self._thread_lock:
            with self._file_lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())

    def _serialize(self, event: Event) -> str:
        # REQ-05: caller's non-empty run_id always wins; only stamp the
        # ctor-provided run_id into events whose run_id is empty. Mutate
        # the dict, not the dataclass — the caller keeps their object.
        if self._run_id is None or event.run_id:
            return event.to_json_line()
        data = event.to_dict()
        data["run_id"] = self._run_id
        return compact_json(data)


_PROJECT_EMITTERS: dict[Path, TelemetryEmitter] = {}


def emitter_for_project_root(project_root: str | Path) -> TelemetryEmitter:
    # Shared cache keyed by the resolved telemetry file path so every wiring
    # call site in the same process serializes through the same threading.Lock.
    path = (Path(project_root) / "telemetry" / "events.jsonl").resolve()
    cached = _PROJECT_EMITTERS.get(path)
    if cached is not None:
        return cached
    emitter = TelemetryEmitter(path)
    _PROJECT_EMITTERS[path] = emitter
    return emitter


__all__ = ["TelemetryEmitter", "emitter_for_project_root"]
