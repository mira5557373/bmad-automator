"""Cost attribution — distribute a session :class:`UsageMetrics` across
the collectors that ran inside it.

This module is the substrate for per-collector cost attribution. The
"C3" follow-up has shipped: :mod:`story_automator.core.innovation.cost_evidence`
(via :func:`~story_automator.core.innovation.cost_evidence.emit_gate_cost_report`)
calls :func:`attribute_cost_uniform` and :func:`attribute_cost_by_duration`
from inside :func:`story_automator.core.gate_orchestrator.run_production_gate`,
so each :class:`CollectorOutcome` records the share of session cost it was
responsible for.

Three attribution modes are supported, in order of fidelity:

* **uniform** — divide session cost equally across the collectors.
  Cheapest, most defensible, the right default when no per-collector
  signal is available.
* **duration-weighted** — divide proportional to per-collector
  wall-clock duration. Best when collectors differ by an order of
  magnitude in execution time (e.g. lint vs. an integration test
  suite).
* **tool-call-weighted** — divide proportional to per-collector tool
  call counts. Useful when LLM tool calls dominate cost (RAMR routes
  P0 collectors to reasoning-strong CLIs that may make many tool
  calls).

All three modes preserve sum-of-shares == session total exactly.
The integer fields (``input_tokens``, ``output_tokens``) preserve the
invariant via exact :class:`fractions.Fraction` arithmetic in
:func:`_split_int` (largest-remainder distribution over rational
weights), so the sum is exact for any ``int`` total — including
totals beyond the float64 mantissa boundary (``2**53``). The float
fields (``total_cost_usd`` and ``duration_s``) absorb any
floating-point drift into the final non-zero share in
:func:`_split_float`, so the invariant also holds for them.

The helpers are pure functions: they accept a session :class:`UsageMetrics`
plus per-collector signals and return a list of :class:`CollectorCostShare`
records in the same order as the input collector ids. They never read
from disk, never mutate inputs, and raise :class:`AttributionError` on
illegal input (e.g. empty collector list).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from ..usage_parsers import UsageMetrics


__all__ = [
    "AttributionError",
    "CollectorCostShare",
    "VALID_ATTRIBUTION_MODES",
    "attribute_cost_uniform",
    "attribute_cost_by_duration",
    "attribute_cost_by_tool_calls",
]


class AttributionError(ValueError):
    """Raised on invalid inputs to the cost-attribution helpers.

    Examples: an empty ``collector_ids`` list, a duration map with
    negative values, a tool-call map containing non-integer counts.
    """


VALID_ATTRIBUTION_MODES: tuple[str, ...] = (
    "uniform",
    "duration-weighted",
    "tool-call-weighted",
)
"""Recommended vocabulary for :attr:`CollectorCostShare.attribution_mode`
*when shares are produced by this module's helpers*.

