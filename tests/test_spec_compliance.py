from __future__ import annotations

import io
import logging
import sys
import unittest


class ModuleImportContractTests(unittest.TestCase):
    """REQ-16: importable in any order, no import-time side effects beyond
    logging.getLogger(__name__), declares __all__."""

    def test_module_imports_cleanly(self) -> None:
        from story_automator.core import spec_compliance  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import spec_compliance

        self.assertEqual(
            sorted(spec_compliance.__all__),
            sorted(
                [
                    "ComplianceError",
                    "ComplianceReport",
                    "ReqVerdict",
                    "check_compliance",
                ]
            ),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        sys.modules.pop("story_automator.core.spec_compliance", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import spec_compliance  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import spec_compliance

        self.assertIsInstance(spec_compliance.logger, logging.Logger)
        self.assertEqual(
            spec_compliance.logger.name,
            "story_automator.core.spec_compliance",
        )
