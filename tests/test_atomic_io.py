from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


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


class HappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_writes_full_contents_to_target(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        write_atomic_text(target, "hello world")

        self.assertEqual(target.read_text(encoding="utf-8"), "hello world")

    def test_overwrites_existing_file(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        target.write_text("old", encoding="utf-8")
        write_atomic_text(target, "new")

        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_writes_unicode_content(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "uni.txt"
        write_atomic_text(target, "héllo — 世界")

        self.assertEqual(target.read_text(encoding="utf-8"), "héllo — 世界")

    def test_no_leftover_tmp_files_in_directory(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        write_atomic_text(target, "payload")

        entries = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(entries, ["out.txt"])

    def test_tmp_file_lives_in_same_directory_as_target(self) -> None:
        # Same-directory siblings are required for os.replace atomicity
        # across filesystems. We assert the implementation hasn't drifted
        # to tempfile.gettempdir() by inspecting an interrupted write.
        from story_automator.core.atomic_io import write_atomic_text
        from unittest.mock import patch

        target = self.dir / "out.txt"
        observed_dirs: list[Path] = []
        real_replace = os.replace

        def spy(src: str, dst: str) -> None:
            observed_dirs.append(Path(src).parent.resolve())
            real_replace(src, dst)

        with patch("story_automator.core.atomic_io.os.replace", side_effect=spy):
            write_atomic_text(target, "payload")

        self.assertEqual(observed_dirs, [self.dir.resolve()])
