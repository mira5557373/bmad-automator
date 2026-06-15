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


if __name__ == "__main__":
    unittest.main()
