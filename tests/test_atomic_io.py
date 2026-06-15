from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import atomic_io  # noqa: F401

    def test_exposes_atomic_write_retry_exhausted(self) -> None:
        from story_automator.core.atomic_io import AtomicWriteRetryExhausted

        # Subclass PermissionError so REQ-04 ("raise the final PermissionError
        # if all retries fail") is satisfied while still being a typed
        # exception per the observability NFR. PermissionError is itself
        # a subclass of OSError.
        self.assertTrue(issubclass(AtomicWriteRetryExhausted, PermissionError))
        self.assertTrue(issubclass(AtomicWriteRetryExhausted, OSError))

    def test_exposes_write_atomic_text(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        self.assertTrue(callable(write_atomic_text))
