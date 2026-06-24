"""SpecDriftWatcher (C1 MVP) — poll-based AC-coverage drift detector.

During a long agent session the model can drift from the spec it was
handed: implementing features the spec did not require, regressing on
requirements that were already satisfied at the start of the run, or
quietly dropping acceptance-criteria coverage as it refactors.

This watcher offers a cheap, poll-based way for an orchestrator (a
future milestone) to detect that drift. It captures an initial
``SpecDriftSnapshot`` (the baseline) and, on each ``poll()`` call,
re-scores the spec via ``core.spec_compliance.check_compliance`` and
classifies the regression by ``severity`` against the baseline.

This module is intentionally minimal:

* No background thread, no asyncio, no timers. The caller decides when
  to poll. Tests therefore drive ``poll()`` synchronously and never wait
  on wall-clock time.
* In-memory by default; optional disk persistence is opt-in via the
  ``persistence_key`` kwarg (see ``spec_drift_persistence``).
* No direct telemetry. ``poll()`` returns a ``SpecDriftEvent`` and the
  caller is expected to log / persist / emit it. We deliberately do
  NOT touch ``core/telemetry_events.py`` — that surface is frozen
  outside its owning milestone.
* No CLI surface. Drift history viewing is a follow-up milestone.

Severity classification uses a four-bucket model controlled by
``severity_thresholds``:

    delta < info_threshold                                 -> "OK"
    info_threshold    <= delta < warning_threshold         -> "INFO"
    warning_threshold <= delta < critical_threshold        -> "WARNING"
    critical_threshold <= delta                            -> "CRITICAL"

Negative deltas (coverage *improved*) always map to ``"OK"``. The
default thresholds are tuned for typical AC-coverage scores in
``[0.0, 1.0]``: 5% noise floor for ``INFO``, 15% for ``WARNING``, 30%
for ``CRITICAL``.

Stdlib only — honors the project's hard guardrail on dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from story_automator.core.spec_compliance import check_compliance

__all__ = [
    "SpecDriftError",
    "SpecDriftEvent",
    "SpecDriftSnapshot",
    "SpecDriftWatcher",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SpecDriftError(RuntimeError):
    """Raised on watcher misconfiguration or use-after-stop.

    The watcher is intentionally fail-loud so a misconfigured threshold
    or a stray ``poll()`` after ``stop()`` cannot silently produce an
    incorrect "OK" severity that masks real regression.
    """


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecDriftSnapshot:
    """One point-in-time read of AC coverage.

    Attributes:
        score: Fraction of requirements satisfied, in ``[0.0, 1.0]``.
            By convention an empty requirement list scores ``1.0``
            (vacuously satisfied) so the baseline does not accidentally
            classify a no-op spec as drift.
        requirements_total: Total number of ``ReqVerdict`` entries
            returned by ``check_compliance``.
        requirements_satisfied: Number of those verdicts whose
            ``status == "implemented"``. ``partial`` counts as
            unsatisfied so the score is conservative.
        timestamp_iso: ISO-8601 UTC timestamp with trailing ``Z`` for
            deterministic serialization.
    """

    score: float
    requirements_total: int
    requirements_satisfied: int
    timestamp_iso: str


@dataclass(frozen=True)
class SpecDriftEvent:
    """Result of one ``poll()`` call.

    Attributes:
        baseline_score: Score captured when the baseline was set.
        current_score: Score from the just-taken snapshot.
        delta: ``baseline_score - current_score``. Positive values mean
            the coverage *regressed*; negative values mean it improved.
        severity: One of ``"OK"``, ``"INFO"``, ``"WARNING"``,
            ``"CRITICAL"``.
        requirements_lost: Sorted tuple of REQ ids that were satisfied
            in the baseline but not in the current snapshot. Sorted for
            deterministic equality in tests + audit logs.
        timestamp_iso: ISO-8601 UTC timestamp of the current snapshot.
    """

    baseline_score: float
    current_score: float
    delta: float
    severity: str
    requirements_lost: tuple[str, ...]
    timestamp_iso: str


# ---------------------------------------------------------------------------
# Severity bucket constants
# ---------------------------------------------------------------------------


_SEVERITY_KEYS: frozenset[str] = frozenset({"info", "warning", "critical"})

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "info": 0.05,
    "warning": 0.15,
    "critical": 0.30,
}

_VALID_SEVERITIES: frozenset[str] = frozenset({"OK", "INFO", "WARNING", "CRITICAL"})


def _validate_thresholds(thresholds: dict[str, float]) -> dict[str, float]:
    """Reject malformed override dicts loudly.

    Three failure modes covered:

    1. Unknown keys (typos like ``"warming"`` would silently make the
       intended bucket use the default, masking severity changes).
    2. Out-of-range values — thresholds must lie in ``[0.0, 1.0]``
       because the underlying score does.
    3. Non-monotonic ordering — ``info < warning < critical`` must hold,
       otherwise the bucket math becomes ambiguous and a moderate drift
       could classify as ``CRITICAL`` while a worse drift classifies as
       ``WARNING``.
    """
    extra = set(thresholds) - _SEVERITY_KEYS
    if extra:
        raise SpecDriftError(
            f"unknown severity_thresholds keys: {sorted(extra)!r}; "
            f"allowed keys are {sorted(_SEVERITY_KEYS)!r}"
        )
    merged: dict[str, float] = {**_DEFAULT_THRESHOLDS, **thresholds}
    for key, value in merged.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SpecDriftError(
                f"severity_thresholds[{key!r}] must be a number, got "
                f"{type(value).__name__}"
            )
        f = float(value)
        if not 0.0 <= f <= 1.0:
            raise SpecDriftError(
                f"severity_thresholds[{key!r}] must lie in [0.0, 1.0], got {f}"
            )
        merged[key] = f
    if not (merged["info"] < merged["warning"] < merged["critical"]):
        raise SpecDriftError(
            "severity_thresholds must satisfy info < warning < critical; got "
            f"info={merged['info']}, warning={merged['warning']}, "
            f"critical={merged['critical']}"
        )
    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 with trailing ``Z``.

    Centralized so a future milestone can monkey-patch a clock source
    without rewriting every caller.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _satisfied_ids(verdicts: Iterable[object]) -> set[str]:
    """Return the set of REQ ids whose status is ``"implemented"``.

    ``partial`` is NOT counted as satisfied — we want the drift score
    to err on the conservative side, so a partial regression still
    surfaces. Any non-``ReqVerdict``-shaped entry is skipped defensively
    rather than crashing the watcher.
    """
    out: set[str] = set()
    for v in verdicts:
        status = getattr(v, "status", None)
        req_id = getattr(v, "req_id", None)
        if status == "implemented" and isinstance(req_id, str) and req_id:
            out.add(req_id)
    return out


def _score(satisfied: int, total: int) -> float:
    """Coverage fraction with vacuous-1.0 for empty specs.

    An empty spec (no requirements at all) returns ``1.0`` so the
    baseline does not look like a regression on the first poll. This
    matches the convention used elsewhere in the gate stack.
    """
    if total == 0:
        return 1.0
    return satisfied / total


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


class SpecDriftWatcher:
    """Poll-based AC-coverage drift detector.

    The watcher is constructed cheaply; no I/O happens until the first
    ``snapshot()`` or ``poll()`` call. Lifecycle:

    1. ``__init__`` — optionally accept a pre-computed baseline.
    2. ``snapshot()`` — one read, no comparison.
    3. ``set_baseline()`` — capture the baseline (or accept one).
    4. ``poll()`` — snapshot + compare; auto-initializes the baseline
       on the first call if one was never set.
    5. ``stop()`` — idempotent close; subsequent ``poll()`` raises so
       downstream telemetry can detect a programming error.

    The watcher holds no on-disk state. Persisting the baseline across
    sessions is a follow-up milestone.
    """

    def __init__(
        self,
        project_root: Path | str,
        spec_path: Path | str,
        *,
        baseline_snapshot: SpecDriftSnapshot | None = None,
        severity_thresholds: dict[str, float] | None = None,
        persistence_key: str | None = None,
    ) -> None:
        """Construct a watcher; no I/O unless ``persistence_key`` is set.

        Args:
            project_root: Directory used as ``cwd`` for the underlying
                ``check_compliance`` subprocess. Stored as a ``Path`` so
                callers can pass either form.
            spec_path: Path to the spec markdown file ``check_compliance``
                should read.
            baseline_snapshot: Optional pre-computed baseline. When
                ``None``, ``poll()`` will auto-initialize on the first
                call.
            severity_thresholds: Optional override for the default
                bucket thresholds. Keys must be a subset of
                ``{"info", "warning", "critical"}``; unknown keys raise
                ``SpecDriftError`` so typos do not silently degrade
                detection.
            persistence_key: Optional slug used as the directory name
                under ``<project_root>/_bmad/drift/``. When provided,
                the watcher loads any persisted baseline at init,
                persists ``set_baseline`` to ``baseline.json``, and
                appends each ``poll()`` event to ``events.jsonl``.
                ``None`` (default) keeps the watcher purely in-memory,
                byte-identical to the MVP. Slug is restricted to
                ``[A-Za-z0-9][A-Za-z0-9_-]*`` to block path traversal.
        """
        self._project_root: Path = Path(project_root)
        self._spec_path: Path = Path(spec_path)
        self._baseline: SpecDriftSnapshot | None = baseline_snapshot
        self._baseline_ids: set[str] = set()
        self._thresholds: dict[str, float] = (
            _validate_thresholds(severity_thresholds)
            if severity_thresholds is not None
            else dict(_DEFAULT_THRESHOLDS)
        )
        self._stopped: bool = False
        self._persistence_key: str | None = persistence_key
        if persistence_key is not None:
            # Validate eagerly so a typo raises at construction time
            # rather than on the first poll(). Local import avoids a
            # circular at module-load. ``_baseline_ids`` is already
            # ``set()`` so a loaded on-disk baseline behaves like a
            # caller-supplied one — id-set is rebuilt on next
            # ``set_baseline``.
            from story_automator.core.innovation.spec_drift_persistence import (
                load_baseline,
                persist_baseline,
                validate_persistence_key,
            )
            validate_persistence_key(persistence_key)
            if self._baseline is None:
                self._baseline = load_baseline(self._project_root, persistence_key)
            else:
                # Caller supplied ``baseline_snapshot`` AND opted into
                # disk persistence. Without this write the in-memory
                # snapshot would silently vanish on the next process
                # restart, contradicting the persistence_key contract.
                # We only persist when no on-disk baseline already
                # exists, so a previously-persisted baseline is never
                # clobbered by a stale caller-supplied snapshot.
                from story_automator.core.innovation.spec_drift_persistence import (
                    baseline_path,
                )
                if not baseline_path(self._project_root, persistence_key).exists():
                    persist_baseline(
                        self._project_root, persistence_key, self._baseline,
                    )

    # ------------------------------------------------------------------
    # Snapshot / baseline management
    # ------------------------------------------------------------------

    def snapshot(self) -> SpecDriftSnapshot:
        """Take one AC-coverage reading without touching the baseline.

        Delegates to ``core.spec_compliance.check_compliance`` so the
        scoring policy stays centralized. The diff is intentionally
        empty for the MVP — the watcher scores the spec as-of-now
        rather than against a candidate diff, because mid-session drift
        is about the running agent's working tree, not a finished diff.
        """
        if self._stopped:
            raise SpecDriftError("watcher has been stopped; cannot take snapshot")
        snap, _ids = self._take_snapshot_with_ids()
        return snap

    def _take_snapshot_with_ids(self) -> tuple[SpecDriftSnapshot, set[str]]:
        """Atomic single-call snapshot + satisfied-id set.

        Both ``snapshot()`` and ``set_baseline()`` use this to guarantee
        that the dataclass score and the id set come from the same
        ``check_compliance`` invocation. Splitting them across two calls
        would let the spec / working tree / LLM output shift between
        reads, leaving the baseline shards inconsistent (e.g.
        ``requirements_satisfied=5`` while ``len(_baseline_ids)=7``) and
        producing incoherent ``poll()`` events later. Also halves the
        subprocess cost of ``set_baseline()``.
        """
        report = check_compliance(
            spec_path=self._spec_path,
            diff_text="",
            cwd=self._project_root,
        )
        verdicts = list(report.verdicts)
        satisfied_ids = _satisfied_ids(verdicts)
        total = len(verdicts)
        snap = SpecDriftSnapshot(
            score=_score(len(satisfied_ids), total),
            requirements_total=total,
            requirements_satisfied=len(satisfied_ids),
            timestamp_iso=_now_iso(),
        )
        return snap, satisfied_ids

    def is_baseline_set(self) -> bool:
        """Return ``True`` iff a baseline snapshot has been recorded."""
        return self._baseline is not None

    def set_baseline(self, snapshot: SpecDriftSnapshot | None = None) -> None:
        """Record (or refresh) the baseline.

        When ``snapshot`` is ``None`` the watcher takes a fresh
        snapshot itself. Either way the satisfied-id set is rebuilt so
        ``requirements_lost`` can be computed on later polls.
        """
        if self._stopped:
            raise SpecDriftError("watcher has been stopped; cannot set baseline")
        if snapshot is None:
            # Single ``check_compliance`` read — the dataclass and the
            # id set are derived from the SAME verdicts list so a later
            # ``poll()`` can never observe two disagreeing shards.
            snapshot, self._baseline_ids = self._take_snapshot_with_ids()
        else:
            # Baseline supplied by caller — we don't know the id set,
            # so a follow-up poll() will discover it on demand.
            self._baseline_ids = set()
        self._baseline = snapshot
        if self._persistence_key is not None:
            from story_automator.core.innovation.spec_drift_persistence import (
                persist_baseline,
            )
            persist_baseline(self._project_root, self._persistence_key, snapshot)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> SpecDriftEvent:
        """Take a snapshot and compare it against the baseline.

        If no baseline is set, the first ``poll()`` auto-initializes it
        from the just-taken snapshot. In that case the event has
        ``delta = 0.0`` and ``severity = "OK"`` — the watcher has not
        observed any drift yet because there was nothing to compare
        against.
        """
        if self._stopped:
            raise SpecDriftError("watcher has been stopped; cannot poll")
        # Take the current reading and re-fetch the id set so we can
        # diff the "lost" REQs deterministically.
        report = check_compliance(
            spec_path=self._spec_path,
            diff_text="",
            cwd=self._project_root,
        )
        verdicts = list(report.verdicts)
        current_ids = _satisfied_ids(verdicts)
        total = len(verdicts)
        satisfied = len(current_ids)
        current_snapshot = SpecDriftSnapshot(
            score=_score(satisfied, total),
            requirements_total=total,
            requirements_satisfied=satisfied,
            timestamp_iso=_now_iso(),
        )

        if self._baseline is None:
            # Auto-initialize: this poll establishes the baseline and
            # emits a no-drift event so the caller has a consistent
            # event stream from t=0.
            self._baseline = current_snapshot
            self._baseline_ids = current_ids
            if self._persistence_key is not None:
                from story_automator.core.innovation.spec_drift_persistence import (
                    persist_baseline,
                )
                persist_baseline(
                    self._project_root,
                    self._persistence_key,
                    current_snapshot,
                )
            event = SpecDriftEvent(
                baseline_score=current_snapshot.score,
                current_score=current_snapshot.score,
                delta=0.0,
                severity="OK",
                requirements_lost=(),
                timestamp_iso=current_snapshot.timestamp_iso,
            )
        else:
            baseline = self._baseline
            # If the baseline was caller-supplied we never captured an
            # id set for it. In that case we conservatively treat the
            # baseline id set as empty so ``requirements_lost`` is
            # empty too — the score-based severity is still meaningful,
            # and the caller can take a fresh baseline later if they
            # want id-level drift.
            baseline_ids = self._baseline_ids
            lost = sorted(baseline_ids - current_ids)
            delta = baseline.score - current_snapshot.score
            severity = self._classify_severity(delta)
            event = SpecDriftEvent(
                baseline_score=baseline.score,
                current_score=current_snapshot.score,
                delta=delta,
                severity=severity,
                requirements_lost=tuple(lost),
                timestamp_iso=current_snapshot.timestamp_iso,
            )

        if self._persistence_key is not None:
            from story_automator.core.innovation.spec_drift_persistence import (
                append_drift_event,
            )
            append_drift_event(self._project_root, self._persistence_key, event)
        return event

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Mark the watcher closed. Idempotent.

        After ``stop()``, ``poll()`` / ``snapshot()`` / ``set_baseline()``
        all raise ``SpecDriftError`` so a programming error (e.g. a
        stale callback firing post-teardown) is loud rather than silent.
        """
        self._stopped = True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify_severity(self, delta: float) -> str:
        """Bucket a delta value into one of the four severity strings.

        Negative deltas (improved coverage) always classify as
        ``"OK"`` — improvement is never drift.
        """
        if delta < self._thresholds["info"]:
            return "OK"
        if delta < self._thresholds["warning"]:
            return "INFO"
        if delta < self._thresholds["critical"]:
            return "WARNING"
        return "CRITICAL"