The three public helpers (:func:`attribute_cost_uniform`,
:func:`attribute_cost_by_duration`, :func:`attribute_cost_by_tool_calls`)
always tag their output shares with one of these literals. Downstream
consumers (e.g. :mod:`~story_automator.core.innovation.cost_evidence`)
re-tag with their own controlled vocabulary on persist / load, so
:class:`CollectorCostShare` instances reaching disk-aware callers may
legitimately carry a different string (e.g. ``"duration"`` /
``"tool-calls"``). The dataclass itself does NOT enforce membership —
``CollectorCostShare(..., attribution_mode="anything")`` is constructible
— precisely because the substrate is shared by multiple persistence
vocabularies. Callers that require a closed-vocabulary check must do so
explicitly against the vocabulary appropriate to *their* layer (see
:data:`story_automator.core.innovation.cost_evidence.VALID_COST_ATTRIBUTION_MODES`
for the on-disk vocab)."""


@dataclass(frozen=True)
class CollectorCostShare:
    """One collector's share of a session's usage + cost.

    The dataclass is frozen so callers can safely intern or hash a
    share. ``attribution_mode`` records *how* this share was computed
    so downstream audit can distinguish a uniform fallback from a
    duration-weighted estimate.

    ``attribution_mode`` is a free-form ``str`` by design — see
    :data:`VALID_ATTRIBUTION_MODES` for the recommended vocabulary
    when constructing shares via this module's helpers, but downstream
    persistence layers (notably
    :mod:`~story_automator.core.innovation.cost_evidence`) may carry
    their own controlled vocabulary on shares loaded from disk.
    """

    collector_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_s: float
    attribution_mode: str


# ---------------------------------------------------------------------------
# Helpers (internal)
# ---------------------------------------------------------------------------


def _require_collectors(collector_ids: list[str]) -> None:
    if not collector_ids:
        raise AttributionError("collector_ids must be non-empty")
    seen: set[str] = set()
    for cid in collector_ids:
        if not isinstance(cid, str) or not cid:
            raise AttributionError(
                f"collector_ids entries must be non-empty strings; got {cid!r}"
            )
        if cid in seen:
            raise AttributionError(f"duplicate collector_id: {cid!r}")
        seen.add(cid)


def _require_finite_session(session: UsageMetrics) -> None:
    """Reject sessions whose totals would later poison ``_split_*``.

    :class:`UsageMetrics` documents "All fields are non-negative" but
    is a plain frozen dataclass without ``__post_init__`` validation —
    so a malformed parser (or a hand-built fixture) can construct a
    session carrying ``float('inf')`` / ``float('nan')`` in
    ``total_cost_usd`` / ``duration_s``, or a negative count in the
    ``int`` fields. Both classes of value would flow into
    :func:`_split_int` / :func:`_split_float` and produce wrong shares
    (the int path's ``total <= 0`` guard catches negatives but the
    float path raises a bare ``OverflowError`` / ``ValueError`` on
    ``Fraction(inf)`` / ``Fraction(nan)`` that bypasses the
    ``AttributionError`` contract).

    Mirrors the symmetry of :func:`_check_weight_map`: weights already
    reject non-finite / negative; session totals must too.
    """
    if session.total_cost_usd != session.total_cost_usd or not math.isfinite(
        session.total_cost_usd
    ):
        raise AttributionError(
            f"session.total_cost_usd must be finite; got {session.total_cost_usd}"
        )
    if session.total_cost_usd < 0:
        raise AttributionError(
            f"session.total_cost_usd must be non-negative; got {session.total_cost_usd}"
        )
    if session.duration_s != session.duration_s or not math.isfinite(
        session.duration_s
    ):
        raise AttributionError(
            f"session.duration_s must be finite; got {session.duration_s}"
        )
    if session.duration_s < 0:
        raise AttributionError(
            f"session.duration_s must be non-negative; got {session.duration_s}"
        )
    if session.input_tokens < 0:
        raise AttributionError(
            f"session.input_tokens must be non-negative; got {session.input_tokens}"
        )
    if session.output_tokens < 0:
        raise AttributionError(
            f"session.output_tokens must be non-negative; got {session.output_tokens}"
        )


def _split_int(total: int, weights: list[float | int]) -> list[int]:
    """Split ``total`` (int) across ``weights`` (sum == 1.0 ideally).

    Uses floor-then-distribute-remainder so the sum of the returned
    list equals ``total`` exactly. Negative weights are treated as 0.

    The apportionment is done in exact rational arithmetic via
    :class:`fractions.Fraction` so the sum-of-shares invariant holds
    for any ``int`` total — including totals larger than ``2**53``
    where ``total * w / total_w`` in pure float arithmetic would lose
    integer precision (the float64 mantissa is 53 bits).

    ``weights`` may carry plain ``int`` entries: when callers have
    exact integer weights (e.g. per-collector tool-call counts) they
    must NOT pre-cast to ``float`` because pairs of ints above the
    float64 mantissa boundary (e.g. ``2**60`` vs ``2**60+1``) collapse
    to the same float and lose their distinguishing precision before
    :class:`Fraction` ever sees them. Passing ints through unchanged
    preserves their exact value through the rational arithmetic below.
    """

    n = len(weights)
    if total <= 0 or n == 0:
        return [0] * n
    clean: list[float | int] = [
        w if (w > 0 and math.isfinite(w)) else 0.0 for w in weights
    ]
    total_w = sum(clean)
    if not math.isfinite(total_w) or total_w <= 0:
        # Fall back to uniform when weights are degenerate (or when two
        # huge-but-finite weights overflowed to ``inf`` on summation) so
        # the invariant (sum of shares == total) still holds.
        return _split_int(total, [1.0] * n)
    # Exact rational apportionment: convert each finite non-negative
    # weight to a :class:`Fraction` and compute ``total * w / sum(w)``
    # in rational space. ``int(Fraction)`` truncates toward zero, which
    # equals floor for non-negative values. ``Fraction`` accepts both
    # ``int`` (exact) and ``float`` (IEEE-754, exact rational of the
    # demoted value) inputs — see the ``weights`` note above for why
    # callers should pass ints when they have them.
    frac_weights = [Fraction(w) for w in clean]
    frac_total_w = sum(frac_weights, Fraction(0))
    frac_total = Fraction(total)
    raw_fracs = [frac_total * w / frac_total_w for w in frac_weights]
    floors = [int(rf) for rf in raw_fracs]
    remainder = total - sum(floors)
    # Distribute the leftover units to the largest fractional parts.
    # ``remainder`` is bounded by ``n - (#zero-weight collectors)`` so
    # the slice never runs past the end of ``fractions``.
    fractions_sorted = sorted(
        range(n),
        key=lambda i: (raw_fracs[i] - floors[i], clean[i]),
        reverse=True,
    )
    for idx in fractions_sorted[: max(0, remainder)]:
        floors[idx] += 1
    return floors


def _split_float(total: float, weights: list[float | int]) -> list[float]:
    """Split ``total`` (float) across ``weights``.

    Adjusts the final share so the sum equals ``total`` exactly,
    absorbing any floating-point drift.

    ``weights`` may carry plain ``int`` entries; the ratio
    ``total * w / sum(w)`` is computed via :class:`Fraction` so two
    integer weights that differ below the float64 ULP at their
    magnitude (e.g. ``2**62`` vs ``2**62 + 2**10``) still produce
    distinct shares — the final float coercion happens only at the
    return boundary so the per-collector ordering is preserved.
    """

    n = len(weights)
    if total <= 0 or n == 0:
        return [0.0] * n
    clean: list[float | int] = [
        w if (w > 0 and math.isfinite(w)) else 0.0 for w in weights
    ]
    total_w = sum(clean)
    if not math.isfinite(total_w) or total_w <= 0:
        return _split_float(total, [1.0] * n)
    # Compute the ratio in exact rational arithmetic so int weights
    # that exceed the float64 mantissa precision (53 bits) keep their
    # distinguishing value. ``Fraction(float)`` is exact for any
    # finite float, so float weights round-trip unchanged.
    frac_total = Fraction(total)
    frac_total_w = Fraction(total_w)
    raw = [float(frac_total * Fraction(w) / frac_total_w) for w in clean]
    # Absorb floating-point drift into the final non-zero entry so the
    # sum invariant holds for callers' equality tests.
    drift = total - sum(raw)
    if drift:
        for i in range(n - 1, -1, -1):
            if clean[i] > 0:
                raw[i] += drift
                break
    return raw


# ---------------------------------------------------------------------------
# Public attribution functions
# ---------------------------------------------------------------------------


def attribute_cost_uniform(
    session: UsageMetrics,
    collector_ids: list[str],
) -> list[CollectorCostShare]:
    """Divide ``session`` equally across ``collector_ids``.

    Returns one :class:`CollectorCostShare` per id, in the same order.
    Raises :class:`AttributionError` if ``collector_ids`` is empty or
    contains duplicates / non-string entries, or if ``session`` carries
    non-finite / negative totals.
    """

    _require_finite_session(session)
    _require_collectors(collector_ids)
    n = len(collector_ids)
    weights = [1.0] * n

    in_shares = _split_int(session.input_tokens, weights)
    out_shares = _split_int(session.output_tokens, weights)
    cost_shares = _split_float(session.total_cost_usd, weights)
    dur_shares = _split_float(session.duration_s, weights)

    return [
        CollectorCostShare(
            collector_id=cid,
            input_tokens=in_shares[i],
            output_tokens=out_shares[i],
            cost_usd=cost_shares[i],
            duration_s=dur_shares[i],
            attribution_mode="uniform",
        )
        for i, cid in enumerate(collector_ids)
    ]


def _check_weight_map(weights: dict[str, float], label: str) -> None:
    if not weights:
        raise AttributionError(f"{label} must be non-empty")
    for cid, val in weights.items():
        if not isinstance(cid, str) or not cid:
            raise AttributionError(
                f"{label} keys must be non-empty strings; got {cid!r}"
            )
        try:
            fval = float(val)
        except (TypeError, ValueError) as exc:
            raise AttributionError(
                f"{label}[{cid!r}] must be numeric; got {val!r}"
            ) from exc
        if not math.isfinite(fval):
            # ``NaN`` and ``inf`` would later flow into ``_split_int`` /
            # ``_split_float`` and produce ``NaN`` shares (``int(NaN)``
            # raises a bare ``ValueError`` that bypasses the
            # ``AttributionError`` contract). Reject up-front instead.
            raise AttributionError(
                f"{label}[{cid!r}] must be finite; got {fval}"
            )
        if fval < 0:
            raise AttributionError(
                f"{label}[{cid!r}] must be non-negative; got {fval}"
            )


def attribute_cost_by_duration(
    session: UsageMetrics,
    durations_s: dict[str, float],
) -> list[CollectorCostShare]:
    """Distribute ``session`` weighted by per-collector duration.

    Returns one share per collector_id in ``durations_s``, in the
    iteration order of the mapping. A collector with zero duration
    receives a zero share unless *all* durations are zero — in which
    case the function degrades gracefully to uniform attribution so
    the sum invariant holds.

    Raises :class:`AttributionError` on empty / negative input, or if
    ``session`` carries non-finite / negative totals.
    """

    _require_finite_session(session)
    _check_weight_map(durations_s, "durations_s")
    collector_ids = list(durations_s.keys())
    _require_collectors(collector_ids)
    weights = [float(durations_s[cid]) for cid in collector_ids]

    in_shares = _split_int(session.input_tokens, weights)
    out_shares = _split_int(session.output_tokens, weights)
    cost_shares = _split_float(session.total_cost_usd, weights)
    dur_shares = _split_float(session.duration_s, weights)

    return [
        CollectorCostShare(
            collector_id=cid,
            input_tokens=in_shares[i],
            output_tokens=out_shares[i],
            cost_usd=cost_shares[i],
            duration_s=dur_shares[i],
            attribution_mode="duration-weighted",
        )
        for i, cid in enumerate(collector_ids)
    ]


def attribute_cost_by_tool_calls(
    session: UsageMetrics,
    tool_calls: dict[str, int],
) -> list[CollectorCostShare]:
    """Distribute ``session`` weighted by per-collector tool-call count.

    Mirrors :func:`attribute_cost_by_duration` but uses tool calls as
    the weight signal. A zero-total tool-call map degrades to uniform
    attribution.

    Raises :class:`AttributionError` on empty / negative / non-integer
    input, or if ``session`` carries non-finite / negative totals.
    """

    _require_finite_session(session)
    _check_weight_map(tool_calls, "tool_calls")
    for cid, val in tool_calls.items():
        if not isinstance(val, int) or isinstance(val, bool):
            raise AttributionError(
                f"tool_calls[{cid!r}] must be an int; got {type(val).__name__}"
            )

    collector_ids = list(tool_calls.keys())
    _require_collectors(collector_ids)
    # Keep tool-call weights as ``int`` — passing them through
    # ``float()`` first would collapse pairs that differ below the
    # float64 ULP at their magnitude (e.g. ``2**60`` and ``2**60+1``
    # demote to the same float), erasing the precision the underlying
    # rational arithmetic in :func:`_split_int` / :func:`_split_float`
    # is designed to preserve.
    weights: list[float | int] = [tool_calls[cid] for cid in collector_ids]

    in_shares = _split_int(session.input_tokens, weights)
    out_shares = _split_int(session.output_tokens, weights)
    cost_shares = _split_float(session.total_cost_usd, weights)
    dur_shares = _split_float(session.duration_s, weights)

    return [
        CollectorCostShare(
            collector_id=cid,
            input_tokens=in_shares[i],
            output_tokens=out_shares[i],
            cost_usd=cost_shares[i],
            duration_s=dur_shares[i],
            attribution_mode="tool-call-weighted",
        )
        for i, cid in enumerate(collector_ids)
    ]
