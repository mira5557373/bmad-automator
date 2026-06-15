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
    """Build a ceiling dict; ``warn_at=None`` omits the key."""
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
# fmt: off
_COMPLETED_BASE = StoryCompleted(
    timestamp=_DEFAULT_TS, run_id="r1", epic="E1", story_key="S1",
    duration_s=1.0, cost_usd=0.0, tokens_in=0, tokens_out=0, attempts=1,
)
# fmt: on


def _completed(cost, ts=_DEFAULT_TS):
    return dataclasses.replace(_COMPLETED_BASE, cost_usd=cost, timestamp=ts)


# fmt: off
def _ceiling(name="c1", window="per_run", limit_usd=10.0, warn_at=0.5, gates=("init",)):
    return BudgetCeiling(name=name, window=window, limit_usd=limit_usd, warn_at=warn_at, gate_names=gates)


def _eval_events(events, ceilings, *, gate="init", now=_DEFAULT_TS, eol="\n", trailing_blanks=0):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_ledger(tmp, events, eol=eol, trailing_blanks=trailing_blanks)
        return evaluate_ceilings(path, gate, now, ceilings=ceilings)
# fmt: on


class ModuleAndSurfaceTests(unittest.TestCase):
    """Imports, surface callables, __all__ exports, _PARSE_WARNINGS state."""

    def test_module_and_callables_exposed(self) -> None:
        self.assertTrue(hasattr(budget_ceilings, "parse_ceilings_config"))
        self.assertTrue(callable(evaluate_ceilings))
        self.assertTrue(callable(bypass_allowed))
        for name in ("evaluate_ceilings", "bypass_allowed"):
            self.assertIn(name, budget_ceilings.__all__)

    def test_warnings_list_exposed_and_cleared(self) -> None:
        self.assertIsInstance(budget_ceilings._PARSE_WARNINGS, list)
        _run_ceilings([_c(name="ok")])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_ceiling_decision_enum_shape(self) -> None:
        self.assertTrue(issubclass(CeilingDecision, enum.Enum))
        names = [m.name for m in CeilingDecision]
        self.assertEqual(names, ["ALLOW", "WARN", "BLOCK"])
        for n in names:
            self.assertEqual(CeilingDecision[n].value, n)


class BudgetCeilingShapeTests(unittest.TestCase):
    def test_kw_only_with_correct_field_names(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(BudgetCeiling))
        with self.assertRaises(TypeError):
            BudgetCeiling("c1", "per_run", 10.0, 0.8, ("init",))  # type: ignore[misc]
        # fmt: off
        self.assertEqual(
            [f.name for f in dataclasses.fields(BudgetCeiling)],
            ["name", "window", "limit_usd", "warn_at", "gate_names"],
        )
        c = BudgetCeiling(name="per_run_cap", window="per_run", limit_usd=25.0, warn_at=0.8, gate_names=("init", "story_start"))
        self.assertEqual(
            (c.name, c.window, c.limit_usd, c.warn_at, c.gate_names),
            ("per_run_cap", "per_run", 25.0, 0.8, ("init", "story_start")),
        )
        # fmt: on


