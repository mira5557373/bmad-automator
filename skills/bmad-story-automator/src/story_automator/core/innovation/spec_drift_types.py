"""Pure-data types + helpers for :class:`SpecDriftWatcher` (sibling split).

Houses the watcher's pure dataclasses (:class:`SpecDriftSnapshot`,
:class:`SpecDriftEvent`), its bespoke exception class
(:class:`SpecDriftError`), the severity-bucket constants
(:data:`_SEVERITY_KEYS`, :data:`_DEFAULT_THRESHOLDS`,
:data:`_VALID_SEVERITIES`), and the four standalone helpers
:func:`_validate_thresholds`, :func:`_now_iso`, :func:`_satisfied_ids`,
:func:`_score`.

Splitting these out of ``spec_drift_watcher.py`` (which sat at 528 LOC
after the C1 follow-ups landed) keeps the canonical module comfortably
under the CLAUDE.md 500-LOC soft limit without changing any observable
behavior — every public symbol is re-exported from ``spec_drift_watcher``
so existing call sites and tests see no surface change.

The split mirrors the sibling pattern already used for
``threshold_proposer`` / ``threshold_proposer_helpers`` and
``spec_drift_watcher`` / ``spec_drift_persistence``.

Stdlib only — honors the project's hard guardrail on dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

__all__ = [
    "SpecDriftError",
    "SpecDriftEvent",
    "SpecDriftSnapshot",
    "_DEFAULT_THRESHOLDS",
    "_SEVERITY_KEYS",
    "_VALID_SEVERITIES",
    "_now_iso",
    "_satisfied_ids",
    "_score",
    "_validate_thresholds",
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
