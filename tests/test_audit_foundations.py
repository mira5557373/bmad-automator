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


import hmac  # noqa: E402 - plan keeps imports adjacent to first usage
import hashlib  # noqa: E402 - plan keeps imports adjacent to first usage


class HkdfExtractTests(unittest.TestCase):
    def test_matches_hmac_sha256(self) -> None:
        from story_automator.core.audit import _hkdf_extract

        salt = b"bmad-audit-v1"
        ikm = b"test-secret"
        expected = hmac.new(salt, ikm, hashlib.sha256).digest()
        self.assertEqual(_hkdf_extract(salt, ikm), expected)
        self.assertEqual(len(_hkdf_extract(salt, ikm)), 32)

    def test_empty_salt_uses_zero_length_key(self) -> None:
        from story_automator.core.audit import _hkdf_extract

        ikm = b"abc"
        expected = hmac.new(b"", ikm, hashlib.sha256).digest()
        self.assertEqual(_hkdf_extract(b"", ikm), expected)


class HkdfExpandTests(unittest.TestCase):
    def test_single_block_output_32_bytes(self) -> None:
        from story_automator.core.audit import _hkdf_expand

        prk = b"\x11" * 32
        info = b"audit-chain"
        t1 = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
        self.assertEqual(_hkdf_expand(prk, info, 32), t1)

    def test_multi_block_chains_previous_t(self) -> None:
        from story_automator.core.audit import _hkdf_expand

        prk = b"\x22" * 32
        info = b"audit-chain"
        t1 = hmac.new(prk, b"" + info + b"\x01", hashlib.sha256).digest()
        t2 = hmac.new(prk, t1 + info + b"\x02", hashlib.sha256).digest()
        self.assertEqual(_hkdf_expand(prk, info, 64), t1 + t2)

    def test_truncates_to_requested_length(self) -> None:
        from story_automator.core.audit import _hkdf_expand

        prk = b"\x33" * 32
        self.assertEqual(len(_hkdf_expand(prk, b"audit-chain", 10)), 10)

    def test_rejects_length_over_8160(self) -> None:
        from story_automator.core.audit import _hkdf_expand

        with self.assertRaises(ValueError):
            _hkdf_expand(b"\x44" * 32, b"audit-chain", 8161)


class DeriveKeyTests(unittest.TestCase):
    DEFAULT_VECTORS = {
        "test-secret": "6e4452e3b4aa348f94f2f85f8cadb311d212993e9c5313281fddacb3435c8c8f",
        "a": "be84295cf7f53d78930226f9ce762c8f43cc0f619cd3a0c8c502f796ed73b5bf",
        "rotate-me-2026": "3a685fdd5172d4eb599420312d5a83445d4d61b1b856cf671e81973d49f42b82",
    }

    def test_default_salt_matches_rfc_vectors(self) -> None:
        from story_automator.core.audit import derive_key

        for secret, expected_hex in self.DEFAULT_VECTORS.items():
            with self.subTest(secret=secret):
                key = derive_key(secret)
                self.assertEqual(key.hex(), expected_hex)
                self.assertEqual(len(key), 32)
                self.assertIsInstance(key, bytes)

    def test_custom_salt_changes_output(self) -> None:
        from story_automator.core.audit import derive_key

        custom = derive_key("test-secret", salt=b"custom-salt")
        self.assertEqual(
            custom.hex(),
            "200ca78c7bd60448c4676b3009fb33ce374f8c75f02042d7a154b40dc09e4a2f",
        )
        self.assertNotEqual(custom, derive_key("test-secret"))

    def test_salt_is_keyword_only(self) -> None:
        from story_automator.core.audit import derive_key

        with self.assertRaises(TypeError):
            derive_key("test-secret", b"positional-salt")  # type: ignore[misc]

    def test_does_not_use_pbkdf2(self) -> None:
        # REQ-03 forbids hashlib.pbkdf2_hmac. Smoke test: the implementation
        # must not equal the pbkdf2_hmac output for any reasonable iteration count.
        from story_automator.core.audit import derive_key

        actual = derive_key("test-secret")
        for iters in (1, 1000, 100_000):
            forbidden = hashlib.pbkdf2_hmac(
                "sha256", b"test-secret", b"bmad-audit-v1", iters, 32
            )
            self.assertNotEqual(
                actual,
                forbidden,
                f"derive_key accidentally matches pbkdf2_hmac at {iters} iters",
            )

    def test_docstring_present(self) -> None:
        from story_automator.core.audit import derive_key

        self.assertTrue(derive_key.__doc__ and "HKDF" in derive_key.__doc__)


class LoadKeyFromEnvHappyPathTests(unittest.TestCase):
    def test_reads_supplied_env_mapping(self) -> None:
        from story_automator.core.audit import derive_key, load_key_from_env

        key = load_key_from_env({"BMAD_AUDIT_KEY": "test-secret"})
        self.assertEqual(key, derive_key("test-secret"))

    def test_reads_process_environment_when_env_is_none(self) -> None:
        import os
        from unittest.mock import patch
        from story_automator.core.audit import derive_key, load_key_from_env

        with patch.dict(
            os.environ, {"BMAD_AUDIT_KEY": "from-process-env"}, clear=False
        ):
            key = load_key_from_env()
        self.assertEqual(key, derive_key("from-process-env"))

    def test_returns_bytes_of_length_32(self) -> None:
        from story_automator.core.audit import load_key_from_env

        key = load_key_from_env({"BMAD_AUDIT_KEY": "x"})
        assert key is not None
        self.assertIsInstance(key, bytes)
        self.assertEqual(len(key), 32)


class LoadKeyFromEnvAbsentContractTests(unittest.TestCase):
    def test_returns_none_when_env_mapping_is_empty(self) -> None:
        from story_automator.core.audit import load_key_from_env

        self.assertIsNone(load_key_from_env({}))

    def test_returns_none_when_var_is_empty_string(self) -> None:
        from story_automator.core.audit import load_key_from_env

        self.assertIsNone(load_key_from_env({"BMAD_AUDIT_KEY": ""}))

    def test_returns_none_when_var_missing_from_process_env(self) -> None:
        import os
        from unittest.mock import patch
        from story_automator.core.audit import load_key_from_env

        scrubbed = {k: v for k, v in os.environ.items() if k != "BMAD_AUDIT_KEY"}
        with patch.dict(os.environ, scrubbed, clear=True):
            self.assertIsNone(load_key_from_env())

    def test_does_not_raise_on_unrelated_env_keys(self) -> None:
        from story_automator.core.audit import load_key_from_env

        try:
            load_key_from_env({"OTHER_VAR": "x", "PATH": "/usr/bin"})
        except Exception as exc:  # noqa: BLE001 - asserting absence
            self.fail(f"load_key_from_env raised on absent var: {exc!r}")

    def test_returns_none_not_empty_bytes(self) -> None:
        from story_automator.core.audit import load_key_from_env

        result = load_key_from_env({})
        self.assertIsNone(result)
        self.assertNotEqual(result, b"")


if __name__ == "__main__":
    unittest.main()
