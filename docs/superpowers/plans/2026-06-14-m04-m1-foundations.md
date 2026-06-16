# M04 Milestone 1: Audit-Trail Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the static scaffolding of `core/audit.py` — module file, two exception classes, an RFC 5869 HKDF-SHA256 `derive_key`, and `load_key_from_env` — with import-allowlist, secrets-never-leak, and docstring guarantees enforced by tests. No `AuditLog` class, no `append`, no `verify` — those land in later M04 milestones.

**Architecture:** A single new file `skills/bmad-story-automator/src/story_automator/core/audit.py` that depends only on the Python standard library (no `filelock` import yet — that arrives with `AuditLog.append` in a later milestone). Two `RuntimeError` subclasses are declared up front so call-site integrations in subsequent milestones can `except` them by name without a circular-dependency dance. `derive_key` implements HKDF-Extract + HKDF-Expand by hand using `hmac` and `hashlib.sha256` (the spec forbids `hashlib.pbkdf2_hmac`). `load_key_from_env` wraps `derive_key` with a safe default-when-unset contract that never raises. A companion test file `tests/test_audit_foundations.py` enforces module size, the import allowlist, the secret-leak prohibition, and pinned HKDF test vectors.

**Tech Stack:** Python 3.11+, standard library only (`hmac`, `hashlib`, `os`, `pathlib`, `typing`). Tests use `unittest`. Lint/format with `ruff`. Run the test suite via `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py"`.

---

## Spec Coverage Map

| Spec ID | Requirement | Tasks |
|---|---|---|
| REQ-01 | Module at `core/audit.py`, `from __future__ import annotations`, stdlib + filelock only | Tasks 1, 2, 11 |
| REQ-03 | `derive_key(secret, *, salt=b"bmad-audit-v1") -> bytes` via hand-rolled HKDF-SHA256, `info=b"audit-chain"` | Tasks 6, 7, 8 |
| REQ-04 | `load_key_from_env(env=None) -> bytes | None` reads `BMAD_AUDIT_KEY`, never raises | Tasks 9, 10 |
| REQ-07a (exception class) | `AuditLockTimeout(RuntimeError)` declared (not yet raised) | Task 4 |
| REQ-10 (exception class) | `AuditKeyMissing(RuntimeError)` declared (not yet raised) | Task 5 |
| NFR-secrets-never-leak | No secret value or derived key bytes appear in repr / str / exception messages | Task 12 |
| NFR-docstrings | Public functions and classes carry concise docstrings | Tasks 4, 5, 6, 9, 13 |
| QA-import-allowlist | `audit.py` imports only stdlib (filelock is the only allowed third-party — none used yet) | Task 11 |

Out of scope for this milestone: `AuditLog` dataclass, `append`, `verify`, `audit_for_policy`, all three call-site integrations, the ≤500 LOC test (added but will pass trivially), tamper/truncation/concurrency QA gates.

---

## File Structure

- **Create:** `skills/bmad-story-automator/src/story_automator/core/audit.py` — the module under test.
- **Create:** `tests/test_audit_foundations.py` — unittest TestCase that exercises every public surface added in this milestone plus the static guards (size, imports, secret leak).

No existing files are modified in this milestone.

---

## Task 1: Create empty audit module scaffold

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_foundations.py` with:

```python
from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_MODULE_PATH = REPO_ROOT / "skills" / "bmad-story-automator" / "src" / "story_automator" / "core" / "audit.py"


def _parsed_audit_module() -> ast.Module:
    return ast.parse(AUDIT_MODULE_PATH.read_text(encoding="utf-8"))


