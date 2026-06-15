from __future__ import annotations

import ast
import dataclasses
import enum
import tempfile
import unittest
from pathlib import Path

from story_automator.core import budget_ceilings
from story_automator.core.budget_ceilings import (
    BudgetCeiling,
    CeilingDecision,
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


def _run_ceilings(ceilings):
    """Write ``ceilings`` into a temp workflow.json and run the parser."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings}}), encoding="utf-8"
        )
        return parse_ceilings_config(path)


def _run_payload(payload):
    """Write arbitrary JSON-serializable ``payload`` and run the parser."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.json"
        path.write_text(compact_json(payload), encoding="utf-8")
        return parse_ceilings_config(path)


def _run_raw(text):
    """Write raw ``text`` (may be invalid JSON) and run the parser."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workflow.json"
        path.write_text(text, encoding="utf-8")
        return parse_ceilings_config(path)


def _write_ledger(tmp, events, *, eol="\n", trailing_blanks=0):
    """Write M01 ``events`` to ``events.jsonl`` under ``tmp``.

    Each event is serialized through ``compact_json(event.to_dict())``
    per REQ-15. ``eol`` defaults to ``\\n`` but tests can pass ``\\r\\n``
    to exercise the NFR line-ending tolerance. ``trailing_blanks``
    appends N blank lines to the end of the file to exercise the same.
    """
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = eol.join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += eol
    body += eol * trailing_blanks
    path.write_text(body, encoding="utf-8")
    return path


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
        self.assertEqual(CeilingDecision.ALLOW.value, "ALLOW")
        self.assertEqual(CeilingDecision.WARN.value, "WARN")
        self.assertEqual(CeilingDecision.BLOCK.value, "BLOCK")

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
        ceiling = BudgetCeiling(
            name="per_run_cap",
            window="per_run",
            limit_usd=25.0,
            warn_at=0.8,
            gate_names=("init", "story_start"),
        )
        self.assertEqual(ceiling.name, "per_run_cap")
        self.assertEqual(ceiling.window, "per_run")
        self.assertEqual(ceiling.limit_usd, 25.0)
        self.assertEqual(ceiling.warn_at, 0.8)
        self.assertEqual(ceiling.gate_names, ("init", "story_start"))


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
            {"index": "0", "reason": "stale", "detail": "from prior test"}
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
        self.assertEqual(
            _run_payload({"policy": {"cost_ceilings": {"not": "a list"}}}), []
        )

    def test_top_level_not_object_returns_empty_list(self) -> None:
        self.assertEqual(_run_payload([1, 2, 3]), [])

    def test_invalid_json_returns_empty_list(self) -> None:
        self.assertEqual(_run_raw("not json {"), [])


class ParseCeilingsConfigMalformedEntryTests(unittest.TestCase):
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
                result = _run_ceilings([_c(limit_usd=limit_val)])
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_value"
                )

    def test_warn_at_out_of_range_is_skipped(self) -> None:
        for warn_at in [0.0, -0.1, 1.5]:
            with self.subTest(warn_at=warn_at):
                result = _run_ceilings([_c(warn_at=warn_at)])
                self.assertEqual(result, [])
                self.assertTrue(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"].startswith(
                        "bad_warn_at"
                    )
                )

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

    def test_bad_limit_usd_type(self) -> None:
        """bool and str types rejected; True is int in Python."""
        for val in [True, "10.0"]:
            with self.subTest(limit_usd=val):
                result = _run_ceilings([_c(limit_usd=val)])
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_type"
                )

    def test_bad_warn_at_type(self) -> None:
        """bool and str types rejected."""
        for val in [True, "0.5"]:
            with self.subTest(warn_at=val):
                result = _run_ceilings([_c(warn_at=val)])
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_warn_at_type"
                )

    def test_bad_name(self) -> None:
        """Non-string and empty string names are rejected."""
        for val in [42, ""]:
            with self.subTest(name=val):
                result = _run_ceilings([_c(name=val)])
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_name"
                )

    def test_bad_window(self) -> None:
        """Non-string and invalid window strings are rejected."""
        for val in [42, "1h"]:
            with self.subTest(window=val):
                result = _run_ceilings([_c(window=val)])
                self.assertEqual(result, [])
                self.assertEqual(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_window"
                )

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
        result = _run_ceilings(
            [
                _c(
                    name="per_run_cap",
                    limit_usd=25.0,
                    warn_at=0.8,
                    gate_names=["init", "story_start"],
                )
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], BudgetCeiling)
        self.assertEqual(result[0].name, "per_run_cap")
        self.assertEqual(result[0].window, "per_run")
        self.assertEqual(result[0].limit_usd, 25.0)
        self.assertEqual(result[0].warn_at, 0.8)
        self.assertEqual(result[0].gate_names, ("init", "story_start"))

    def test_gate_names_become_tuple_not_list(self) -> None:
        result = _run_ceilings([_c(name="c1", window="24h")])
        self.assertIsInstance(result[0].gate_names, tuple)

    def test_multiple_ceilings_preserve_file_order(self) -> None:
        result = _run_ceilings(
            [
                _c(name="first", limit_usd=5.0),
                _c(
                    name="second",
                    window="24h",
                    limit_usd=10.0,
                    warn_at=0.6,
                    gate_names=["story_start"],
                ),
                _c(
                    name="third",
                    window="7d",
                    limit_usd=50.0,
                    warn_at=0.9,
                    gate_names=["retry_start"],
                ),
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

    def _has_future_import_after_optional_docstring(self, src: str) -> bool:
        tree = ast.parse(src)
        body = tree.body
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body = body[1:]
        if not body:
            return False
        head = body[0]
        if not isinstance(head, ast.ImportFrom):
            return False
        return head.module == "__future__" and any(
            alias.name == "annotations" for alias in head.names
        )

    def test_source_file_has_future_annotations(self) -> None:
        src_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "budget_ceilings.py"
        )
        self.assertTrue(
            self._has_future_import_after_optional_docstring(
                src_path.read_text(encoding="utf-8")
            ),
            f"REQ-01 violated for {src_path}",
        )

    def test_test_file_has_future_annotations(self) -> None:
        test_path = Path(__file__).resolve()
        self.assertTrue(
            self._has_future_import_after_optional_docstring(
                test_path.read_text(encoding="utf-8")
            ),
            f"REQ-01 violated for {test_path}",
        )


class LedgerFixturePatternTests(unittest.TestCase):
    """REQ-15: compact_json serialization round-trips via parse_event."""

    def test_event_fixture_round_trips_via_compact_json(self) -> None:
        event = StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=0.25,
            tokens_in=10,
            tokens_out=10,
            attempts=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ensure_dir(tmp)
            ledger = Path(tmp) / "events.jsonl"
            ledger.write_text(compact_json(event.to_dict()) + "\n", encoding="utf-8")
            with ledger.open("r", encoding="utf-8") as handle:
                first = handle.readline().rstrip("\n")
            parsed = parse_event(first)
        self.assertEqual(parsed.run_id, "r1")
        self.assertEqual(getattr(parsed, "cost_usd"), 0.25)


class EvaluatorSurfaceTests(unittest.TestCase):
    def test_evaluate_ceilings_is_importable(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings  # noqa: F401

    def test_bypass_allowed_is_importable(self) -> None:
        from story_automator.core.budget_ceilings import bypass_allowed  # noqa: F401

    def test_exports_include_new_callables(self) -> None:
        self.assertIn("evaluate_ceilings", budget_ceilings.__all__)
        self.assertIn("bypass_allowed", budget_ceilings.__all__)


class EvaluateCeilingsNoConfigTests(unittest.TestCase):
    def test_both_none_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings(
            "events.jsonl", "init", "2026-06-15T00:00:00Z"
        )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_empty_ceilings_list_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings(
            "events.jsonl", "init", "2026-06-15T00:00:00Z", ceilings=[]
        )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_no_config_path_does_not_touch_ledger(self) -> None:
        """Sentinel must short-circuit before any file I/O."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings(
            "/nonexistent/path/to/events.jsonl",
            "init",
            "2026-06-15T00:00:00Z",
        )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")


