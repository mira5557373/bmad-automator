from __future__ import annotations

import ast
import dataclasses
import enum
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from story_automator.core import budget_ceilings
from story_automator.core.budget_ceilings import (
    BudgetCeiling,
    CeilingDecision,
    bypass_allowed,
    evaluate_ceilings,
    parse_ceilings_config,
)
from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import StoryCompleted, parse_event


def _c(name="bad", window="per_run", limit_usd=10.0, warn_at=0.5, gate_names=None):
    """Build a ceiling dict with sane defaults. ``warn_at=None`` omits the key."""
    d = {
        "name": name,
        "window": window,
        "limit_usd": limit_usd,
        "gate_names": ["init"] if gate_names is None else gate_names,
    }
    if warn_at is not None:
        d["warn_at"] = warn_at
    return d


def _run_raw(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.json"
        path.write_text(text, encoding="utf-8")
        return parse_ceilings_config(path)


def _run_payload(payload):
    return _run_raw(compact_json(payload))


def _run_ceilings(ceilings):
    return _run_payload({"policy": {"cost_ceilings": ceilings}})


def _write_ledger(tmp, events, *, eol="\n", trailing_blanks=0):
    """Write M01 ``events`` (REQ-15 compact_json) with chosen line ending."""
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = eol.join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += eol
    body += eol * trailing_blanks
    path.write_text(body, encoding="utf-8")
    return path


_DEFAULT_TS = "2026-06-15T00:00:00Z"
_COMPLETED_BASE = StoryCompleted(
    timestamp=_DEFAULT_TS,
    run_id="r1",
    epic="E1",
    story_key="S1",
    duration_s=1.0,
    cost_usd=0.0,
    tokens_in=0,
    tokens_out=0,
    attempts=1,
)


def _completed(cost, ts=_DEFAULT_TS):
    return dataclasses.replace(_COMPLETED_BASE, cost_usd=cost, timestamp=ts)


def _ceiling(name="c1", window="per_run", limit_usd=10.0, warn_at=0.5, gates=("init",)):
    return BudgetCeiling(
        name=name,
        window=window,
        limit_usd=limit_usd,
        warn_at=warn_at,
        gate_names=gates,
    )


def _eval_events(
    events, ceilings, *, gate="init", now=_DEFAULT_TS, eol="\n", trailing_blanks=0
):
    """Write ``events`` to a temp ledger and evaluate ``ceilings`` against it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_ledger(tmp, events, eol=eol, trailing_blanks=trailing_blanks)
        return evaluate_ceilings(path, gate, now, ceilings=ceilings)


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        self.assertTrue(hasattr(budget_ceilings, "parse_ceilings_config"))


class CeilingDecisionTests(unittest.TestCase):
    def test_has_exactly_three_members(self) -> None:
        self.assertEqual(len(list(CeilingDecision)), 3)

    def test_member_names_and_order(self) -> None:
        names = [m.name for m in CeilingDecision]
        self.assertEqual(names, ["ALLOW", "WARN", "BLOCK"])

    def test_member_values_match_names(self) -> None:
        for name in ["ALLOW", "WARN", "BLOCK"]:
            self.assertEqual(CeilingDecision[name].value, name)

    def test_is_enum_subclass(self) -> None:
        self.assertTrue(issubclass(CeilingDecision, enum.Enum))


class BudgetCeilingShapeTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(BudgetCeiling))
        with self.assertRaises(TypeError):
            BudgetCeiling("c1", "per_run", 10.0, 0.8, ("init",))  # type: ignore[misc]

    def test_field_names_exact(self) -> None:
        names = [f.name for f in dataclasses.fields(BudgetCeiling)]
        self.assertEqual(
            names, ["name", "window", "limit_usd", "warn_at", "gate_names"]
        )

    def test_can_construct_with_keywords(self) -> None:
        c = BudgetCeiling(
            name="per_run_cap",
            window="per_run",
            limit_usd=25.0,
            warn_at=0.8,
            gate_names=("init", "story_start"),
        )
        self.assertEqual(
            (c.name, c.window, c.limit_usd, c.warn_at, c.gate_names),
            ("per_run_cap", "per_run", 25.0, 0.8, ("init", "story_start")),
        )


class ParseWarningsModuleStateTests(unittest.TestCase):
    def test_module_exposes_parse_warnings_list(self) -> None:
        self.assertTrue(hasattr(budget_ceilings, "_PARSE_WARNINGS"))
        self.assertIsInstance(budget_ceilings._PARSE_WARNINGS, list)

    def test_parse_warnings_is_empty_after_clean_call(self) -> None:
        _run_ceilings([_c(name="ok")])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class ParseCeilingsConfigMissingFileTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(parse_ceilings_config(Path(tmp) / "nope.json"), [])

    def test_missing_file_accepts_str_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(parse_ceilings_config(str(Path(tmp) / "nope.json")), [])

    def test_missing_file_clears_parse_warnings(self) -> None:
        budget_ceilings._PARSE_WARNINGS.append(
            {"index": "0", "reason": "stale", "detail": "stale"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            parse_ceilings_config(Path(tmp) / "missing.json")
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class ParseCeilingsConfigMissingKeysTests(unittest.TestCase):
    def test_empty_object_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload({}), [])

    def test_no_policy_key_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload({"other": {"foo": "bar"}}), [])

    def test_no_cost_ceilings_key_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload({"policy": {"unrelated": 1}}), [])

    def test_cost_ceilings_not_a_list_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload({"policy": {"cost_ceilings": {"x": 1}}}), [])

    def test_top_level_not_object_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload([1, 2, 3]), [])

    def test_invalid_json_returns_empty_list(self) -> None:
        self.assertEqual(_run_raw("not json {"), [])


class ParseCeilingsConfigMalformedEntryTests(unittest.TestCase):
    def _assert_skipped(self, kwarg, val, reason):
        """Build a ceiling with kwarg=val and assert it's skipped with ``reason``."""
        result = _run_ceilings([_c(**{kwarg: val})])
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], reason)

    def test_missing_required_key_is_skipped(self) -> None:
        result = _run_ceilings([_c(name="bad", warn_at=None), _c(name="good")])
        self.assertEqual([c.name for c in result], ["good"])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "missing_keys")
        self.assertIn("warn_at", budget_ceilings._PARSE_WARNINGS[0]["detail"])

    def test_bad_limit_usd_value(self) -> None:
        """Negative and zero limits are rejected."""
        for limit_val in [-1.0, 0.0]:
            with self.subTest(limit_usd=limit_val):
                self._assert_skipped("limit_usd", limit_val, "bad_limit_usd_value")

    def test_bad_limit_usd_type(self) -> None:
        """bool and str types rejected; True is int in Python."""
        for val in [True, "10.0"]:
            with self.subTest(limit_usd=val):
                self._assert_skipped("limit_usd", val, "bad_limit_usd_type")

    def test_bad_warn_at_type(self) -> None:
        """bool and str types rejected."""
        for val in [True, "0.5"]:
            with self.subTest(warn_at=val):
                self._assert_skipped("warn_at", val, "bad_warn_at_type")

    def test_bad_name(self) -> None:
        """Non-string and empty string names are rejected."""
        for val in [42, ""]:
            with self.subTest(name=val):
                self._assert_skipped("name", val, "bad_name")

    def test_bad_window(self) -> None:
        """Non-string and invalid window strings are rejected."""
        for val in [42, "1h"]:
            with self.subTest(window=val):
                self._assert_skipped("window", val, "bad_window")

    def test_warn_at_out_of_range_is_skipped(self) -> None:
        for warn_at in [0.0, -0.1, 1.5]:
            with self.subTest(warn_at=warn_at):
                result = _run_ceilings([_c(warn_at=warn_at)])
                self.assertEqual(result, [])
                reason = budget_ceilings._PARSE_WARNINGS[0]["reason"]
                self.assertTrue(reason.startswith("bad_warn_at"))

    def test_boundary_warn_at_one_is_allowed(self) -> None:
        result = _run_ceilings([_c(name="ok", warn_at=1.0)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].warn_at, 1.0)

    def test_non_object_entry_is_skipped(self) -> None:
        result = _run_ceilings(["not an object", 42, None])
        self.assertEqual(result, [])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 3)
        for warning in budget_ceilings._PARSE_WARNINGS:
            self.assertEqual(warning["reason"], "not_object")

    def test_gate_names_must_be_list_of_strings(self) -> None:
        result = _run_ceilings(
            [_c(gate_names="init"), _c(name="bad2", gate_names=[1, 2])]
        )
        self.assertEqual(result, [])
        reasons = [w["reason"] for w in budget_ceilings._PARSE_WARNINGS]
        self.assertEqual(reasons, ["bad_gate_names", "bad_gate_names"])

    def test_warnings_cleared_on_each_call(self) -> None:
        _run_ceilings([_c(window="nope")])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)
        _run_ceilings([_c(name="ok")])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_utf8_non_ascii_name_round_trips(self) -> None:
        """REQ-04 says UTF-8 reading; confirm non-ASCII names survive."""
        result = _run_ceilings([_c(name="ceiling-ünïcödé")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "ceiling-ünïcödé")

    def test_non_finite_limit_usd_is_skipped(self) -> None:
        """NaN/Infinity slip past the ``<= 0`` check; math.isfinite catches them."""
        prefix = (
            '{"policy":{"cost_ceilings":[{"name":"x","window":"per_run","limit_usd":'
        )
        suffix = ',"warn_at":0.5,"gate_names":["init"]}]}}'
        for raw in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(limit_usd=raw):
                result = _run_raw(prefix + raw + suffix)
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_value"
                )

    def test_non_utf8_file_returns_empty_list(self) -> None:
        """Tolerant-by-design: invalid UTF-8 bytes return [] instead of crashing."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_bytes(b"\xff\xfe\xfd not utf-8")
            self.assertEqual(parse_ceilings_config(path), [])


class ParseCeilingsConfigHappyPathTests(unittest.TestCase):
    def test_single_well_formed_ceiling_parses(self) -> None:
        entry = _c(
            name="per_run_cap",
            limit_usd=25.0,
            warn_at=0.8,
            gate_names=["init", "story_start"],
        )
        result = _run_ceilings([entry])
        self.assertEqual(len(result), 1)
        c = result[0]
        self.assertIsInstance(c, BudgetCeiling)
        self.assertEqual(
            (c.name, c.window, c.limit_usd, c.warn_at, c.gate_names),
            ("per_run_cap", "per_run", 25.0, 0.8, ("init", "story_start")),
        )

    def test_gate_names_become_tuple_not_list(self) -> None:
        result = _run_ceilings([_c(name="c1", window="24h")])
        self.assertIsInstance(result[0].gate_names, tuple)

    def test_multiple_ceilings_preserve_file_order(self) -> None:
        result = _run_ceilings(
            [
                _c(name="first", limit_usd=5.0),
                _c(name="second", window="24h", limit_usd=10.0, warn_at=0.6),
                _c(name="third", window="7d", limit_usd=50.0, warn_at=0.9),
            ]
        )
        self.assertEqual([c.name for c in result], ["first", "second", "third"])

    def test_happy_path_leaves_parse_warnings_empty(self) -> None:
        _run_ceilings([_c(name="c1", window="30d", limit_usd=100.0, warn_at=0.75)])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_empty_cost_ceilings_list_returns_empty_list(self) -> None:
        self.assertEqual(_run_ceilings([]), [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class SpecReq01PreludeTests(unittest.TestCase):
    """REQ-01: future annotations required."""

    def _has_future_import(self, src: str) -> bool:
        body = ast.parse(src).body
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body = body[1:]
        head = body[0] if body else None
        return (
            isinstance(head, ast.ImportFrom)
            and head.module == "__future__"
            and any(a.name == "annotations" for a in head.names)
        )

    def test_source_file_has_future_annotations(self) -> None:
        src_path = (
            Path(__file__).resolve().parents[1]
            / "skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py"
        )
        self.assertTrue(self._has_future_import(src_path.read_text(encoding="utf-8")))

    def test_test_file_has_future_annotations(self) -> None:
        test_path = Path(__file__).resolve()
        self.assertTrue(self._has_future_import(test_path.read_text(encoding="utf-8")))


class LedgerFixturePatternTests(unittest.TestCase):
    """REQ-15: compact_json serialization round-trips via parse_event."""

    def test_event_fixture_round_trips_via_compact_json(self) -> None:
        event = _completed(0.25)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "events.jsonl"
            ledger.write_text(compact_json(event.to_dict()) + "\n", encoding="utf-8")
            parsed = parse_event(ledger.read_text(encoding="utf-8").rstrip("\n"))
        self.assertEqual(parsed.run_id, "r1")
        self.assertEqual(getattr(parsed, "cost_usd"), 0.25)


class EvaluatorSurfaceTests(unittest.TestCase):
    def test_evaluate_ceilings_is_importable(self) -> None:
        self.assertTrue(callable(evaluate_ceilings))

    def test_bypass_allowed_is_importable(self) -> None:
        self.assertTrue(callable(bypass_allowed))

    def test_exports_include_new_callables(self) -> None:
        self.assertIn("evaluate_ceilings", budget_ceilings.__all__)
        self.assertIn("bypass_allowed", budget_ceilings.__all__)


class EvaluateCeilingsNoConfigTests(unittest.TestCase):
    SENTINEL = (CeilingDecision.ALLOW, "no_ceilings_configured")

    def test_both_none_returns_allow_no_ceilings_sentinel(self) -> None:
        out = evaluate_ceilings("events.jsonl", "init", _DEFAULT_TS)
        self.assertEqual(out, self.SENTINEL)

    def test_empty_ceilings_list_returns_allow_no_ceilings_sentinel(self) -> None:
        out = evaluate_ceilings("events.jsonl", "init", _DEFAULT_TS, ceilings=[])
        self.assertEqual(out, self.SENTINEL)

    def test_no_config_path_does_not_touch_ledger(self) -> None:
        """Sentinel must short-circuit before any file I/O."""
        out = evaluate_ceilings(
            "/nonexistent/path/to/events.jsonl", "init", _DEFAULT_TS
        )
        self.assertEqual(out, self.SENTINEL)


class EvaluateCeilingsEmptyLedgerTests(unittest.TestCase):
    def test_missing_ledger_file_returns_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verdict, reason = evaluate_ceilings(
                Path(tmp) / "events.jsonl",
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[_ceiling(warn_at=0.8)],
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")

    def test_empty_ledger_file_returns_allow(self) -> None:
        verdict, reason = _eval_events([], [_ceiling(warn_at=0.8)])
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")


class EvaluateCeilingsDecisionRuleTests(unittest.TestCase):
    def _assert(self, costs, expected_verdict, expected_spent):
        events = [_completed(c) for c in costs]
        verdict, reason = _eval_events(events, [_ceiling(warn_at=0.8)])
        self.assertEqual(verdict, expected_verdict)
        self.assertEqual(reason, f"c1:per_run:spent={expected_spent}:limit=10.0000")

    def test_below_warn_threshold_returns_allow(self) -> None:
        self._assert([1.0], CeilingDecision.ALLOW, "1.0000")

    def test_at_warn_threshold_returns_warn(self) -> None:
        # 10.0 * 0.8 = 8.0 exactly
        self._assert([8.0], CeilingDecision.WARN, "8.0000")

    def test_between_warn_and_limit_returns_warn(self) -> None:
        self._assert([5.0, 4.0], CeilingDecision.WARN, "9.0000")

    def test_at_limit_returns_block(self) -> None:
        self._assert([10.0], CeilingDecision.BLOCK, "10.0000")

    def test_above_limit_returns_block(self) -> None:
        self._assert([12.5], CeilingDecision.BLOCK, "12.5000")


class EvaluateCeilingsWindowTests(unittest.TestCase):
    def _spent(self, pairs, window, expected, **kw):
        """``pairs``: iterable of (cost, ts). Run and assert spent=``expected``."""
        events = [_completed(c, ts=t) for c, t in pairs]
        ceilings = [_ceiling(window=window, limit_usd=100.0)]
        _, reason = _eval_events(events, ceilings, **kw)
        self.assertIn(f"spent={expected}", reason)

    def test_per_run_sums_all_events_regardless_of_timestamp(self) -> None:
        pairs = [(3.0, "1996-01-01T00:00:00Z"), (4.0, "2026-06-15T00:00:00Z")]
        self._spent(pairs, "per_run", "7.0000")

    def test_24h_excludes_events_older_than_86400_seconds(self) -> None:
        pairs = [(5.0, "2026-06-13T23:59:59Z"), (7.0, "2026-06-14T01:00:00Z")]
        self._spent(pairs, "24h", "7.0000")

    def test_7d_excludes_events_older_than_604800_seconds(self) -> None:
        pairs = [(5.0, "2026-06-07T23:59:59Z"), (9.0, "2026-06-10T00:00:00Z")]
        self._spent(pairs, "7d", "9.0000")

    def test_30d_excludes_events_older_than_2592000_seconds(self) -> None:
        pairs = [(5.0, "2026-05-15T23:59:59Z"), (11.0, "2026-05-20T00:00:00Z")]
        self._spent(pairs, "30d", "11.0000")

    def test_unparseable_event_timestamp_is_skipped_in_windowed_modes(self) -> None:
        pairs = [(99.0, "not-a-timestamp"), (3.0, "2026-06-14T12:00:00Z")]
        self._spent(pairs, "24h", "3.0000")

    def test_future_event_beyond_window_is_excluded(self) -> None:
        """REQ-08 'within N seconds' is symmetric."""
        pairs = [(50.0, "2026-12-31T00:00:00Z"), (3.0, "2026-06-14T12:00:00Z")]
        self._spent(pairs, "24h", "3.0000")

    def test_unparseable_now_iso_short_circuits_to_zero_in_windowed_modes(self) -> None:
        """A bad now_iso plus a windowed ceiling counts zero spend."""
        self._spent(
            [(50.0, "2026-06-14T12:00:00Z")], "24h", "0.0000", now="not-a-timestamp"
        )


class EvaluateCeilingsGateFilterTests(unittest.TestCase):
    def test_ceiling_not_listing_gate_is_ignored(self) -> None:
        ceiling = _ceiling(
            name="only_story_start", limit_usd=1.0, gates=("story_start",)
        )
        verdict, reason = _eval_events([_completed(99.0)], [ceiling])
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_ceiling_listing_gate_is_applied(self) -> None:
        ceiling = _ceiling(
            name="any_gate",
            warn_at=0.8,
            gates=("init", "story_start", "retry_start"),
        )
        for gate in ("init", "story_start", "retry_start"):
            with self.subTest(gate=gate):
                verdict, reason = _eval_events([_completed(11.0)], [ceiling], gate=gate)
                self.assertEqual(verdict, CeilingDecision.BLOCK)
                self.assertIn("any_gate", reason)


class EvaluateCeilingsMultiCeilingTests(unittest.TestCase):
    def _run(self, ceilings, cost):
        return _eval_events([_completed(cost)], ceilings)

    def test_block_outranks_warn(self) -> None:
        cs = [
            _ceiling(name="cap_a", limit_usd=2.0),
            _ceiling(name="cap_b", limit_usd=1.0),
        ]
        verdict, reason = self._run(cs, 1.5)
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertIn("cap_b", reason)

    def test_warn_outranks_allow(self) -> None:
        cs = [
            _ceiling(name="cap_a", limit_usd=100.0),
            _ceiling(name="cap_b", limit_usd=10.0),
        ]
        verdict, reason = self._run(cs, 6.0)
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertIn("cap_b", reason)

    def test_tie_break_uses_declaration_order(self) -> None:
        cs = [
            _ceiling(name="first", limit_usd=1.0),
            _ceiling(name="second", limit_usd=1.0),
        ]
        verdict, reason = self._run(cs, 2.0)
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertTrue(reason.startswith("first:"))

    def test_all_ceilings_below_warn_returns_allow_with_first_reason(self) -> None:
        cs = [
            _ceiling(name="alpha", limit_usd=100.0, warn_at=0.9),
            _ceiling(name="beta", limit_usd=200.0, warn_at=0.9),
        ]
        verdict, reason = self._run(cs, 1.0)
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertTrue(reason.startswith("alpha:"))


class EvaluateCeilingsLineEndingTests(unittest.TestCase):
    def test_crlf_line_endings_are_tolerated(self) -> None:
        evs = [_completed(2.0), _completed(3.0)]
        _, reason = _eval_events(evs, [_ceiling(limit_usd=100.0)], eol="\r\n")
        self.assertIn("spent=5.0000", reason)

    def test_trailing_blank_lines_are_tolerated(self) -> None:
        _, reason = _eval_events(
            [_completed(7.0)], [_ceiling(limit_usd=100.0)], trailing_blanks=5
        )
        self.assertIn("spent=7.0000", reason)

    def test_malformed_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            valid = compact_json(_completed(4.0).to_dict())
            path.write_text("not json\n{}\n[1,2,3]\n" + valid + "\n", encoding="utf-8")
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[_ceiling(limit_usd=100.0)],
            )
        self.assertIn("spent=4.0000", reason)

    def test_event_without_cost_usd_attribute_contributes_zero(self) -> None:
        """``StoryStarted`` has no ``cost_usd``; must not blow up or count."""
        from story_automator.core.telemetry_events import StoryStarted

        started = StoryStarted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            agent="dev",
            model="m",
            complexity="L",
        )
        _, reason = _eval_events(
            [started, _completed(3.0)], [_ceiling(limit_usd=100.0)]
        )
        self.assertIn("spent=3.0000", reason)


class BypassAllowedTests(unittest.TestCase):
    ENV = "BMAD_ALLOW_CEILING_BYPASS"

    def setUp(self) -> None:
        self._prior = os.environ.pop(self.ENV, None)

    def tearDown(self) -> None:
        os.environ.pop(self.ENV, None)
        if self._prior is not None:
            os.environ[self.ENV] = self._prior

    def _run(self, env_value, isatty_value):
        if env_value is None:
            os.environ.pop(self.ENV, None)
        else:
            os.environ[self.ENV] = env_value
        with mock.patch("sys.stdin.isatty", return_value=isatty_value):
            return bypass_allowed()

    def test_env_unset_and_no_tty_returns_false(self) -> None:
        self.assertFalse(self._run(None, False))

    def test_env_unset_with_tty_returns_false(self) -> None:
        self.assertFalse(self._run(None, True))

    def test_env_set_no_tty_returns_false(self) -> None:
        self.assertFalse(self._run("1", False))

    def test_env_set_with_tty_returns_true(self) -> None:
        self.assertTrue(self._run("1", True))

    def test_env_set_to_other_value_returns_false(self) -> None:
        for value in ["0", "true", "yes", "TRUE", "01"]:
            with self.subTest(env=value):
                self.assertFalse(self._run(value, True))


class EvaluateCeilingsDeterminismTests(unittest.TestCase):
    def test_one_hundred_calls_byte_identical(self) -> None:
        cs = [_ceiling(name=f"c{i}") for i in range(4)]
        outputs = {
            _eval_events([_completed(6.0), _completed(2.5)], cs) for _ in range(100)
        }
        self.assertEqual(len(outputs), 1)
        verdict, reason = outputs.pop()
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertTrue(reason.startswith("c0:"))


class EvaluateCeilingsConfigSourceTests(unittest.TestCase):
    def _write_workflow(self, tmp, ceilings_list):
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings_list}}), encoding="utf-8"
        )
        return path

    def test_workflow_json_path_is_read_through_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self._write_workflow(tmp, [_c(name="from_disk", limit_usd=5.0)])
            ledger = _write_ledger(tmp, [_completed(6.0)])
            verdict, reason = evaluate_ceilings(
                ledger, "init", "2026-06-15T00:00:00Z", workflow_json_path=workflow
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertTrue(reason.startswith("from_disk:"))

    def test_workflow_json_path_with_no_ceilings_returns_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self._write_workflow(tmp, [])
            verdict, reason = evaluate_ceilings(
                "irrelevant.jsonl",
                "init",
                "2026-06-15T00:00:00Z",
                workflow_json_path=workflow,
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")


if __name__ == "__main__":
    unittest.main()