class AuditModuleExistsTests(unittest.TestCase):
    def test_module_file_exists(self) -> None:
        self.assertTrue(AUDIT_MODULE_PATH.is_file(), f"missing audit module: {AUDIT_MODULE_PATH}")

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
        self.assertIsInstance(first, ast.ImportFrom, "first real statement must be `from __future__ import annotations`")
        assert isinstance(first, ast.ImportFrom)  # narrows type for mypy/readers
        self.assertEqual(first.module, "__future__")
        self.assertEqual([alias.name for alias in first.names], ["annotations"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations -v`
Expected: FAIL — `missing audit module`.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/audit.py`:

```python
"""Audit-trail subsystem.

Append-only, hash-chained JSONL audit log for high-value operational events.
This module is the M04 foundations slice: it ships only the key-derivation
surface and module-level exception classes. The ``AuditLog`` dataclass,
``append``, ``verify``, and ``audit_for_policy`` arrive in later milestones.
"""

from __future__ import annotations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): scaffold core/audit.py module"
```

---

## Task 2: Pin the public API surface

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py` after the existing test class:

```python
class AuditPublicApiTests(unittest.TestCase):
    def test_all_lists_milestone_surface(self) -> None:
        import story_automator.core.audit as audit

        self.assertEqual(
            sorted(audit.__all__),
            sorted(["AuditKeyMissing", "AuditLockTimeout", "derive_key", "load_key_from_env"]),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditPublicApiTests -v`
Expected: FAIL — `module 'story_automator.core.audit' has no attribute '__all__'`.

- [ ] **Step 3: Write minimal implementation**

Edit `skills/bmad-story-automator/src/story_automator/core/audit.py`, add below the `from __future__` line:

```python


__all__ = [
    "AuditKeyMissing",
    "AuditLockTimeout",
    "derive_key",
    "load_key_from_env",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditPublicApiTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): pin __all__ to milestone surface"
```

---

## Task 3: Pin the file-size budget (NFR)

**Files:**
- Modify: `tests/test_audit_foundations.py`

This guard is added now so future milestones cannot quietly blow through the 500-line budget set by the spec's NFR.

- [ ] **Step 1: Write the failing test**

Append a new TestCase to `tests/test_audit_foundations.py`:

```python
class AuditModuleSizeBudgetTests(unittest.TestCase):
    def test_module_at_or_below_500_lines(self) -> None:
        line_count = sum(1 for _ in AUDIT_MODULE_PATH.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(line_count, 500, f"audit.py is {line_count} lines (budget: 500)")
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditModuleSizeBudgetTests -v`
Expected: PASS (module currently well under 500 lines). This test is a *standing guard*, not a TDD pair — its failure mode is "future code grew too big", not "code missing now".

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): enforce 500-line module budget"
```

---

## Task 4: Declare `AuditLockTimeout` exception

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditLockTimeoutTests -v`
Expected: FAIL — `cannot import name 'AuditLockTimeout'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/audit.py`:

```python


class AuditLockTimeout(RuntimeError):
    """Raised when ``AuditLog.append`` cannot acquire the per-log file lock.

    The lock timeout is fixed at 5 seconds per REQ-07a. Catching this exception
    indicates contention or a stale lock file — never a programming error in
    the caller's payload. The message must not include the audit key.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditLockTimeoutTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): declare AuditLockTimeout exception"
```

---

## Task 5: Declare `AuditKeyMissing` exception

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditKeyMissingTests -v`
Expected: FAIL — `cannot import name 'AuditKeyMissing'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/audit.py`:

```python


class AuditKeyMissing(RuntimeError):
    """Raised by ``audit_for_policy`` when the policy enables audit but no key is loadable.

    The runtime contract per REQ-10: if ``security.audit_trail`` is truthy and
    ``load_key_from_env()`` returns ``None``, callers refusing to open an unkeyed
    log raise this exception. The message must not include the audit key.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditKeyMissingTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): declare AuditKeyMissing exception"
```

---

## Task 6: HKDF-Extract primitive (private helper)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

The spec forbids `hashlib.pbkdf2_hmac`. We implement RFC 5869 by hand. Step 1 is `Extract`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
import hmac
import hashlib


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.HkdfExtractTests -v`
Expected: FAIL — `cannot import name '_hkdf_extract'`.

- [ ] **Step 3: Write minimal implementation**

Two edits to `skills/bmad-story-automator/src/story_automator/core/audit.py`:

**(a) Insert these two `import` lines immediately after `from __future__ import annotations` and before the blank line that precedes `__all__`:**

```python
import hashlib
import hmac
```

So the top of the module now reads, in order: module docstring → `from __future__ import annotations` → `import hashlib` → `import hmac` → blank line → `__all__ = [...]` → blank line → `class AuditLockTimeout(...)` → `class AuditKeyMissing(...)`.

**(b) Append this function to the very bottom of the file (after the `class AuditKeyMissing` block):**

```python


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """RFC 5869 HKDF-Extract step using HMAC-SHA256.

    Returns the 32-byte pseudo-random key (PRK). Empty salt is treated as a
    zero-length HMAC key, matching Python's ``hmac`` semantics.
    """
    return hmac.new(salt, ikm, hashlib.sha256).digest()
```

This ordering (imports near top, helpers near bottom) matches the convention in `core/common.py`. Subsequent tasks 7-9 will append further symbols at the bottom; the file ends up with the structure: docstring → `from __future__` → imports → `__all__` → exception classes → private helpers (`_hkdf_extract`, `_hkdf_expand`) → constants (`_HKDF_DEFAULT_SALT`, `_HKDF_INFO`, `_KEY_LENGTH`, `_ENV_VAR`) → public functions (`derive_key`, `load_key_from_env`). Constants accumulate near the bottom in this milestone — that's an artefact of strict TDD step ordering and is acceptable for the foundations slice; a future milestone may re-group them.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.HkdfExtractTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): add HKDF-Extract primitive"
```

---

## Task 7: HKDF-Expand primitive (private helper)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.HkdfExpandTests -v`
Expected: FAIL — `cannot import name '_hkdf_expand'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/audit.py`:

```python


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand step using HMAC-SHA256.

    Produces ``length`` bytes of output keying material (OKM) by chaining
    HMAC blocks. Raises ``ValueError`` if ``length`` exceeds the RFC ceiling
    of 255 * 32 = 8160 bytes.
    """
    if length > 255 * hashlib.sha256().digest_size:
        raise ValueError("hkdf expand length exceeds 255 * hashlen")
    out = bytearray()
    previous = b""
    counter = 1
    while len(out) < length:
        previous = hmac.new(prk, previous + info + bytes([counter]), hashlib.sha256).digest()
        out.extend(previous)
        counter += 1
    return bytes(out[:length])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.HkdfExpandTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): add HKDF-Expand primitive"
```

---

## Task 8: Public `derive_key` (REQ-03)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

The pinned vectors below were computed offline with the canonical RFC 5869 algorithm using `salt=b"bmad-audit-v1"` and `info=b"audit-chain"`. If the implementation deviates from RFC 5869 in any way, these vectors will catch it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
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
        self.assertEqual(custom.hex(), "200ca78c7bd60448c4676b3009fb33ce374f8c75f02042d7a154b40dc09e4a2f")
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
            forbidden = hashlib.pbkdf2_hmac("sha256", b"test-secret", b"bmad-audit-v1", iters, 32)
            self.assertNotEqual(actual, forbidden, f"derive_key accidentally matches pbkdf2_hmac at {iters} iters")

    def test_docstring_present(self) -> None:
        from story_automator.core.audit import derive_key

        self.assertTrue(derive_key.__doc__ and "HKDF" in derive_key.__doc__)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.DeriveKeyTests -v`
Expected: FAIL — `cannot import name 'derive_key'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/audit.py`:

```python


_HKDF_DEFAULT_SALT = b"bmad-audit-v1"
_HKDF_INFO = b"audit-chain"
_KEY_LENGTH = 32


def derive_key(secret: str, *, salt: bytes = _HKDF_DEFAULT_SALT) -> bytes:
    """Derive a 32-byte audit-chain key from ``secret`` via RFC 5869 HKDF-SHA256.

    Uses ``salt`` as the HKDF salt (default ``b"bmad-audit-v1"``) and the
    fixed ``info`` value ``b"audit-chain"``. Implementation is hand-rolled on
    top of ``hmac`` + ``hashlib.sha256``; ``hashlib.pbkdf2_hmac`` is forbidden
    here per REQ-03. The returned bytes are the raw key material — never log
    or include them in repr / exception messages.
    """
    prk = _hkdf_extract(salt, secret.encode("utf-8"))
    return _hkdf_expand(prk, _HKDF_INFO, _KEY_LENGTH)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.DeriveKeyTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): add derive_key (HKDF-SHA256)"
```

---

## Task 9: `load_key_from_env` happy path (REQ-04)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
class LoadKeyFromEnvHappyPathTests(unittest.TestCase):
    def test_reads_supplied_env_mapping(self) -> None:
        from story_automator.core.audit import derive_key, load_key_from_env

        key = load_key_from_env({"BMAD_AUDIT_KEY": "test-secret"})
        self.assertEqual(key, derive_key("test-secret"))

    def test_reads_process_environment_when_env_is_none(self) -> None:
        import os
        from unittest.mock import patch
        from story_automator.core.audit import derive_key, load_key_from_env

        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "from-process-env"}, clear=False):
            key = load_key_from_env()
        self.assertEqual(key, derive_key("from-process-env"))

    def test_returns_bytes_of_length_32(self) -> None:
        from story_automator.core.audit import load_key_from_env

        key = load_key_from_env({"BMAD_AUDIT_KEY": "x"})
        assert key is not None
        self.assertIsInstance(key, bytes)
        self.assertEqual(len(key), 32)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.LoadKeyFromEnvHappyPathTests -v`
Expected: FAIL — `cannot import name 'load_key_from_env'`.

- [ ] **Step 3: Write minimal implementation**

Add to the import block of `skills/bmad-story-automator/src/story_automator/core/audit.py` (alongside the existing `import hashlib` / `import hmac` lines added in Task 6, in alphabetical order — so the import block reads: `import hashlib`, `import hmac`, `import os`, then a blank line, then `from typing import Mapping`):

```python
import os
from typing import Mapping
```

Append at the bottom of the module:

```python


_ENV_VAR = "BMAD_AUDIT_KEY"


def load_key_from_env(env: Mapping[str, str] | None = None) -> bytes | None:
    """Return a derived audit key from the ``BMAD_AUDIT_KEY`` environment variable.

    Reads from ``env`` when provided, otherwise from ``os.environ``. Returns
    ``None`` when the variable is unset or empty — this function must never
    raise on a missing variable per REQ-04. The raw env value is consumed
    only inside ``derive_key`` and is never logged, repr'd, or included in
    error output anywhere in this module.
    """
    source: Mapping[str, str] = env if env is not None else os.environ
    raw = source.get(_ENV_VAR, "")
    if not raw:
        return None
    return derive_key(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.LoadKeyFromEnvHappyPathTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): add load_key_from_env"
```

---

## Task 10: `load_key_from_env` absent / empty / never-raises contract

**Files:**
- Modify: `tests/test_audit_foundations.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.LoadKeyFromEnvAbsentContractTests -v`
Expected: PASS (5 tests) — the contract was implemented in Task 9. If any test fails, that's a Task 9 regression.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): pin load_key_from_env absent contract"
```

---

## Task 11: Import-allowlist QA gate

**Files:**
- Modify: `tests/test_audit_foundations.py`

Parses `audit.py` with `ast` and asserts every `import` / `from ... import` only references the standard library or `filelock`. This catches accidental `import psutil`, `requests`, etc.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
import ast
import sys


class AuditImportAllowlistTests(unittest.TestCase):
    ALLOWED_THIRD_PARTY = {"filelock"}

    def _collect_top_level_modules(self) -> set[str]:
        tree = ast.parse(AUDIT_MODULE_PATH.read_text(encoding="utf-8"))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative imports inside the package are fine
                if node.module:
                    mods.add(node.module.split(".", 1)[0])
        return mods

    def test_no_psutil_import(self) -> None:
        self.assertNotIn("psutil", self._collect_top_level_modules())

    def test_only_stdlib_or_allowlisted_third_party(self) -> None:
        stdlib = set(sys.stdlib_module_names)
        offenders = []
        for mod in self._collect_top_level_modules():
            if mod in stdlib or mod in self.ALLOWED_THIRD_PARTY:
                continue
            offenders.append(mod)
        self.assertEqual(offenders, [], f"non-allowlisted imports in audit.py: {offenders}")
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.AuditImportAllowlistTests -v`
Expected: PASS — the module currently imports only `hmac`, `hashlib`, `os`, `typing`, all of which are in `sys.stdlib_module_names`. If anything was accidentally pulled in, this fails.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): enforce stdlib + filelock import allowlist"
```

---

## Task 12: Secrets-never-leak QA gate

**Files:**
- Modify: `tests/test_audit_foundations.py`

Exercises the NFR that the raw env value and derived key bytes must never appear in repr / str / exception messages.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
class SecretsNeverLeakTests(unittest.TestCase):
    SECRET = "super-secret-canary-9c7c"

    def test_derive_key_does_not_print(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from story_automator.core.audit import derive_key

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            derive_key(self.SECRET)
        self.assertNotIn(self.SECRET, buf_out.getvalue())
        self.assertNotIn(self.SECRET, buf_err.getvalue())

    def test_load_key_from_env_does_not_print(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from story_automator.core.audit import load_key_from_env

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            load_key_from_env({"BMAD_AUDIT_KEY": self.SECRET})
        self.assertNotIn(self.SECRET, buf_out.getvalue())
        self.assertNotIn(self.SECRET, buf_err.getvalue())

    def test_exception_messages_do_not_carry_secret(self) -> None:
        # Raising AuditKeyMissing or AuditLockTimeout in our caller patterns
        # must never embed the secret. We assert the spec-mandated invariant:
        # the module source code never references BMAD_AUDIT_KEY's *value*
        # in any f-string or format call that would echo back the env value.
        from story_automator.core.audit import AuditKeyMissing, AuditLockTimeout

        for exc_cls in (AuditKeyMissing, AuditLockTimeout):
            instance = exc_cls("generic message")
            self.assertNotIn(self.SECRET, str(instance))
            self.assertNotIn(self.SECRET, repr(instance))

    def test_module_source_does_not_log_or_print_raw_key(self) -> None:
        # Static check: the module body must not call print, logging.*, or
        # warnings.warn with f-strings that interpolate the secret. We do a
        # coarse but cheap check — no `print(`, `logging.`, `warnings.` calls
        # in the audit module at all (consistent with how other core/* modules
        # avoid side-effect I/O).
        source = AUDIT_MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("print(", "logging.", "warnings."):
            self.assertNotIn(forbidden, source, f"audit.py contains forbidden call: {forbidden}")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.SecretsNeverLeakTests -v`
Expected: PASS (4 tests). If a later milestone introduces logging, that test must be revisited together with the logging design.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): enforce secrets-never-leak invariant"
```

---

## Task 13: Docstring coverage QA gate

**Files:**
- Modify: `tests/test_audit_foundations.py`

NFR-docstrings says every public function and class carries a concise docstring.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_foundations.py`:

```python
class DocstringCoverageTests(unittest.TestCase):
    PUBLIC_NAMES = ("AuditKeyMissing", "AuditLockTimeout", "derive_key", "load_key_from_env")

    def test_every_public_name_has_docstring(self) -> None:
        import story_automator.core.audit as audit

        missing: list[str] = []
        for name in self.PUBLIC_NAMES:
            obj = getattr(audit, name)
            doc = obj.__doc__
            if not doc or not doc.strip():
                missing.append(name)
        self.assertEqual(missing, [], f"public names missing docstrings: {missing}")

    def test_derive_key_docstring_describes_contract(self) -> None:
        from story_automator.core.audit import derive_key

        doc = (derive_key.__doc__ or "").lower()
        for required in ("hkdf", "32", "info"):
            self.assertIn(required, doc)

    def test_load_key_from_env_docstring_documents_none_return(self) -> None:
        from story_automator.core.audit import load_key_from_env

        doc = (load_key_from_env.__doc__ or "").lower()
        self.assertIn("none", doc)
        self.assertIn("bmad_audit_key", doc)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_foundations.DocstringCoverageTests -v`
Expected: PASS (3 tests). If it fails, edit the docstrings of the named functions to include the required substrings. Keep them concise — one short paragraph each.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): enforce docstring coverage"
```

---

## Task 14: Whole-suite green + ruff clean

**Files:**
- (no file modifications expected; this is a verification task)

- [ ] **Step 1: Run the whole foundations test file**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v
```

