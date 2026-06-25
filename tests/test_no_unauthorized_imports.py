"""Enforce the self-contained-runtime invariant: the shipped Python runtime
must import only the standard library and its own first-party package.

The npm package advertises a self-contained Python runtime with no third-party
dependencies (pyproject declares none, and the install path ships only source).
A silently-added `import requests`/`yaml`/`filelock`/... would break a clean
install at first use. This ast-walk guard fails CI the moment such an import
appears, instead of at a user's first emit.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "skills" / "bmad-story-automator" / "src" / "story_automator"

FIRST_PARTY = {"story_automator"}
# Names not present in sys.stdlib_module_names but always importable.
EXTRA_ALLOWED = {"__future__"}
# Third-party deps declared in pyproject.toml. Per CLAUDE.md hard guardrail:
# stdlib + filelock + psutil only — adding a new entry here requires an
# explicit spec waiver, since this is the canonical "no surprise deps" gate.
DECLARED_DEPS = {"filelock", "psutil"}


def _top_level_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import — always first-party
            if node.module:
                names.add(node.module.split(".")[0])
    return names


class NoUnauthorizedImportsTests(unittest.TestCase):
    def test_runtime_imports_are_stdlib_or_first_party(self) -> None:
        self.assertTrue(SRC_ROOT.is_dir(), f"source root not found: {SRC_ROOT}")
        allowed = set(sys.stdlib_module_names) | FIRST_PARTY | EXTRA_ALLOWED | DECLARED_DEPS
        violations: dict[str, set[str]] = {}
        py_files = sorted(SRC_ROOT.rglob("*.py"))
        self.assertTrue(py_files, "no python files discovered under src")
        for path in py_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offending = {name for name in _top_level_imports(tree) if name and name not in allowed}
            if offending:
                violations[str(path.relative_to(SRC_ROOT))] = offending
        self.assertEqual(
            violations,
            {},
            "non-stdlib / non-first-party imports found in the shipped runtime "
            f"(add a real dependency to pyproject before importing): {violations}",
        )


if __name__ == "__main__":
    unittest.main()
