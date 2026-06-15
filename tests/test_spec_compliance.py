from __future__ import annotations

import dataclasses
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


class ComplianceErrorTests(unittest.TestCase):
    """REQ-10: module-level Exception subclass."""

    def test_compliance_error_is_exception_subclass(self) -> None:
        from story_automator.core.spec_compliance import ComplianceError

        self.assertTrue(issubclass(ComplianceError, Exception))

    def test_compliance_error_carries_message(self) -> None:
        from story_automator.core.spec_compliance import ComplianceError

        err = ComplianceError("subprocess exited 2")
        self.assertEqual(str(err), "subprocess exited 2")


class ReqVerdictDataclassTests(unittest.TestCase):
    """REQ-07: frozen kw_only @dataclass with four fields."""

    def test_req_verdict_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        self.assertTrue(dataclasses.is_dataclass(ReqVerdict))
        params = ReqVerdict.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_req_verdict_field_names(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        names = sorted(f.name for f in dataclasses.fields(ReqVerdict))
        self.assertEqual(
            names,
            ["confidence", "evidence", "req_id", "status"],
        )

    def test_req_verdict_construction_requires_keyword_args(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        with self.assertRaises(TypeError):
            ReqVerdict("REQ-01", "implemented", "", 0.9)  # type: ignore[misc]

    def test_req_verdict_instances_are_immutable(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        v = ReqVerdict(
            req_id="REQ-01",
            status="implemented",
            evidence="seen",
            confidence=0.9,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            v.status = "missing"  # type: ignore[misc]

    def test_req_verdict_does_not_subclass_other_dataclasses(self) -> None:
        # NFR: dataclasses must not subclass other dataclasses.
        from story_automator.core.spec_compliance import ReqVerdict

        ancestors = [
            base
            for base in ReqVerdict.__mro__
            if base is not ReqVerdict and base is not object
        ]
        for base in ancestors:
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"ReqVerdict unexpectedly inherits from dataclass {base!r}",
            )


class ComplianceReportDataclassTests(unittest.TestCase):
    """REQ-08: frozen kw_only @dataclass with four fields."""

    def test_compliance_report_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.spec_compliance import ComplianceReport

        self.assertTrue(dataclasses.is_dataclass(ComplianceReport))
        params = ComplianceReport.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_compliance_report_field_names(self) -> None:
        from story_automator.core.spec_compliance import ComplianceReport

        names = sorted(f.name for f in dataclasses.fields(ComplianceReport))
        self.assertEqual(
            names,
            ["diff_sha", "model_invocation_ms", "spec_path", "verdicts"],
        )

    def test_compliance_report_construction(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceReport,
            ReqVerdict,
        )

        v = ReqVerdict(
            req_id="REQ-01",
            status="implemented",
            evidence="seen",
            confidence=0.9,
        )
        r = ComplianceReport(
            verdicts=[v],
            spec_path="docs/foo.md",
            diff_sha="deadbeef",
            model_invocation_ms=4231,
        )
        self.assertEqual(r.verdicts, [v])
        self.assertEqual(r.spec_path, "docs/foo.md")
        self.assertEqual(r.diff_sha, "deadbeef")
        self.assertEqual(r.model_invocation_ms, 4231)