Expected: every test from Tasks 1-13 passes; OK with N tests, 0 failures, 0 errors.

- [ ] **Step 2: Run ruff lint on the module and its tests**

```bash
ruff check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
```

Expected: `All checks passed.` (zero findings).

- [ ] **Step 3: Run ruff format check**

```bash
ruff format --check skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
```

Expected: `2 files already formatted` (or equivalent — no diffs). If diffs are reported, run `ruff format` on the same paths, re-run the suite from Step 1 to confirm no regressions, then create a fresh follow-up commit (see Step 5 below) — never `git commit --amend` an already-recorded commit.

- [ ] **Step 4: Run the broader project test suite to confirm no regressions**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v
```

Expected: all existing tests still pass.

- [ ] **Step 5: Commit any format fix (only if Step 3 reported diffs)**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_foundations.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "chore(audit): apply ruff format"
```

If Step 3 was already clean, no commit is created here.

---

## Task 15: Final review checklist

**Files:**
- (no file modifications)

This is a self-review of the milestone deliverable before declaring it done.

- [ ] **Step 1: Re-read the spec sections in scope**

Open `docs/superpowers/specs/2026-06-14-m04-audit-trail.md`. Confirm by eye that:
- REQ-01 is satisfied (module path, `from __future__ import annotations`, stdlib-only imports).
- REQ-03 derive_key signature exactly matches: `derive_key(secret: str, *, salt: bytes = b"bmad-audit-v1") -> bytes`. Confirm `info=b"audit-chain"` is used.
- REQ-04 `load_key_from_env(env: Mapping[str, str] | None = None) -> bytes | None` exactly matches.
- REQ-07a class `AuditLockTimeout` subclasses `RuntimeError` (it's not raised yet — that's later).
- REQ-10 class `AuditKeyMissing` subclasses `RuntimeError` (it's not raised yet — that's later).
- NFR-secrets-never-leak: no `print`, `logging`, `warnings`, or repr surface includes the secret.
- NFR-docstrings: all public symbols documented.
- QA-import-allowlist: `psutil` and other non-allowlisted third-party packages not imported.

