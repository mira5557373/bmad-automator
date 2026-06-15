from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import failure_triage  # noqa: F401
