# tests/test_portability.py
"""Wave F: cross-platform path handling (forward-slashed relative paths and
OS-independent absolute-glob rejection)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core import runtime_layout
from story_automator.core.artifact_paths import resolve_artifact_glob


class RelativePathSeparatorTests(unittest.TestCase):
    def test_marker_project_entry_is_forward_slashed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            entry = runtime_layout.active_marker_project_entry(str(d))
            # Must never contain a backslash separator, regardless of host OS.
            self.assertNotIn("\\", entry)
            self.assertIn("/", entry)
            self.assertTrue(entry.endswith(runtime_layout.ACTIVE_MARKER_NAME))


class AbsoluteGlobRejectionTests(unittest.TestCase):
    def test_posix_absolute_glob_rejected_even_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                resolve_artifact_glob(str(d), "/tmp/x-*.md")

    def test_backslash_absolute_glob_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                resolve_artifact_glob(str(d), "\\\\server\\share\\x-*.md")

    def test_relative_glob_still_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            artifacts = root / "docs" / "bmad" / "implementation-artifacts"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / "result-1.md").write_text("x", encoding="utf-8")
            # A valid artifacts-relative glob must still resolve cleanly (the
            # broadened absolute check must not over-reject relative patterns).
            resolved = resolve_artifact_glob(
                str(root), "docs/bmad/implementation-artifacts/result-*.md"
            )
            self.assertIsNotNone(resolved)


if __name__ == "__main__":
    unittest.main()
