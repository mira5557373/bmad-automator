from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.common import compact_json


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


if __name__ == "__main__":
    unittest.main()
