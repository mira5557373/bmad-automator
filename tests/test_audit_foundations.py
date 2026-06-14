from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_MODULE_PATH = (
    REPO_ROOT
    / "skills"
    / "bmad-story-automator"
    / "src"
    / "story_automator"
    / "core"
    / "audit.py"
)


def _parsed_audit_module() -> ast.Module:
    return ast.parse(AUDIT_MODULE_PATH.read_text(encoding="utf-8"))


class AuditModuleExistsTests(unittest.TestCase):
    def test_module_file_exists(self) -> None:
        self.assertTrue(
            AUDIT_MODULE_PATH.is_file(), f"missing audit module: {AUDIT_MODULE_PATH}"
        )

    def test_first_real_statement_is_future_annotations(self) -> None:
        # Use AST so a multi-line module docstring is recognised correctly —
        # naïve line-by-line scanning would misread docstring continuation
        # lines as code.
        tree = _parsed_audit_module()
        body = list(tree.body)
        self.assertGreater(len(body), 0, "audit.py has no statements")
        # Skip an optional module docstring (Expr wrapping a string Constant).
        idx = 0
        if (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            idx = 1
        self.assertGreater(len(body), idx, "audit.py has no statements after docstring")
        first = body[idx]
        self.assertIsInstance(
            first,
            ast.ImportFrom,
            "first real statement must be `from __future__ import annotations`",
        )
        assert isinstance(first, ast.ImportFrom)  # narrows type for mypy/readers
        self.assertEqual(first.module, "__future__")
        self.assertEqual([alias.name for alias in first.names], ["annotations"])


class AuditPublicApiTests(unittest.TestCase):
    def test_all_lists_milestone_surface(self) -> None:
        import story_automator.core.audit as audit

        self.assertEqual(
            sorted(audit.__all__),
            sorted(
                [
                    "AuditKeyMissing",
                    "AuditLockTimeout",
                    "derive_key",
                    "load_key_from_env",
                ]
            ),
        )


class AuditModuleSizeBudgetTests(unittest.TestCase):
    def test_module_at_or_below_500_lines(self) -> None:
        line_count = sum(
            1 for _ in AUDIT_MODULE_PATH.read_text(encoding="utf-8").splitlines()
        )
        self.assertLessEqual(
            line_count, 500, f"audit.py is {line_count} lines (budget: 500)"
        )


class AuditLockTimeoutTests(unittest.TestCase):
    def test_subclasses_runtime_error(self) -> None:
        from story_automator.core.audit import AuditLockTimeout

        self.assertTrue(issubclass(AuditLockTimeout, RuntimeError))

    def test_can_be_raised_and_caught(self) -> None:
        from story_automator.core.audit import AuditLockTimeout

        with self.assertRaises(AuditLockTimeout) as ctx:
            raise AuditLockTimeout("lock held by another writer")
        self.assertIn("lock held", str(ctx.exception))

    def test_has_docstring(self) -> None:
        from story_automator.core.audit import AuditLockTimeout

        self.assertTrue(AuditLockTimeout.__doc__ and AuditLockTimeout.__doc__.strip())


class AuditKeyMissingTests(unittest.TestCase):
    def test_subclasses_runtime_error(self) -> None:
        from story_automator.core.audit import AuditKeyMissing

        self.assertTrue(issubclass(AuditKeyMissing, RuntimeError))

    def test_can_be_raised_and_caught(self) -> None:
        from story_automator.core.audit import AuditKeyMissing

        with self.assertRaises(AuditKeyMissing) as ctx:
            raise AuditKeyMissing("BMAD_AUDIT_KEY is not set")
        self.assertIn("BMAD_AUDIT_KEY", str(ctx.exception))

    def test_distinct_from_lock_timeout(self) -> None:
        from story_automator.core.audit import AuditKeyMissing, AuditLockTimeout

        self.assertIsNot(AuditKeyMissing, AuditLockTimeout)
        self.assertFalse(issubclass(AuditKeyMissing, AuditLockTimeout))
        self.assertFalse(issubclass(AuditLockTimeout, AuditKeyMissing))

    def test_has_docstring(self) -> None:
        from story_automator.core.audit import AuditKeyMissing

        self.assertTrue(AuditKeyMissing.__doc__ and AuditKeyMissing.__doc__.strip())


if __name__ == "__main__":
    unittest.main()
