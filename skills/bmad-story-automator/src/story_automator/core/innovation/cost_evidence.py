"""Per-collector cost evidence — disk emission + load surface for C3.

The full cost-attribution wiring milestone (C3) splits a session's
:class:`UsageMetrics` across the collectors that actually ran, then
persists the result as JSON under
``_bmad/gate/cost/<gate_id>/`` so downstream tooling can answer "which
collector burned which fraction of this gate's LLM bill". The N7
substrate (``core/innovation/cost_attribution.py``) ships the
distribution helpers; this module ties them to the orchestrator.

Disk layout (sibling-of-evidence, NOT a child of ``_bmad/gate/evidence/``
so listing the evidence tree for Merkle reverification is unaffected):

.. code-block:: text

    _bmad/gate/cost/<gate_id>/summary.json
    _bmad/gate/cost/<gate_id>/<collector_id>.json

* ``summary.json`` is the :class:`GateCostReport` serialization
  (gate id, session usage, attribution mode, total cost, collector
  count, timestamp).
* Each ``<collector_id>.json`` is the matching
  :class:`CollectorCostShare` dataclass — one file per collector for
  cheap per-collector lookups without re-parsing the summary.

The module is **fail-soft for the gate path**: orchestrator wiring
wraps :func:`emit_gate_cost_report` in ``try/except Exception`` so a
disk-emission failure can never abort an in-flight gate. Cost
evidence is observability, not gating.

Attribution selection:

* Default ``attribution_mode="duration"`` — collectors already record
  ``duration_ms`` in their evidence dict, so weighted attribution is
  always possible without additional plumbing.
* When every collector reports zero duration we silently fall back to
  ``"uniform"`` (the :func:`attribute_cost_by_duration` helper already
  handles this gracefully but we surface the actual mode used in the
  emitted report so auditors can distinguish the two situations).
* ``"tool-calls"`` is reserved for a future milestone that surfaces
  per-collector tool-call counts; today the orchestrator does not yet
  capture them, so we raise :class:`CostEvidenceError` if the caller
  asks for that mode without an explicit weight map.
* Any other ``attribution_mode`` value raises
  :class:`CostEvidenceError` BEFORE the cost directory is touched —
  invalid input never leaves a half-written tree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..atomic_io import write_atomic_text
from ..common import compact_json, ensure_dir, iso_now
from ..usage_parsers import UsageMetrics
from .cost_attribution import (
    AttributionError,
    CollectorCostShare,
    attribute_cost_by_duration,
    attribute_cost_uniform,
)

if TYPE_CHECKING:
    from ..collector_config import CollectorOutcome


__all__ = [
    "CostEvidenceError",
    "GateCostReport",
    "RESERVED_COLLECTOR_IDS",
    "VALID_COST_ATTRIBUTION_MODES",
    "collector_cost_path",
    "emit_gate_cost_report",
    "get_cost_root_dir",
    "load_collector_cost_share",
    "load_gate_cost_report",
    "summary_path",
]


# Per-collector files share a directory with the gate summary
# (``summary.json``) so any collector_id whose ``<id>.json`` collides
# with an internal filename would silently overwrite either the share
# or the summary depending on write order. ``emit_gate_cost_report``
# writes per-collector files BEFORE the summary, so a collector named
# ``"summary"`` would have its share destroyed by the summary write at
# l.~407-409 — losing the per-collector record AND breaking the
# "on-disk collector set always matches summary" invariant the prune
# step at l.~376-381 documents. Reject reserved names BEFORE touching
# disk so a half-written tree is impossible. Lowercase only — match
# the registry convention documented at :func:`collector_cost_path`.
RESERVED_COLLECTOR_IDS: frozenset[str] = frozenset({"summary"})


class CostEvidenceError(ValueError):
    """Raised for invalid input to :func:`emit_gate_cost_report`.

    Used for the "operator told us something illegal" path: empty
    collector list, unsupported ``attribution_mode``, malformed
    on-disk JSON during load. We deliberately do NOT raise this for
    "I/O failed mid-write" because the orchestrator already wraps
    emission in ``try/except`` and converts every failure into a
    silent best-effort skip.
    """


# Closed vocabulary for ``attribution_mode``. ``"tool-calls"`` is
# included for forward-compat: when the orchestrator starts capturing
# per-collector tool-call counts the helper below will accept the
# weight map and dispatch to :func:`attribute_cost_by_tool_calls`.
VALID_COST_ATTRIBUTION_MODES: tuple[str, ...] = (
    "uniform",
    "duration",
    "tool-calls",
)


@dataclass(frozen=True)
class GateCostReport:
    """The summary payload persisted under ``_bmad/gate/cost/<gate_id>/``.

    Frozen so the orchestrator can return it to a caller without
    worrying about downstream mutation. ``per_collector`` is a
    ``tuple`` of :class:`CollectorCostShare` (also frozen) — preserves
    the original input ordering so a caller scanning the tuple sees
    collectors in the same order the registry produced them.
    """

    gate_id: str
    session_usage: UsageMetrics
    per_collector: tuple[CollectorCostShare, ...]
    attribution_mode: str
    total_cost_usd: float
    collector_count: int
    timestamp_iso: str


# ---------------------------------------------------------------------------
# Disk layout helpers
# ---------------------------------------------------------------------------


_COST_DIRNAME = "cost"


def get_cost_root_dir(project_root: str | Path, gate_id: str) -> Path:
    """Return ``_bmad/gate/cost/<gate_id>/``, creating it on demand.

    Lives as a SIBLING of ``_bmad/gate/evidence/`` (not a child) so a
    Merkle re-walk of the evidence bundle for a given gate never sees
    cost files — they are observability, not evidence.
    """

    path = Path(project_root) / "_bmad" / "gate" / _COST_DIRNAME / gate_id
    ensure_dir(path)
    return path


def summary_path(project_root: str | Path, gate_id: str) -> Path:
    """Path of the per-gate summary JSON."""

    return get_cost_root_dir(project_root, gate_id) / "summary.json"


def collector_cost_path(
    project_root: str | Path, gate_id: str, collector_id: str,
) -> Path:
    """Path of one collector's share JSON.

    No filename sanitization is performed HERE — collector ids are
    produced by the registry which constrains them to a safe character
    set (lowercase, hyphen, digits). Callers passing arbitrary strings
    get whatever ``Path`` does with them. The emit-side guard at
    :func:`emit_gate_cost_report` rejects ``..`` / ``/`` / ``\\`` in
    collector_ids BEFORE disk touch so the per-gate-dir isolation
    invariant is preserved; this helper is read-only and trusts callers
    that route through emission.
    """

    return get_cost_root_dir(project_root, gate_id) / f"{collector_id}.json"


# ---------------------------------------------------------------------------
# Internal serialization
# ---------------------------------------------------------------------------


def _share_to_json(share: CollectorCostShare) -> dict[str, object]:
    return {
        "collector_id": share.collector_id,
        "input_tokens": share.input_tokens,
        "output_tokens": share.output_tokens,
        "cost_usd": share.cost_usd,
        "duration_s": share.duration_s,
        "attribution_mode": share.attribution_mode,
    }


def _share_from_json(data: dict[str, object]) -> CollectorCostShare:
    return CollectorCostShare(
        collector_id=str(data["collector_id"]),
        input_tokens=int(data["input_tokens"]),  # type: ignore[arg-type]
        output_tokens=int(data["output_tokens"]),  # type: ignore[arg-type]
        cost_usd=float(data["cost_usd"]),  # type: ignore[arg-type]
        duration_s=float(data["duration_s"]),  # type: ignore[arg-type]
        attribution_mode=str(data["attribution_mode"]),
    )


def _usage_to_json(usage: UsageMetrics) -> dict[str, object]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_cost_usd": usage.total_cost_usd,
        "tool_calls_count": usage.tool_calls_count,
        "duration_s": usage.duration_s,
    }


def _usage_from_json(data: dict[str, object]) -> UsageMetrics:
    return UsageMetrics(
        input_tokens=int(data.get("input_tokens", 0)),  # type: ignore[arg-type]
        output_tokens=int(data.get("output_tokens", 0)),  # type: ignore[arg-type]
        total_cost_usd=float(data.get("total_cost_usd", 0.0)),  # type: ignore[arg-type]
        tool_calls_count=int(data.get("tool_calls_count", 0)),  # type: ignore[arg-type]
        duration_s=float(data.get("duration_s", 0.0)),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Attribution dispatch
# ---------------------------------------------------------------------------


def _attribute(
    session: UsageMetrics,
    collector_outcomes: list["CollectorOutcome"],
    attribution_mode: str,
) -> tuple[list[CollectorCostShare], str]:
    """Run the requested attribution mode against ``collector_outcomes``.

    Returns ``(shares, actual_mode)`` — ``actual_mode`` may differ
    from the requested ``attribution_mode`` when we fall back to
    uniform (e.g. all-zero durations under ``"duration"`` mode). The
    summary payload records ``actual_mode`` so auditors can tell.
    """

    collector_ids = [o.config.collector_id for o in collector_outcomes]
    if attribution_mode == "uniform":
        return attribute_cost_uniform(session, collector_ids), "uniform"

    if attribution_mode == "duration":
        durations_ms: dict[str, float] = {}
        total_duration = 0.0
        for outcome in collector_outcomes:
            raw = outcome.evidence.get("duration_ms", 0)
            try:
                ms = float(raw)
            except (TypeError, ValueError):
                ms = 0.0
            if ms < 0:
                ms = 0.0
            durations_ms[outcome.config.collector_id] = ms
            total_duration += ms
        if total_duration <= 0:
            # No signal — degrade to uniform so the report still
            # carries a useful breakdown. We expose the actual mode in
            # the summary so this fallback is auditable.
            return attribute_cost_uniform(session, collector_ids), "uniform"
        return (
            attribute_cost_by_duration(session, durations_ms),
            "duration",
        )

    if attribution_mode == "tool-calls":
        # Reserved for future milestone — the orchestrator does not
        # yet capture per-collector tool-call counts in the evidence
        # dict. Fail loudly rather than silently falling back so the
        # mismatch is visible to operators.
        raise CostEvidenceError(
            "attribution_mode='tool-calls' requires per-collector "
            "tool_calls counts which are not yet captured by the "
            "orchestrator; use 'duration' or 'uniform'",
        )

    raise CostEvidenceError(
        f"unknown attribution_mode: {attribution_mode!r}; "
        f"valid modes are {VALID_COST_ATTRIBUTION_MODES}",
    )


# ---------------------------------------------------------------------------
# Public emit + load surface
# ---------------------------------------------------------------------------


def emit_gate_cost_report(
    project_root: str | Path,
    gate_id: str,
    session_usage: UsageMetrics,
    collector_outcomes: list["CollectorOutcome"],
    *,
    attribution_mode: str = "duration",
    timestamp_iso: str | None = None,
) -> GateCostReport:
    """Compute and persist per-collector cost shares for a gate.

    Atomically writes one ``summary.json`` plus one
    ``<collector_id>.json`` per collector under
    ``_bmad/gate/cost/<gate_id>/``. Returns the in-memory
    :class:`GateCostReport` so the caller can embed (e.g.) the total
    cost on the gate file.

    Raises :class:`CostEvidenceError` BEFORE touching disk when:

    * ``collector_outcomes`` is empty,
    * ``collector_outcomes`` contains a duplicate ``collector_id``
      (rejected symmetrically across all attribution modes — see the
      duplicate-id guard below),
    * ``attribution_mode`` is not in
      :data:`VALID_COST_ATTRIBUTION_MODES`,
    * ``attribution_mode == "tool-calls"`` (not yet captured by the
      orchestrator — see :func:`_attribute`).

    All-zero durations under the default mode silently fall back to
    uniform attribution. The ``attribution_mode`` field on the
    persisted summary reflects the actual mode used so callers can
    distinguish "operator asked for uniform" from "operator asked for
    duration but all collectors reported zero".
    """

    if not collector_outcomes:
        raise CostEvidenceError(
            "collector_outcomes must be non-empty; got empty list",
        )
    if attribution_mode not in VALID_COST_ATTRIBUTION_MODES:
        raise CostEvidenceError(
            f"unknown attribution_mode: {attribution_mode!r}; "
            f"valid modes are {VALID_COST_ATTRIBUTION_MODES}",
        )
    # Duplicate-id guard — runs BEFORE attribution dispatch so both
    # "uniform" and "duration" modes reject the same illegal input
    # symmetrically. Without this, duration mode silently collapses
    # duplicate ids in its weight dict while still summing both into
    # the total — producing a report whose collector_count and per-
    # share weights disagree. Uniform mode raises via
    # cost_attribution._require_collectors; we want parity.
    cids = [o.config.collector_id for o in collector_outcomes]
    seen: set[str] = set()
    dupes: list[str] = []
    for cid in cids:
        if cid in seen and cid not in dupes:
            dupes.append(cid)
        seen.add(cid)
    if dupes:
        raise CostEvidenceError(
            "duplicate collector_id in outcomes: "
            f"{', '.join(repr(d) for d in dupes)}",
        )
    # Reserved-name guard — per-collector files (``<id>.json``) share
    # a directory with internal files like ``summary.json``. A
    # collector_id collision with a reserved name would silently
    # overwrite either the share or the summary depending on write
    # order, breaking the "on-disk collector set matches summary"
    # invariant at l.~376-381 and turning load_collector_cost_share
    # into a malformed-share error path. Reject BEFORE disk touch.
    reserved = [cid for cid in cids if cid in RESERVED_COLLECTOR_IDS]
    if reserved:
        raise CostEvidenceError(
            "collector_id collides with reserved internal filename: "
            f"{', '.join(repr(r) for r in reserved)}",
        )
    # Path-traversal guard — symmetric with the reserved-name guard
    # above. ``collector_cost_path`` joins ``<id>.json`` onto the
    # per-gate cost dir; if ``id`` contains ``..`` segments or path
    # separators, the resulting Path resolves OUTSIDE the per-gate
    # directory (e.g. ``id='../escaped'`` lands at
    # ``cost/escaped.json`` — sibling of the gate dir). That breaks
    # the prune loop at l.~436-445 (which only scans ``cost_dir``),
    # silently round-trips through ``load_collector_cost_share``, and
    # diverges the on-disk collector set from the persisted summary.
    # The registry constrains production collector_ids to lowercase
    # ASCII / digits / hyphen (see ``collector_cost_path`` docstring),
    # but the registry does NOT enforce this — a hand-registered
    # CollectorConfig with a traversal id reaches this point. Reject
    # BEFORE disk touch so a half-written tree is impossible.
    traversal: list[str] = []
    for cid in cids:
        if ".." in Path(cid).parts or "/" in cid or "\\" in cid:
            traversal.append(cid)
    if traversal:
        raise CostEvidenceError(
            "collector_id contains path traversal segments: "
            f"{', '.join(repr(t) for t in traversal)}",
        )

    try:
        shares, actual_mode = _attribute(
            session_usage, collector_outcomes, attribution_mode,
        )
    except AttributionError as exc:
        raise CostEvidenceError(str(exc)) from exc

    ts = timestamp_iso if timestamp_iso is not None else iso_now()
    report = GateCostReport(
        gate_id=gate_id,
        session_usage=session_usage,
        per_collector=tuple(shares),
        attribution_mode=actual_mode,
        total_cost_usd=float(session_usage.total_cost_usd),
        collector_count=len(shares),
        timestamp_iso=ts,
    )

    # Persist — atomic writes so a crash mid-emit never leaves a
    # partially-written summary. Per-collector files are written
    # FIRST so a successful summary.json implies all collector
    # records are durable. Stale ``<collector_id>.json`` files from a
    # previous emit for the same gate_id are unlinked AFTER the
    # summary.json write lands — so a partial re-emit that crashes
    # between the new per-collector writes and the new summary write
    # rolls back cleanly: the OLD summary.json (preserved via
    # atomic-replace) still matches OLD per-collector files on disk,
    # because no ghosts have been pruned yet. Pruning BEFORE summary
    # write would have created the inverse failure mode: old summary
    # references collectors whose files were just deleted.
    cost_dir = get_cost_root_dir(project_root, gate_id)
    for share in shares:
        share_path = cost_dir / f"{share.collector_id}.json"
        write_atomic_text(share_path, compact_json(_share_to_json(share)))

    summary_payload = {
        "gate_id": report.gate_id,
        "session_usage": _usage_to_json(session_usage),
        "per_collector": [_share_to_json(s) for s in shares],
        "attribution_mode": actual_mode,
        "total_cost_usd": report.total_cost_usd,
        "collector_count": report.collector_count,
        "timestamp_iso": report.timestamp_iso,
    }
    write_atomic_text(
        cost_dir / "summary.json", compact_json(summary_payload),
    )

    # Prune ghost per-collector files left over from prior emissions
    # for the same gate_id (e.g. crashed-recovery / remediation cycles
    # where the collector set shrank between runs). Without this, the
    # cost dir listing diverges from summary.json's ``per_collector``
    # tuple and load_collector_cost_share returns stale data. Pruning
    # runs AFTER the new summary.json is durable so a failed summary
    # write rolls back to a state where the OLD summary still matches
    # the on-disk collector set (ghosts survive — they are dropped on
    # the next successful re-emit).
    kept = {f"{s.collector_id}.json" for s in shares}
    kept.add("summary.json")
    try:
        existing = list(cost_dir.iterdir())
    except OSError:
        existing = []
    for entry in existing:
        name = entry.name
        if not name.endswith(".json") or name in kept:
            continue
        try:
            entry.unlink()
        except OSError:
            # Best-effort prune — observability, not gating. A leftover
            # ghost is worse than ignored, but emission must not abort.
            pass

    return report


def load_gate_cost_report(
    project_root: str | Path, gate_id: str,
) -> GateCostReport | None:
    """Round-trip the persisted summary back into memory.

    Returns ``None`` when the summary file is missing — callers that
    need to distinguish "never emitted" from "emitted with zero
    shares" should compare against ``None`` rather than checking
    ``report.collector_count``.
    """

    sp = summary_path(project_root, gate_id)
    if not sp.is_file():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostEvidenceError(
            f"failed to load summary at {sp}: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise CostEvidenceError(
            f"summary at {sp} is not a JSON object",
        )

    per_collector_raw = data.get("per_collector", [])
    if not isinstance(per_collector_raw, list):
        raise CostEvidenceError(
            f"per_collector field in {sp} must be a list",
        )
    try:
        shares = tuple(
            _share_from_json(entry)
            for entry in per_collector_raw
            if isinstance(entry, dict)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CostEvidenceError(
            f"malformed per_collector share at {sp}: {exc}",
        ) from exc
    return GateCostReport(
        gate_id=str(data.get("gate_id", "")),
        session_usage=_usage_from_json(
            data.get("session_usage", {})
            if isinstance(data.get("session_usage"), dict) else {},
        ),
        per_collector=shares,
        attribution_mode=str(data.get("attribution_mode", "uniform")),
        total_cost_usd=float(data.get("total_cost_usd", 0.0)),
        # Derive collector_count from len(shares) ALWAYS — mirrors the
        # emit-side invariant at l.359 (collector_count=len(shares)) so
        # the in-memory dataclass is internally consistent even when
        # legacy / hand-edited summary.json carries a stale on-disk
        # collector_count or non-dict per_collector entries silently
        # dropped by the isinstance(entry, dict) filter above. The
        # asymmetric "trust on-disk number" path used to surface
        # (collector_count=N, len(per_collector)<N) tuples to operator
        # audits with no warning.
        collector_count=len(shares),
        timestamp_iso=str(data.get("timestamp_iso", "")),
    )


def load_collector_cost_share(
    project_root: str | Path, gate_id: str, collector_id: str,
) -> CollectorCostShare | None:
    """Load one collector's share. Returns ``None`` when absent."""

    path = collector_cost_path(project_root, gate_id, collector_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostEvidenceError(
            f"failed to load collector share at {path}: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise CostEvidenceError(
            f"collector share at {path} is not a JSON object",
        )
    try:
        return _share_from_json(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise CostEvidenceError(
            f"malformed collector share at {path}: {exc}",
        ) from exc
