from __future__ import annotations

import dataclasses
import hashlib
import io
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


class PromptRenderingTests(unittest.TestCase):
    """REQ-11: spec/diff embedded as fenced code blocks, four-letter
    placeholder tokens escaped in the spec only."""

    def test_render_prompt_wraps_spec_in_fenced_block(self) -> None:
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="hello", diff_text="world")
        self.assertIn("## Spec\n\n```text\nhello\n```", out)

    def test_render_prompt_wraps_diff_in_fenced_block(self) -> None:
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="spec body", diff_text="diff body")
        self.assertIn("## Diff\n\n```text\ndiff body\n```", out)

    def test_render_prompt_escapes_four_letter_uppercase_placeholder(self) -> None:
        # REQ-11: {{NAME}} (4-letter uppercase body) must be escaped.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{NAME}}!", diff_text="d")
        self.assertIn("{{ESC:NAME}}", out)
        self.assertNotIn("{{NAME}}", out)

    def test_render_prompt_does_not_escape_three_letter_token(self) -> None:
        # "four-letter" means exactly four — leave others alone.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{HI}}", diff_text="d")
        self.assertIn("{{HI}}", out)
        self.assertNotIn("ESC:HI", out)

    def test_render_prompt_does_not_escape_lowercase_token(self) -> None:
        # Spec says "four-letter" — interpret as uppercase letters
        # (the BMAD template convention). Lowercase identifiers are
        # human prose, not template directives.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{name}}", diff_text="d")
        self.assertIn("{{name}}", out)
        self.assertNotIn("ESC:name", out)

    def test_render_prompt_does_not_escape_diff_tokens(self) -> None:
        # REQ-11 scopes the escape to the spec; diff is verbatim.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="clean", diff_text="diff has {{NAME}}")
        self.assertIn("{{NAME}}", out)
        self.assertNotIn("ESC:NAME", out)

    def test_render_prompt_states_expected_json_shape(self) -> None:
        # The model must be told which JSON envelope to return.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="s", diff_text="d")
        self.assertIn("verdicts", out)
        self.assertIn("model_invocation_ms", out)

    def test_render_prompt_forbids_markdown_fences_in_response(self) -> None:
        # Real claude -p often wraps JSON in ```json fences by default.
        # The prompt must instruct otherwise, else `_parse_envelope`
        # raises ComplianceError on the fenced output. This test pins
        # the contract so a future header edit can't quietly drop the
        # instruction.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="s", diff_text="d")
        self.assertRegex(out, r"no markdown fences")


class EnvelopeParserHappyPathTests(unittest.TestCase):
    """REQ-09: parse the model's JSON envelope into ReqVerdict list."""

    def test_parses_single_verdict(self) -> None:
        from story_automator.core.spec_compliance import _parse_envelope

        payload = (
            '{"verdicts": ['
            '{"req_id": "REQ-01", "status": "implemented", '
            '"evidence": "seen at core/a.py:1", "confidence": 0.9}'
            '], "model_invocation_ms": 4231}'
        )
        verdicts, ms = _parse_envelope(payload)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].req_id, "REQ-01")
        self.assertEqual(verdicts[0].status, "implemented")
        self.assertEqual(verdicts[0].evidence, "seen at core/a.py:1")
        self.assertAlmostEqual(verdicts[0].confidence, 0.9)
        self.assertEqual(ms, 4231)

    def test_coerces_integer_confidence_to_float(self) -> None:
        from story_automator.core.spec_compliance import _parse_envelope

        payload = (
            '{"verdicts": ['
            '{"req_id": "REQ-02", "status": "partial", '
            '"evidence": "", "confidence": 1}'
            '], "model_invocation_ms": 0}'
        )
        verdicts, ms = _parse_envelope(payload)
        self.assertIsInstance(verdicts[0].confidence, float)
        self.assertEqual(verdicts[0].confidence, 1.0)
        self.assertEqual(ms, 0)


