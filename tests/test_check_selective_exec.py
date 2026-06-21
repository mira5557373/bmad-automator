from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


class TestSelectTestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "tests"))
        os.makedirs(os.path.join(self.tmp, "src"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _import_fn(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _select_test_files
            return _select_test_files
        finally:
            sys.path.pop(0)

    def test_direct_test_file_selected(self):
        test_file = os.path.join(self.tmp, "tests", "test_foo.py")
        with open(test_file, "w") as f:
            f.write("pass\n")
        fn = self._import_fn()
        result = fn(self.tmp, ["tests/test_foo.py"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], test_file)

    def test_source_maps_to_test(self):
        src_file = os.path.join(self.tmp, "src", "bar.py")
        test_file = os.path.join(self.tmp, "tests", "test_bar.py")
        with open(src_file, "w") as f:
            f.write("pass\n")
        with open(test_file, "w") as f:
            f.write("pass\n")
        fn = self._import_fn()
        result = fn(self.tmp, ["src/bar.py"])
        self.assertEqual(len(result), 1)
        self.assertIn("test_bar.py", result[0])

    def test_no_matching_test_returns_empty(self):
        fn = self._import_fn()
        result = fn(self.tmp, ["src/nonexistent.py"])
        self.assertEqual(result, [])

    def test_multiple_changed_files(self):
        for name in ["test_a.py", "test_b.py"]:
            with open(os.path.join(self.tmp, "tests", name), "w") as f:
                f.write("pass\n")
        fn = self._import_fn()
        result = fn(self.tmp, ["tests/test_a.py", "tests/test_b.py"])
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
