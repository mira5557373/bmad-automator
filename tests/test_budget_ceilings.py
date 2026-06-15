from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import budget_ceilings  # noqa: F401


class CeilingDecisionTests(unittest.TestCase):
    def test_has_exactly_three_members(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertEqual(len(list(CeilingDecision)), 3)

    def test_member_names_and_order(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        names = [m.name for m in CeilingDecision]
        self.assertEqual(names, ["ALLOW", "WARN", "BLOCK"])

    def test_member_values_match_names(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertEqual(CeilingDecision.ALLOW.value, "ALLOW")
        self.assertEqual(CeilingDecision.WARN.value, "WARN")
        self.assertEqual(CeilingDecision.BLOCK.value, "BLOCK")

    def test_is_enum_subclass(self) -> None:
        import enum

        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertTrue(issubclass(CeilingDecision, enum.Enum))


class BudgetCeilingShapeTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        import dataclasses

        from story_automator.core.budget_ceilings import BudgetCeiling

        self.assertTrue(dataclasses.is_dataclass(BudgetCeiling))
        with self.assertRaises(TypeError):
            BudgetCeiling("c1", "per_run", 10.0, 0.8, ("init",))  # type: ignore[misc]

    def test_field_names_exact(self) -> None:
        import dataclasses

        from story_automator.core.budget_ceilings import BudgetCeiling

        names = [f.name for f in dataclasses.fields(BudgetCeiling)]
        self.assertEqual(
            names,
            ["name", "window", "limit_usd", "warn_at", "gate_names"],
        )

    def test_can_construct_with_keywords(self) -> None:
        from story_automator.core.budget_ceilings import BudgetCeiling

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
        from story_automator.core import budget_ceilings

        self.assertTrue(hasattr(budget_ceilings, "_PARSE_WARNINGS"))
        self.assertIsInstance(budget_ceilings._PARSE_WARNINGS, list)

    def test_parse_warnings_starts_empty(self) -> None:
        from story_automator.core import budget_ceilings

        first = budget_ceilings._PARSE_WARNINGS
        second = budget_ceilings._PARSE_WARNINGS
        self.assertIs(first, second)


class ParseCeilingsConfigMissingFileTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.json"
            result = parse_ceilings_config(missing)
            self.assertEqual(result, [])

    def test_missing_file_accepts_str_path(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does-not-exist.json")
            result = parse_ceilings_config(missing)
            self.assertEqual(result, [])

    def test_missing_file_clears_parse_warnings(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        budget_ceilings._PARSE_WARNINGS.append(
            {"index": "0", "reason": "stale", "detail": "from prior test"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            parse_ceilings_config(Path(tmp) / "missing.json")
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class ParseCeilingsConfigMissingKeysTests(unittest.TestCase):
    def _write(self, tmp: str, payload: object) -> Path:
        path = Path(tmp) / "workflow.json"
        path.write_text(compact_json(payload), encoding="utf-8")
        return path

    def test_empty_object_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_no_policy_key_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"other": {"foo": "bar"}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_no_cost_ceilings_key_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"policy": {"unrelated": 1}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_cost_ceilings_not_a_list_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"policy": {"cost_ceilings": {"not": "a list"}}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_top_level_not_object_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(compact_json([1, 2, 3]), encoding="utf-8")
            self.assertEqual(parse_ceilings_config(path), [])

    def test_invalid_json_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text("not json {", encoding="utf-8")
            self.assertEqual(parse_ceilings_config(path), [])


class ParseCeilingsConfigMalformedEntryTests(unittest.TestCase):
    def _write(self, tmp: str, ceilings: list[object]) -> Path:
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings}}),
            encoding="utf-8",
        )
        return path

    def test_missing_required_key_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "gate_names": ["init"],
                    },
                    {
                        "name": "good",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    },
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual([c.name for c in result], ["good"])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "missing_keys")
        self.assertIn("warn_at", budget_ceilings._PARSE_WARNINGS[0]["detail"])

    def test_invalid_window_string_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "1h",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_window")

    def test_negative_limit_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": -1.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_value"
        )

    def test_zero_limit_is_skipped(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": 0.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])

    def test_warn_at_out_of_range_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        cases = [0.0, -0.1, 1.5]
        for warn_at in cases:
            with self.subTest(warn_at=warn_at):
                with tempfile.TemporaryDirectory() as tmp:
                    path = self._write(
                        tmp,
                        [
                            {
                                "name": "bad",
                                "window": "per_run",
                                "limit_usd": 10.0,
                                "warn_at": warn_at,
                                "gate_names": ["init"],
                            }
                        ],
                    )
                    result = parse_ceilings_config(path)
                self.assertEqual(result, [])
                self.assertTrue(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"].startswith(
                        "bad_warn_at"
                    )
                )

    def test_boundary_warn_at_one_is_allowed(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "ok",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 1.0,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].warn_at, 1.0)

    def test_non_object_entry_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, ["not an object", 42, None])
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 3)
        for warning in budget_ceilings._PARSE_WARNINGS:
            self.assertEqual(warning["reason"], "not_object")

    def test_gate_names_must_be_list_of_strings(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": "init",
                    },
                    {
                        "name": "bad2",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": [1, 2],
                    },
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        reasons = [w["reason"] for w in budget_ceilings._PARSE_WARNINGS]
        self.assertEqual(reasons, ["bad_gate_names", "bad_gate_names"])

    def test_warnings_cleared_on_each_call(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            bad_path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "nope",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            parse_ceilings_config(bad_path)
            self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)

            good_path = Path(tmp) / "workflow2.json"
            good_path.write_text(
                compact_json(
                    {
                        "policy": {
                            "cost_ceilings": [
                                {
                                    "name": "ok",
                                    "window": "per_run",
                                    "limit_usd": 10.0,
                                    "warn_at": 0.5,
                                    "gate_names": ["init"],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            parse_ceilings_config(good_path)
            self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_bool_is_not_accepted_as_limit_usd(self) -> None:
        """``True`` is an ``int`` in Python; the validator explicitly
        rejects bool to avoid silently coercing ``True`` to 1.0."""
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": True,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_type"
        )

    def test_string_limit_usd_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": "10.0",
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_type"
        )

    def test_bool_is_not_accepted_as_warn_at(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": True,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_warn_at_type"
        )

    def test_string_warn_at_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": "0.5",
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_warn_at_type"
        )

    def test_non_string_name_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": 42,
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_name")

    def test_empty_string_name_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_name")

    def test_non_string_window_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "bad",
                        "window": 42,
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_window")

    def test_utf8_non_ascii_name_round_trips(self) -> None:
        """REQ-04 says UTF-8 reading; confirm non-ASCII names survive."""
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "ceiling-ünïcödé",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "ceiling-ünïcödé")


class ParseCeilingsConfigHappyPathTests(unittest.TestCase):
    def _write(self, tmp: str, ceilings: list[dict[str, object]]) -> Path:
        ensure_dir(tmp)
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings}}),
            encoding="utf-8",
        )
        return path

    def test_single_well_formed_ceiling_parses(self) -> None:
        from story_automator.core.budget_ceilings import (
            BudgetCeiling,
            parse_ceilings_config,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "per_run_cap",
                        "window": "per_run",
                        "limit_usd": 25.0,
                        "warn_at": 0.8,
                        "gate_names": ["init", "story_start"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], BudgetCeiling)
            self.assertEqual(result[0].name, "per_run_cap")
            self.assertEqual(result[0].window, "per_run")
            self.assertEqual(result[0].limit_usd, 25.0)
            self.assertEqual(result[0].warn_at, 0.8)
            self.assertEqual(result[0].gate_names, ("init", "story_start"))

    def test_gate_names_become_tuple_not_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "c1",
                        "window": "24h",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
            self.assertIsInstance(result[0].gate_names, tuple)

    def test_multiple_ceilings_preserve_file_order(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "first",
                        "window": "per_run",
                        "limit_usd": 5.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    },
                    {
                        "name": "second",
                        "window": "24h",
                        "limit_usd": 10.0,
                        "warn_at": 0.6,
                        "gate_names": ["story_start"],
                    },
                    {
                        "name": "third",
                        "window": "7d",
                        "limit_usd": 50.0,
                        "warn_at": 0.9,
                        "gate_names": ["retry_start"],
                    },
                ],
            )
            result = parse_ceilings_config(path)
            self.assertEqual([c.name for c in result], ["first", "second", "third"])

    def test_happy_path_leaves_parse_warnings_empty(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "c1",
                        "window": "30d",
                        "limit_usd": 100.0,
                        "warn_at": 0.75,
                        "gate_names": ["init"],
                    }
                ],
            )
            parse_ceilings_config(path)
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])