class EvaluateCeilingsEmptyLedgerTests(unittest.TestCase):
    def _ceiling(self):
        return BudgetCeiling(
            name="c1",
            window="per_run",
            limit_usd=10.0,
            warn_at=0.8,
            gate_names=("init",),
        )

    def test_missing_ledger_file_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "events.jsonl"
            verdict, reason = evaluate_ceilings(
                missing, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")

    def test_empty_ledger_file_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")


class EvaluateCeilingsDecisionRuleTests(unittest.TestCase):
    def _ceiling(self):
        return BudgetCeiling(
            name="c1",
            window="per_run",
            limit_usd=10.0,
            warn_at=0.8,
            gate_names=("init",),
        )

    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_below_warn_threshold_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(1.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=1.0000:limit=10.0000")

    def test_at_warn_threshold_returns_warn(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            # 10.0 * 0.8 = 8.0 exactly
            path = _write_ledger(tmp, [self._event(8.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertEqual(reason, "c1:per_run:spent=8.0000:limit=10.0000")

    def test_between_warn_and_limit_returns_warn(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(5.0), self._event(4.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertEqual(reason, "c1:per_run:spent=9.0000:limit=10.0000")

    def test_at_limit_returns_block(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(10.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertEqual(reason, "c1:per_run:spent=10.0000:limit=10.0000")

    def test_above_limit_returns_block(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(12.5)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertEqual(reason, "c1:per_run:spent=12.5000:limit=10.0000")


class EvaluateCeilingsWindowTests(unittest.TestCase):
    def _event(self, ts, cost):
        return StoryCompleted(
            timestamp=ts,
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def _ceiling(self, window):
        return BudgetCeiling(
            name="c1",
            window=window,
            limit_usd=100.0,
            warn_at=0.5,
            gate_names=("init",),
        )

    def test_per_run_sums_all_events_regardless_of_timestamp(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("1996-01-01T00:00:00Z", 3.0),
            self._event("2026-06-15T00:00:00Z", 4.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("per_run")],
            )
        self.assertIn("spent=7.0000", reason)

    def test_24h_excludes_events_older_than_86400_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-06-13T23:59:59Z", 5.0),
            self._event("2026-06-14T01:00:00Z", 7.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=7.0000", reason)

    def test_7d_excludes_events_older_than_604800_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-06-07T23:59:59Z", 5.0),
            self._event("2026-06-10T00:00:00Z", 9.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("7d")],
            )
        self.assertIn("spent=9.0000", reason)

    def test_30d_excludes_events_older_than_2592000_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-05-15T23:59:59Z", 5.0),
            self._event("2026-05-20T00:00:00Z", 11.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("30d")],
            )
        self.assertIn("spent=11.0000", reason)

    def test_unparseable_event_timestamp_is_skipped_in_windowed_modes(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("not-a-timestamp", 99.0),
            self._event("2026-06-14T12:00:00Z", 3.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=3.0000", reason)

    def test_future_event_beyond_window_is_excluded(self) -> None:
        """REQ-08 'within N seconds' is symmetric."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-12-31T00:00:00Z", 50.0),
            self._event("2026-06-14T12:00:00Z", 3.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=3.0000", reason)

    def test_unparseable_now_iso_short_circuits_to_zero_in_windowed_modes(self) -> None:
        """A bad now_iso plus a windowed ceiling counts zero spend."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [self._event("2026-06-14T12:00:00Z", 50.0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path,
                "init",
                "not-a-timestamp",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=0.0000", reason)


if __name__ == "__main__":
    unittest.main()
