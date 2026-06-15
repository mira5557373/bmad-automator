from __future__ import annotations

import importlib
import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports_cleanly(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        self.assertTrue(hasattr(module, "__all__"))

    def test_module_exports_expected_symbols(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        expected = {
            "Channel",
            "GoldenTraceError",
            "MismatchField",
            "TraceDiff",
            "TraceEntry",
            "TraceMismatch",
            "compare_traces",
            "load_golden",
            "serialize_trace",
        }
        self.assertEqual(set(module.__all__), expected)


if __name__ == "__main__":
    unittest.main()