class EnvelopeParserErrorTests(unittest.TestCase):
    """REQ-10: parse failure raises ComplianceError, never downgrades."""

    def test_malformed_json_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "not valid JSON"):
            _parse_envelope("{not json")

    def test_non_object_top_level_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "top-level JSON object"):
            _parse_envelope("[]")

    def test_missing_verdicts_key_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "'verdicts'"):
            _parse_envelope('{"model_invocation_ms": 0}')

    def test_missing_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "model_invocation_ms"):
            _parse_envelope('{"verdicts": []}')

    def test_non_list_verdicts_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "'verdicts' must be a"):
            _parse_envelope('{"verdicts": {}, "model_invocation_ms": 0}')

    def test_missing_verdict_field_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        payload = (
            '{"verdicts": [{"req_id": "REQ-01", "status": "implemented", '
            '"evidence": "x"}], "model_invocation_ms": 0}'
        )
        with self.assertRaisesRegex(ComplianceError, "'confidence'"):
            _parse_envelope(payload)

    def test_unknown_status_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        payload = (
            '{"verdicts": [{"req_id": "REQ-01", "status": "maybe", '
            '"evidence": "", "confidence": 0.5}], "model_invocation_ms": 0}'
        )
        with self.assertRaisesRegex(ComplianceError, "status must be one of"):
            _parse_envelope(payload)

    def test_negative_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "non-negative"):
            _parse_envelope('{"verdicts": [], "model_invocation_ms": -1}')

    def test_non_integer_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "model_invocation_ms"):
            _parse_envelope('{"verdicts": [], "model_invocation_ms": "fast"}')

    def test_parser_never_silently_downgrades_to_missing(self) -> None:
        # REQ-10 explicit guarantee: a malformed envelope must NOT be
        # converted into a "missing" verdict. Assert by checking that
        # the parser raises rather than returning a list.
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        try:
            _parse_envelope("not json at all")
        except ComplianceError:
            return
        self.fail(
            "parser silently produced a verdict instead of raising "
            "ComplianceError on unparseable input — REQ-10 forbids that"
        )


def _ok_completed_process(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude", "-p", "..."],
        returncode=0,
        stdout=stdout,
        stderr="",
    )


_SAMPLE_ENVELOPE = (
    '{"verdicts": ['
    '{"req_id": "REQ-01", "status": "implemented", '
    '"evidence": "core/a.py:1", "confidence": 0.9}'
    '], "model_invocation_ms": 4231}'
)


