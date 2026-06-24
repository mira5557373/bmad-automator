"""Tests for :mod:`story_automator.core.innovation.cost_attribution`."""

from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError

from story_automator.core.innovation.cost_attribution import (
    AttributionError,
    CollectorCostShare,
    VALID_ATTRIBUTION_MODES,
    attribute_cost_by_duration,
    attribute_cost_by_tool_calls,
    attribute_cost_uniform,
)
from story_automator.core.usage_parsers import UsageMetrics


SESSION = UsageMetrics(
    input_tokens=900,
    output_tokens=300,
    total_cost_usd=0.123456,
    tool_calls_count=12,
    duration_s=60.0,
)


class UniformAttributionTests(unittest.TestCase):
    def test_uniform_distributes_equally(self) -> None:
        shares = attribute_cost_uniform(SESSION, ["a", "b", "c"])
        self.assertEqual(len(shares), 3)
        # Tokens are integers — should each be 300 / 100.
        self.assertEqual([s.input_tokens for s in shares], [300, 300, 300])
        self.assertEqual([s.output_tokens for s in shares], [100, 100, 100])
        # Sum-of-cost should equal the session cost.
        self.assertAlmostEqual(
            sum(s.cost_usd for s in shares),
            SESSION.total_cost_usd,
        )

    def test_uniform_handles_zero_session(self) -> None:
        zero = UsageMetrics()
        shares = attribute_cost_uniform(zero, ["a", "b"])
        for share in shares:
            self.assertEqual(share.input_tokens, 0)
            self.assertEqual(share.output_tokens, 0)
            self.assertEqual(share.cost_usd, 0.0)
            self.assertEqual(share.duration_s, 0.0)
            self.assertEqual(share.attribution_mode, "uniform")

    def test_uniform_empty_collector_list_raises(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_uniform(SESSION, [])

    def test_uniform_duplicate_collector_raises(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_uniform(SESSION, ["a", "a"])

    def test_uniform_int_token_sum_invariant(self) -> None:
        # 901 / 3 must still sum to 901 — the floor-then-distribute
        # remainder logic guarantees the exact-integer invariant.
        session = UsageMetrics(input_tokens=901, output_tokens=901)
        shares = attribute_cost_uniform(session, ["a", "b", "c"])
        self.assertEqual(sum(s.input_tokens for s in shares), 901)
        self.assertEqual(sum(s.output_tokens for s in shares), 901)

    def test_uniform_int_token_sum_invariant_beyond_float64_mantissa(self) -> None:
        # Regression for round-2 bug sweep finding:
        # ``_split_int`` used to apportion via ``total * w / total_w``
        # in float arithmetic, which silently dropped integer precision
        # once ``total`` exceeded ``2**53`` (the float64 mantissa is 53
        # bits). The leftover-remainder loop then could not recover the
        # lost units when the drop exceeded ``n``. Pre-fix reproducer:
        # ``_split_int(2**63, [1.0]*3)`` summed to ``2**63 - 509``
        # instead of ``2**63``. The fix uses exact rational arithmetic
        # via :class:`fractions.Fraction` so the documented "sum equals
        # total exactly" invariant holds at any int scale.
        for total in (2**53 + 7, 2**56 + 13, 2**63):
            session = UsageMetrics(input_tokens=total, output_tokens=total)
            shares = attribute_cost_uniform(session, ["a", "b", "c"])
            self.assertEqual(
                sum(s.input_tokens for s in shares),
                total,
                f"input_tokens sum drift at total={total}",
            )
            self.assertEqual(
                sum(s.output_tokens for s in shares),
                total,
                f"output_tokens sum drift at total={total}",
            )


class DurationWeightedAttributionTests(unittest.TestCase):
    def test_by_duration_weighted_correctly(self) -> None:
        durations = {"a": 10.0, "b": 30.0, "c": 60.0}
        shares = attribute_cost_by_duration(SESSION, durations)
        # 100 / (10 + 30 + 60) = 1; so a gets 10%, b gets 30%, c gets 60%.
        cost_by_id = {s.collector_id: s.cost_usd for s in shares}
        self.assertAlmostEqual(cost_by_id["a"] / SESSION.total_cost_usd, 0.1)
        self.assertAlmostEqual(cost_by_id["b"] / SESSION.total_cost_usd, 0.3)
        # Final share absorbs any drift, so allow a tiny epsilon for c.
        total_share = sum(s.cost_usd for s in shares)
        self.assertAlmostEqual(total_share, SESSION.total_cost_usd)

    def test_by_duration_zero_total_handles_safely(self) -> None:
        durations = {"a": 0.0, "b": 0.0}
        shares = attribute_cost_by_duration(SESSION, durations)
        # Degenerate weights -> uniform fallback; sum invariant holds.
        self.assertAlmostEqual(
            sum(s.cost_usd for s in shares),
            SESSION.total_cost_usd,
        )
        # Each share keeps the attribution_mode = "duration-weighted"
        # label so audit can see the input was duration-shaped even
        # though the values were degenerate.
        for share in shares:
            self.assertEqual(share.attribution_mode, "duration-weighted")

    def test_by_duration_negative_raises(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_by_duration(SESSION, {"a": -1.0, "b": 1.0})

    def test_by_duration_empty_raises(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_by_duration(SESSION, {})

    def test_by_duration_inf_weight_raises_attribution_error(self) -> None:
        # Regression: before the fix, ``inf`` slipped past the
        # ``fval < 0`` guard (because ``inf < 0`` is False) and later
        # crashed ``int(NaN)`` inside ``_split_int`` with a bare
        # ``ValueError``, bypassing the ``AttributionError`` contract.
        with self.assertRaises(AttributionError):
            attribute_cost_by_duration(
                UsageMetrics(input_tokens=100, total_cost_usd=1.0),
                {"a": float("inf"), "b": 1.0},
            )

    def test_by_duration_nan_weight_raises_attribution_error(self) -> None:
        # Regression: ``NaN`` is also non-finite and slipped past the
        # ``fval < 0`` guard (``NaN < 0`` is False) before the fix.
        with self.assertRaises(AttributionError):
            attribute_cost_by_duration(
                UsageMetrics(input_tokens=100, total_cost_usd=1.0),
                {"a": float("nan"), "b": 1.0},
            )

    def test_by_duration_overflow_sum_degrades_to_uniform(self) -> None:
        # Regression: two finite-but-huge weights can overflow to
        # ``inf`` on summation, which would then turn the share ratios
        # into ``NaN``. The hardened helpers detect a non-finite
        # ``total_w`` and fall back to uniform attribution so the
        # sum-of-shares-equals-total invariant still holds.
        huge = sys.float_info.max
        session = UsageMetrics(input_tokens=100, total_cost_usd=1.0)
        shares = attribute_cost_by_duration(session, {"a": huge, "b": huge})
        self.assertEqual(sum(s.input_tokens for s in shares), 100)
        self.assertAlmostEqual(sum(s.cost_usd for s in shares), 1.0)


class ToolCallWeightedAttributionTests(unittest.TestCase):
    def test_by_tool_calls_weighted_correctly(self) -> None:
        tool_calls = {"lint": 1, "static": 4, "compliance": 5}
        shares = attribute_cost_by_tool_calls(SESSION, tool_calls)
        cost_by_id = {s.collector_id: s.cost_usd for s in shares}
        self.assertAlmostEqual(cost_by_id["lint"] / SESSION.total_cost_usd, 0.1)
        self.assertAlmostEqual(cost_by_id["static"] / SESSION.total_cost_usd, 0.4)
        self.assertAlmostEqual(
            sum(s.cost_usd for s in shares),
            SESSION.total_cost_usd,
        )

    def test_by_tool_calls_zero_total_handles_safely(self) -> None:
        shares = attribute_cost_by_tool_calls(SESSION, {"a": 0, "b": 0})
        self.assertAlmostEqual(
            sum(s.cost_usd for s in shares),
            SESSION.total_cost_usd,
        )
        for share in shares:
            self.assertEqual(share.attribution_mode, "tool-call-weighted")

    def test_by_tool_calls_rejects_non_int(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_by_tool_calls(SESSION, {"a": 1.5, "b": 2})  # type: ignore[dict-item]
        with self.assertRaises(AttributionError):
            attribute_cost_by_tool_calls(SESSION, {"a": True, "b": 2})  # type: ignore[dict-item]

    def test_by_tool_calls_negative_raises(self) -> None:
        with self.assertRaises(AttributionError):
            attribute_cost_by_tool_calls(SESSION, {"a": -1, "b": 2})


class FrozenAndSumInvariantTests(unittest.TestCase):
    def test_cost_share_frozen(self) -> None:
        share = CollectorCostShare(
            collector_id="x",
            input_tokens=1,
            output_tokens=2,
            cost_usd=0.01,
            duration_s=1.0,
            attribution_mode="uniform",
        )
        with self.assertRaises(FrozenInstanceError):
            share.cost_usd = 99.9  # type: ignore[misc]

    def test_attribution_mode_set_on_each_share(self) -> None:
        # The three public helpers always tag their output with one of
        # the recommended vocabulary entries (see
        # ``VALID_ATTRIBUTION_MODES``). Downstream persistence layers
        # may legitimately carry a different vocabulary, but the
        # in-module producers stick to the recommended set.
        modes_seen = set()
        modes_seen.update(
            s.attribution_mode
            for s in attribute_cost_uniform(SESSION, ["a", "b"])
        )
        modes_seen.update(
            s.attribution_mode
            for s in attribute_cost_by_duration(SESSION, {"a": 1.0, "b": 2.0})
        )
        modes_seen.update(
            s.attribution_mode
            for s in attribute_cost_by_tool_calls(SESSION, {"a": 1, "b": 2})
        )
        self.assertEqual(modes_seen, set(VALID_ATTRIBUTION_MODES))

    def test_attribution_mode_is_free_form_string(self) -> None:
        # Regression for round-2 bug sweep finding: the docstring on
        # ``VALID_ATTRIBUTION_MODES`` used to claim it was the "closed
        # vocabulary" for ``CollectorCostShare.attribution_mode``, but
        # the frozen dataclass does NOT enforce membership. This is by
        # design — :mod:`cost_evidence` legitimately constructs shares
        # with its own controlled vocabulary (``"duration"`` /
        # ``"tool-calls"``) via its ``_share_from_json`` loader, and
        # adding strict ``__post_init__`` enforcement here would break
        # that layer. This test pins the documented "free-form ``str``
        # by design" contract so a future refactor that adds naive
        # ``assert mode in VALID_ATTRIBUTION_MODES`` validation fails
        # loudly here before it breaks the persistence layer.
        share = CollectorCostShare(
            collector_id="x",
            input_tokens=1,
            output_tokens=2,
            cost_usd=0.01,
            duration_s=1.0,
            attribution_mode="hammer-time",  # not in VALID_ATTRIBUTION_MODES
        )
        self.assertEqual(share.attribution_mode, "hammer-time")
        self.assertNotIn(share.attribution_mode, VALID_ATTRIBUTION_MODES)
        # The cost_evidence vocab ("duration" / "tool-calls") must also
        # round-trip through the constructor unchanged — that's the
        # whole reason the dataclass field is intentionally permissive.
        for cost_evidence_mode in ("duration", "tool-calls"):
            s = CollectorCostShare(
                collector_id="y",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                duration_s=0.0,
                attribution_mode=cost_evidence_mode,
            )
            self.assertEqual(s.attribution_mode, cost_evidence_mode)

    def test_attribute_preserves_sum(self) -> None:
        session = UsageMetrics(
            input_tokens=999,
            output_tokens=1001,
            total_cost_usd=0.5,
            duration_s=33.3,
        )
        ids = ["alpha", "beta", "gamma", "delta"]

        uniform = attribute_cost_uniform(session, ids)
        self.assertEqual(sum(s.input_tokens for s in uniform), 999)
        self.assertEqual(sum(s.output_tokens for s in uniform), 1001)
        self.assertAlmostEqual(sum(s.cost_usd for s in uniform), 0.5)
        self.assertAlmostEqual(sum(s.duration_s for s in uniform), 33.3)

        durations = {cid: float(i + 1) for i, cid in enumerate(ids)}
        weighted = attribute_cost_by_duration(session, durations)
        self.assertEqual(sum(s.input_tokens for s in weighted), 999)
        self.assertEqual(sum(s.output_tokens for s in weighted), 1001)
        self.assertAlmostEqual(sum(s.cost_usd for s in weighted), 0.5)


if __name__ == "__main__":
    unittest.main()
