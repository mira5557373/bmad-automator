from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
