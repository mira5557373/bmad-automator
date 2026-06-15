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

from .common import ensure_dir
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
        line = event.to_json_line() + "\n"
        with self._thread_lock:
            with self._file_lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())


__all__ = ["TelemetryEmitter"]