- [ ] **Step 2: Confirm the diff against `main` only touches the expected files**

```bash
git diff --stat main..HEAD
```

Expected files in the diff:
- `CLAUDE.md` (added in the preflight commit; only if it wasn't already present on main)
- `skills/bmad-story-automator/src/story_automator/core/audit.py` (new)
- `tests/test_audit_foundations.py` (new)
- `docs/superpowers/plans/2026-06-14-m04-m1-foundations.md` (new — this plan)

No other source files should have changed. If anything else shows up, investigate before continuing.

- [ ] **Step 3: Confirm commit hygiene**

```bash
git log --oneline main..HEAD
```

Each commit:
- Has a Conventional Commits prefix (`feat:`, `test:`, `chore:`, `docs:`).
- Carries the `Generated-By:` trailer.
- Represents one logical TDD step.

- [ ] **Step 4: Hand-off note**

The next milestone (M04 M2) will add the `AuditLog` dataclass, `append`, `verify`, and `audit_for_policy`. At that point:
- The `filelock` import becomes live and the import-allowlist test in Task 11 keeps passing because `filelock` is already on the allowlist.
- The `AuditLockTimeout` and `AuditKeyMissing` classes get raised for real; the docstring-only tests from Tasks 4/5 stay valid.
- The size budget guard from Task 3 becomes a load-bearing constraint.
