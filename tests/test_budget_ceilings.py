from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import budget_ceilings  # noqa: F401


if __name__ == "__main__":
    unittest.main()