class CheckComplianceHappyPathTests(unittest.TestCase):
    """REQ-09: subprocess.run is invoked, stdout is parsed, report is built."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01 do thing\n", encoding="utf-8")

    def test_returns_compliance_report_with_parsed_verdicts(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceReport,
            check_compliance,
        )

        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(
                spec_path=self.spec,
                diff_text="--- a/x\n+++ b/x\n",
            )

        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(len(report.verdicts), 1)
        self.assertEqual(report.verdicts[0].req_id, "REQ-01")
        self.assertEqual(report.verdicts[0].status, "implemented")
        self.assertEqual(report.model_invocation_ms, 4231)

    def test_spec_path_is_string_form_of_resolved_path(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(report.spec_path, str(self.spec.resolve()))

    def test_diff_sha_is_sha256_of_diff_text(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
        expected_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(spec_path=self.spec, diff_text=diff)
        self.assertEqual(report.diff_sha, expected_sha)

    def test_spec_text_is_read_from_disk_and_embedded_in_prompt(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        self.spec.write_text(
            "# Spec body unique-marker-xyz\n",
            encoding="utf-8",
        )
        captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            captured["args"] = args
            captured["kwargs"] = kwargs
            captured["input"] = kwargs.get("input")
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        with patch("subprocess.run", side_effect=fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")

        prompt = captured["input"]
        assert isinstance(prompt, str)
        self.assertIn("unique-marker-xyz", prompt)
        self.assertIn("```text\n", prompt)


class CheckComplianceErrorMatrixTests(unittest.TestCase):
    """REQ-10: non-zero exit, timeout, and parse failure raise
    ComplianceError. Never silently downgrade."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01\n", encoding="utf-8")

    def test_non_zero_exit_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        failed = subprocess.CompletedProcess(
            args=["claude", "-p"],
            returncode=2,
            stdout="",
            stderr="boom",
        )
        with (
            patch("subprocess.run", return_value=failed),
            self.assertRaisesRegex(ComplianceError, "exited 2"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_non_zero_exit_includes_stderr_excerpt(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        failed = subprocess.CompletedProcess(
            args=["claude", "-p"],
            returncode=1,
            stdout="",
            stderr="auth failed: please login",
        )
        with patch("subprocess.run", return_value=failed):
            try:
                check_compliance(spec_path=self.spec, diff_text="d")
            except ComplianceError as exc:
                self.assertIn("auth failed", str(exc))
            else:
                self.fail("expected ComplianceError")

    def test_timeout_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        def fake_run(*args: object, **kwargs: object) -> object:
            raise subprocess.TimeoutExpired(
                cmd=["claude", "-p"],
                timeout=120,
            )

        with (
            patch("subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(ComplianceError, "timed out"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_unparseable_stdout_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        ok_but_bad = subprocess.CompletedProcess(
            args=["claude", "-p"],
            returncode=0,
            stdout="not json at all",
            stderr="",
        )
        with (
            patch("subprocess.run", return_value=ok_but_bad),
            self.assertRaisesRegex(ComplianceError, "not valid JSON"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_parse_failure_never_downgrades_to_missing_verdict(self) -> None:
        # REQ-10 explicit guarantee. We verified _parse_envelope in
        # Task 6; here we verify the public surface honours the same.
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        ok_but_bad = subprocess.CompletedProcess(
            args=["claude", "-p"],
            returncode=0,
            stdout='{"unrelated": "shape"}',
            stderr="",
        )
        with patch("subprocess.run", return_value=ok_but_bad):
            try:
                check_compliance(spec_path=self.spec, diff_text="d")
            except ComplianceError:
                return
        self.fail(
            "check_compliance silently produced a report instead of "
            "raising on unparseable envelope — REQ-10 forbids that"
        )

    def test_timeout_propagates_configured_timeout_seconds(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            captured.update(kwargs)
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        with patch("subprocess.run", side_effect=fake_run):
            check_compliance(
                spec_path=self.spec,
                diff_text="d",
                timeout_s=7,
            )
        self.assertEqual(captured.get("timeout"), 7)


class SubprocessInvocationShapeTests(unittest.TestCase):
    """NFR: list args, never shell=True, caller-supplied cwd defaulting
    to Path.cwd(), LANG=C.UTF-8 propagated in child env."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01\n", encoding="utf-8")
        self.captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            self.captured["args"] = args
            self.captured.update(kwargs)
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        self._fake_run = fake_run

    def test_subprocess_args_are_list_not_string(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        positional = self.captured["args"]
        assert isinstance(positional, tuple)
        self.assertIsInstance(positional[0], list)
        self.assertEqual(positional[0][0], "claude")
        self.assertIn("-p", positional[0])

    def test_subprocess_never_uses_shell(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        # `shell` MUST NOT be set to True; we accept absent or False.
        self.assertNotEqual(self.captured.get("shell"), True)

    def test_subprocess_uses_check_false_and_captures_text_output(self) -> None:
        # REQ-09 explicit: check=False, text=True, capture_output=True.
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(self.captured.get("check"), False)
        self.assertEqual(self.captured.get("text"), True)
        self.assertEqual(self.captured.get("capture_output"), True)

    def test_cwd_defaults_to_current_working_directory(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(self.captured.get("cwd"), str(Path.cwd()))

    def test_cwd_can_be_overridden_by_caller(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(
                spec_path=self.spec,
                diff_text="d",
                cwd=self.root,
            )
        self.assertEqual(self.captured.get("cwd"), str(self.root))

    def test_env_propagates_lang_c_utf8(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        env = self.captured.get("env")
        self.assertIsInstance(env, dict)
        assert isinstance(env, dict)
        self.assertEqual(env.get("LANG"), "C.UTF-8")
        # PATH must still be present so the child can locate `claude`.
        self.assertIn("PATH", env)

    def test_claude_binary_argument_overrides_executable(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(
                spec_path=self.spec,
                diff_text="d",
                claude_binary="/usr/local/bin/claude",
            )
        positional = self.captured["args"]
        assert isinstance(positional, tuple)
        self.assertEqual(positional[0][0], "/usr/local/bin/claude")