class SpecReq01PreludeTests(unittest.TestCase):
    """REQ-01: both new files must declare
    ``from __future__ import annotations``. The existing project
    convention (see core/telemetry_events.py) places the module
    docstring before the future import; this test tolerates a
    docstring prelude but rejects any executable code between the
    docstring and the future import."""

    def _has_future_import_after_optional_docstring(self, src: str) -> bool:
        import ast

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
    """REQ-15: fixtures must be built by serializing M01 event instances
    through ``compact_json``. This sub-milestone has no evaluator yet,
    but the fixture-building utility is exercised here so M03-M2 can
    rely on it. The test asserts only that the fixture round-trips
    through ``parse_event`` — no ceiling evaluation runs."""

    def test_event_fixture_round_trips_via_compact_json(self) -> None:
        from story_automator.core.telemetry_events import (
            StoryCompleted,
            parse_event,
        )

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
            line = compact_json(event.to_dict())
            ledger.write_text(line + "\n", encoding="utf-8")

            with ledger.open("r", encoding="utf-8") as handle:
                first = handle.readline().rstrip("\n")
            parsed = parse_event(first)
        self.assertEqual(parsed.run_id, "r1")
        self.assertEqual(getattr(parsed, "cost_usd"), 0.25)


if __name__ == "__main__":
    unittest.main()