class ParseCeilingsConfigMissingFileTests(unittest.TestCase):
    def test_missing_file_returns_empty_list_and_clears_warnings(self) -> None:
        budget_ceilings._PARSE_WARNINGS.append({"x": "stale"})
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            self.assertEqual(parse_ceilings_config(missing), [])
            self.assertEqual(parse_ceilings_config(str(missing)), [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class ParseCeilingsConfigMissingKeysTests(unittest.TestCase):
    def test_payload_shapes_return_empty_list(self) -> None:
        # fmt: off
        payloads = [
            {}, {"other": {"foo": "bar"}}, {"policy": {"unrelated": 1}},
            {"policy": {"cost_ceilings": {"x": 1}}}, [1, 2, 3],
        ]
        # fmt: on
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(_run_payload(payload), [])
        self.assertEqual(_run_raw("not json {"), [])


class ParseCeilingsConfigMalformedEntryTests(unittest.TestCase):
    def test_per_field_validation(self) -> None:
        # fmt: off
        cases = [
            ("limit_usd", -1.0, "bad_limit_usd_value"), ("limit_usd", 0.0, "bad_limit_usd_value"),
            ("limit_usd", True, "bad_limit_usd_type"), ("limit_usd", "10.0", "bad_limit_usd_type"),
            ("warn_at", True, "bad_warn_at_type"), ("warn_at", "0.5", "bad_warn_at_type"),
            ("warn_at", 0.0, "bad_warn_at_value"), ("warn_at", -0.1, "bad_warn_at_value"),
            ("warn_at", 1.5, "bad_warn_at_value"),
            ("name", 42, "bad_name"), ("name", "", "bad_name"),
            ("window", 42, "bad_window"), ("window", "1h", "bad_window"),
        ]
        # fmt: on
        for kwarg, val, reason in cases:
            with self.subTest(kwarg=kwarg, val=val):
                self.assertEqual(_run_ceilings([_c(**{kwarg: val})]), [])
                self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], reason)

    def test_missing_required_key_is_skipped(self) -> None:
        result = _run_ceilings([_c(name="bad", warn_at=None), _c(name="good")])
        self.assertEqual([c.name for c in result], ["good"])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "missing_keys")
        self.assertIn("warn_at", budget_ceilings._PARSE_WARNINGS[0]["detail"])

    def test_boundary_warn_at_one_is_allowed(self) -> None:
        result = _run_ceilings([_c(name="ok", warn_at=1.0)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].warn_at, 1.0)

    def test_non_object_entry_is_skipped(self) -> None:
        self.assertEqual(_run_ceilings(["not an object", 42, None]), [])
        reasons = [w["reason"] for w in budget_ceilings._PARSE_WARNINGS]
        self.assertEqual(reasons, ["not_object"] * 3)

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
        result = _run_ceilings([_c(name="ceiling-ünïcödé")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "ceiling-ünïcödé")

    def test_non_finite_limit_usd_is_skipped(self) -> None:
        """NaN/Infinity slip past ``<= 0``; math.isfinite catches them."""
        # fmt: off
        prefix = '{"policy":{"cost_ceilings":[{"name":"x","window":"per_run","limit_usd":'
        suffix = ',"warn_at":0.5,"gate_names":["init"]}]}}'
        for raw in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(limit_usd=raw):
                self.assertEqual(_run_raw(prefix + raw + suffix), [])
                self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_value")
        # fmt: on

    def test_non_utf8_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_bytes(b"\xff\xfe\xfd not utf-8")
            self.assertEqual(parse_ceilings_config(path), [])


class ParseCeilingsConfigHappyPathTests(unittest.TestCase):
    def test_single_well_formed_ceiling_parses(self) -> None:
        # fmt: off
        entry = _c(name="per_run_cap", limit_usd=25.0, warn_at=0.8, gate_names=["init", "story_start"])
        result = _run_ceilings([entry])
        self.assertEqual(len(result), 1)
        c = result[0]
        self.assertIsInstance(c, BudgetCeiling)
        self.assertIsInstance(c.gate_names, tuple)
        self.assertEqual(
            (c.name, c.window, c.limit_usd, c.warn_at, c.gate_names),
            ("per_run_cap", "per_run", 25.0, 0.8, ("init", "story_start")),
        )
        # fmt: on

    def test_multiple_ceilings_preserve_file_order(self) -> None:
        # fmt: off
        result = _run_ceilings([
            _c(name="first", limit_usd=5.0),
            _c(name="second", window="24h", limit_usd=10.0, warn_at=0.6),
            _c(name="third", window="7d", limit_usd=50.0, warn_at=0.9),
        ])
        # fmt: on
        self.assertEqual([c.name for c in result], ["first", "second", "third"])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_empty_cost_ceilings_list_returns_empty_list(self) -> None:
        self.assertEqual(_run_ceilings([]), [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class SpecReq01PreludeTests(unittest.TestCase):
    """REQ-01: future annotations required at top of source and test files."""

    def test_files_have_future_annotations(self) -> None:
        # fmt: off
        def has_future_import(src: str) -> bool:
            body = ast.parse(src).body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0].value, "value", None), str):
                body = body[1:]
            head = body[0] if body else None
            return (isinstance(head, ast.ImportFrom) and head.module == "__future__"
                    and any(a.name == "annotations" for a in head.names))
        src_path = Path(__file__).resolve().parents[1] / "skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py"
        # fmt: on
        for p in [src_path, Path(__file__).resolve()]:
            with self.subTest(path=p.name):
                self.assertTrue(has_future_import(p.read_text(encoding="utf-8")))


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


