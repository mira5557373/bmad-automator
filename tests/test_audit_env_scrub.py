"""D-04 followup — sibling-module + rename-proof AST-skip invariants.

The D-04 trust-boundary scrub helper originally lived inside ``core/audit.py``.
The followup moves the implementation to a sibling module
``core/audit_env_scrub.py`` so that:

  * ``audit.py`` regains LOC headroom against the 500-line soft limit.
  * The AST regression test in ``tests/test_audit_regression.py`` skips the
    helper's implementation file by *structure* (does the file define a
    top-level ``scrub_env_for_subprocess`` function?) rather than by the
    hard-coded filename ``audit.py``.

Back-compat: ``audit.py`` re-exports ``scrub_env_for_subprocess`` so every
existing call site keeps working unchanged. These tests pin that contract.
"""

from __future__ import annotations

import ast
import textwrap
import unittest
from pathlib import Path


SKILL_SRC = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "bmad-story-automator"
    / "src"
    / "story_automator"
)


class HelperSiblingModuleTests(unittest.TestCase):
    """Pins that scrub_env_for_subprocess lives in audit_env_scrub.py."""

    def test_scrub_helper_lives_in_sibling_module(self) -> None:
        """The implementation file must be ``audit_env_scrub.py`` — NOT ``audit.py``.

        We parse both files' top-level definitions and assert that the helper
        is defined in the sibling, not in audit.py. This anchors the LOC
        budget split so a future refactor cannot silently fold the helper
        back into audit.py.
        """
        sibling = SKILL_SRC / "core" / "audit_env_scrub.py"
        audit = SKILL_SRC / "core" / "audit.py"
        self.assertTrue(
            sibling.exists(),
            f"sibling module is missing: {sibling}",
        )

        def _defines_helper(path: Path) -> bool:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if (
                    isinstance(node, ast.FunctionDef)
                    and node.name == "scrub_env_for_subprocess"
                ):
                    return True
            return False

        self.assertTrue(
            _defines_helper(sibling),
            "audit_env_scrub.py must define scrub_env_for_subprocess",
        )
        self.assertFalse(
            _defines_helper(audit),
            "audit.py must NOT define scrub_env_for_subprocess — "
            "it should re-export from audit_env_scrub",
        )

    def test_audit_reexports_scrub_helper(self) -> None:
        """Existing call sites must keep working — ``from .audit import …``.

        ~25 call sites in core/ + commands/ + tests/ import the helper from
        ``story_automator.core.audit``. The re-export pattern preserves that
        contract.
        """
        from story_automator.core.audit import scrub_env_for_subprocess
        from story_automator.core.audit_env_scrub import (
            scrub_env_for_subprocess as direct,
        )

        # Both names resolve to the same function object — proves re-export
        # rather than a duplicate definition.
        self.assertIs(scrub_env_for_subprocess, direct)

        # And the function is still listed in audit.__all__.
        import story_automator.core.audit as audit_mod

        self.assertIn("scrub_env_for_subprocess", audit_mod.__all__)


class AstSkipStructuralDetectionTests(unittest.TestCase):
    """Pins that the AST skip is structural (function-def driven), not filename-driven.

    These tests replicate the AST-walk logic the regression test uses, on
    synthesized in-memory snippets. They assert:

      * A file named ``audit.py`` that does NOT define the helper is NOT
        skipped (a future renaming of the real audit.py to a different name,
        leaving a stub at the old path, must not free that stub from the
        invariant).
      * A file with any other name that DOES define the helper IS skipped
        (a future split that names the sibling ``audit_env_scrub.py`` or
        ``audit_helpers.py`` must auto-skip without touching the regression
        test).
    """

    @staticmethod
    def _defines_helper(source: str) -> bool:
        """Replicate the structural skip used by the AST regression test."""
        tree = ast.parse(source)
        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "scrub_env_for_subprocess"
            ):
                return True
        return False

    def test_ast_skip_is_structural_not_filename(self) -> None:
        # A file named "audit.py" with NO helper definition must NOT be
        # skipped — the skip is structural, not name-based.
        fake_audit_source = textwrap.dedent(
            """\
            from __future__ import annotations

            import subprocess


            def some_helper() -> None:
                subprocess.run(["echo", "hi"], env={"X": "1"})
            """
        )
        self.assertFalse(
            self._defines_helper(fake_audit_source),
            "structural check must not treat a stub audit.py as the impl file",
        )

    def test_ast_skip_detects_helper_definition(self) -> None:
        # A file with a non-"audit" name but that DOES define the helper
        # must be detected as the implementation file (and skipped).
        sibling_source = textwrap.dedent(
            """\
            from __future__ import annotations

            import os
            from typing import Mapping

            _AUDIT_ENV_KEYS_TO_SCRUB = frozenset({"BMAD_AUDIT_KEY"})


            def scrub_env_for_subprocess(env=None):
                source = dict(os.environ if env is None else env)
                for key in _AUDIT_ENV_KEYS_TO_SCRUB:
                    source.pop(key, None)
                return source
            """
        )
        self.assertTrue(
            self._defines_helper(sibling_source),
            "structural check must detect any module that defines the helper",
        )


if __name__ == "__main__":
    unittest.main()