class EvaluateCeilingsNoConfigTests(unittest.TestCase):
    def test_no_config_returns_sentinel(self) -> None:
        sentinel = (CeilingDecision.ALLOW, "no_ceilings_configured")
        ev = evaluate_ceilings
        # Both-None, empty list, and missing-path-with-no-config all sentinel.
        self.assertEqual(ev("events.jsonl", "init", _DEFAULT_TS), sentinel)
        self.assertEqual(ev("events.jsonl", "init", _DEFAULT_TS, ceilings=[]), sentinel)
        self.assertEqual(ev("/nonexistent/events.jsonl", "init", _DEFAULT_TS), sentinel)


class EvaluateCeilingsEmptyLedgerTests(unittest.TestCase):
    def test_missing_or_empty_ledger_returns_allow(self) -> None:
        expected = (CeilingDecision.ALLOW, "c1:per_run:spent=0.0000:limit=10.0000")
        # fmt: off
        # Missing file: pass a path that does not exist.
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "events.jsonl"
            out = evaluate_ceilings(missing, "init", _DEFAULT_TS, ceilings=[_ceiling(warn_at=0.8)])
        # fmt: on
        self.assertEqual(out, expected)
        # Empty file: written via _write_ledger with no events.
        self.assertEqual(_eval_events([], [_ceiling(warn_at=0.8)]), expected)


class EvaluateCeilingsDecisionRuleTests(unittest.TestCase):
    def test_allow_warn_block_boundaries(self) -> None:
        # ceiling: limit_usd=10.0, warn_at=0.8 -> WARN at 8.0, BLOCK at 10.0.
        for costs, expected_verdict, spent in [
            ([1.0], CeilingDecision.ALLOW, "1.0000"),
            ([8.0], CeilingDecision.WARN, "8.0000"),
            ([5.0, 4.0], CeilingDecision.WARN, "9.0000"),
            ([10.0], CeilingDecision.BLOCK, "10.0000"),
            ([12.5], CeilingDecision.BLOCK, "12.5000"),
        ]:
            with self.subTest(costs=costs):
                events = [_completed(c) for c in costs]
                verdict, reason = _eval_events(events, [_ceiling(warn_at=0.8)])
                self.assertEqual(verdict, expected_verdict)
                self.assertEqual(reason, f"c1:per_run:spent={spent}:limit=10.0000")


class EvaluateCeilingsWindowTests(unittest.TestCase):
    def test_window_filters(self) -> None:
        # (window, pairs, expected_spent_str, now). Symmetric "within N seconds".
        D = _DEFAULT_TS
        # fmt: off
        cases = [
            ("per_run", [(3.0, "1996-01-01T00:00:00Z"), (4.0, D)], "7.0000", D),
            ("24h", [(5.0, "2026-06-13T23:59:59Z"), (7.0, "2026-06-14T01:00:00Z")], "7.0000", D),
            ("7d", [(5.0, "2026-06-07T23:59:59Z"), (9.0, "2026-06-10T00:00:00Z")], "9.0000", D),
            ("30d", [(5.0, "2026-05-15T23:59:59Z"), (11.0, "2026-05-20T00:00:00Z")], "11.0000", D),
            ("24h", [(99.0, "not-a-timestamp"), (3.0, "2026-06-14T12:00:00Z")], "3.0000", D),
            ("24h", [(50.0, "2026-12-31T00:00:00Z"), (3.0, "2026-06-14T12:00:00Z")], "3.0000", D),
            ("24h", [(50.0, "2026-06-14T12:00:00Z")], "0.0000", "not-a-timestamp"),
        ]
        # fmt: on
        for window, pairs, expected, now in cases:
            with self.subTest(window=window, now=now):
                events = [_completed(c, ts=t) for c, t in pairs]
                _, reason = _eval_events(
                    events, [_ceiling(window=window, limit_usd=100.0)], now=now
                )
                self.assertIn(f"spent={expected}", reason)


class EvaluateCeilingsGateFilterTests(unittest.TestCase):
    def test_gate_filtering(self) -> None:
        # fmt: off
        # Non-matching gate falls through to sentinel.
        ceiling = _ceiling(name="only_story_start", limit_usd=1.0, gates=("story_start",))
        verdict, reason = _eval_events([_completed(99.0)], [ceiling])
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")
        # Matching gate applies; verify across all REQ-07 gate names.
        ceiling = _ceiling(name="any_gate", warn_at=0.8, gates=("init", "story_start", "retry_start"))
        # fmt: on
        for gate in ("init", "story_start", "retry_start"):
            with self.subTest(gate=gate):
                verdict, reason = _eval_events([_completed(11.0)], [ceiling], gate=gate)
                self.assertEqual(verdict, CeilingDecision.BLOCK)
                self.assertIn("any_gate", reason)


class EvaluateCeilingsMultiCeilingTests(unittest.TestCase):
    def test_severity_merge_and_tiebreak(self) -> None:
        def cs(*specs):
            return [_ceiling(name=n, limit_usd=L, warn_at=w) for n, L, w in specs]

        # (ceilings, cost, expected_verdict, expected_reason_prefix).
        # fmt: off
        cases = [
            (cs(("cap_a", 2.0, 0.5), ("cap_b", 1.0, 0.5)), 1.5, CeilingDecision.BLOCK, "cap_b"),
            (cs(("cap_a", 100.0, 0.5), ("cap_b", 10.0, 0.5)), 6.0, CeilingDecision.WARN, "cap_b"),
            (cs(("first", 1.0, 0.5), ("second", 1.0, 0.5)), 2.0, CeilingDecision.BLOCK, "first"),
            (cs(("alpha", 100.0, 0.9), ("beta", 200.0, 0.9)), 1.0, CeilingDecision.ALLOW, "alpha"),
        ]
        # fmt: on
        for ceilings, cost, expected_verdict, prefix in cases:
            with self.subTest(prefix=prefix):
                verdict, reason = _eval_events([_completed(cost)], ceilings)
                self.assertEqual(verdict, expected_verdict)
                self.assertTrue(reason.startswith(prefix + ":"), reason)


class EvaluateCeilingsLineEndingTests(unittest.TestCase):
    def test_crlf_and_trailing_blanks_are_tolerated(self) -> None:
        # fmt: off
        cap = [_ceiling(limit_usd=100.0)]
        _, r = _eval_events([_completed(2.0), _completed(3.0)], cap, eol="\r\n")
        self.assertIn("spent=5.0000", r)
        _, r = _eval_events([_completed(7.0)], cap, trailing_blanks=5)
        self.assertIn("spent=7.0000", r)
        # fmt: on

    def test_malformed_lines_are_skipped(self) -> None:
        # fmt: off
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            valid = compact_json(_completed(4.0).to_dict())
            path.write_text("not json\n{}\n[1,2,3]\n" + valid + "\n", encoding="utf-8")
            _, reason = evaluate_ceilings(path, "init", _DEFAULT_TS, ceilings=[_ceiling(limit_usd=100.0)])
        # fmt: on
        self.assertIn("spent=4.0000", reason)

    def test_event_without_cost_usd_attribute_contributes_zero(self) -> None:
        """``StoryStarted`` has no ``cost_usd``; must not blow up or count."""
        from story_automator.core.telemetry_events import StoryStarted

        # fmt: off
        started = StoryStarted(
            timestamp=_DEFAULT_TS, run_id="r1", epic="E1", story_key="S1",
            agent="dev", model="m", complexity="L",
        )
        _, reason = _eval_events([started, _completed(3.0)], [_ceiling(limit_usd=100.0)])
        # fmt: on
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

    def test_truth_table_and_non_exact_env_values(self) -> None:
        # Only env=="1" AND isatty -> True; anything else -> False.
        # fmt: off
        cases = [
            (None, False, False), (None, True, False),
            ("1", False, False), ("1", True, True),
            ("0", True, False), ("true", True, False), ("yes", True, False),
            ("TRUE", True, False), ("01", True, False),
        ]
        # fmt: on
        for env, tty, expected in cases:
            with self.subTest(env=env, tty=tty):
                self.assertEqual(self._run(env, tty), expected)


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
        body = compact_json({"policy": {"cost_ceilings": ceilings_list}})
        path.write_text(body, encoding="utf-8")
        return path

    def test_workflow_json_path_round_trip(self) -> None:
        # fmt: off
        # Loaded ceiling triggers BLOCK on the ledger.
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self._write_workflow(tmp, [_c(name="from_disk", limit_usd=5.0)])
            ledger = _write_ledger(tmp, [_completed(6.0)])
            verdict, reason = evaluate_ceilings(ledger, "init", _DEFAULT_TS, workflow_json_path=workflow)
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertTrue(reason.startswith("from_disk:"))
        # Empty ceilings list on disk yields the no-config sentinel.
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self._write_workflow(tmp, [])
            verdict, reason = evaluate_ceilings("irrelevant.jsonl", "init", _DEFAULT_TS, workflow_json_path=workflow)
        # fmt: on
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")


if __name__ == "__main__":
    unittest.main()
