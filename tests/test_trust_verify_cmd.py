from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from dataclasses import dataclass
from pathlib import Path

from story_automator.core.spec_compliance import ComplianceError


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a
    string buffer and return ``(exit_code, parsed_json)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


# --- Lightweight stand-ins mirroring the core dataclass attributes the ---
# --- command's serializers read. Avoids spawning ``claude -p``.        ---


@dataclass
class _StubGap:
    file_path: str = "core/x.py"
    line: int = 1
    symbol: str = "sym"
    description: str = "desc"
    severity: str = "major"


@dataclass
class _StubStatus:
    gap: _StubGap
    path_exists: bool = True
    line_in_range: bool = True
    symbol_present: bool = True
    confidence: float = 0.95
    notes: tuple = ()


@dataclass
class _StubReport1:
    statuses: list
    overall_confidence: float
    validated_at: str = "2026-06-15T12:00:00Z"


@dataclass
class _StubVerdict:
    req_id: str
    status: str
    evidence: str = "ev"
    confidence: float = 0.9


@dataclass
class _StubReport2:
    verdicts: list
    spec_path: str = "spec.md"
    diff_sha: str = "0" * 64
    model_invocation_ms: int = 1234


@dataclass
class _StubEntry:
    req_id: str
    existing_test_path: str | None
    created_test_path: str | None
    action: str


def _report1(confidence: float = 0.95) -> _StubReport1:
    return _StubReport1(
        statuses=[_StubStatus(gap=_StubGap())],
        overall_confidence=confidence,
    )


def _report2(statuses=("implemented",)) -> _StubReport2:
    return _StubReport2(
        verdicts=[
            _StubVerdict(req_id=f"REQ-0{i + 1}", status=s)
            for i, s in enumerate(statuses)
        ]
    )


def _plan(actions=("found",)) -> list:
    out = []
    for i, action in enumerate(actions):
        req = f"REQ-0{i + 1}"
        if action == "found":
            out.append(
                _StubEntry(req, f"tests/test_compliance_{req}.py", None, "found")
            )
        else:
            out.append(
                _StubEntry(req, None, f"tests/test_compliance_{req}.py", action)
            )
    return out


def _patch_chain(
    *,
    report1: _StubReport1,
    report2: _StubReport2,
    plan: list,
):
    """Patch the three core entry points imported into the command module so
    the chain runs without filesystem source-tree checks or a subprocess."""
    from story_automator.commands import trust_verify as tv

    return (
        mock.patch.object(tv, "parse_gap_list", return_value=[]),
        mock.patch.object(tv, "validate_gaps", return_value=report1),
        mock.patch.object(tv, "check_compliance", return_value=report2),
        mock.patch.object(tv, "plan_feature_tests", return_value=plan),
    )


def _run_chain(
    args: list[str],
    *,
    report1: _StubReport1,
    report2: _StubReport2,
    plan: list,
):
    p1, p2, p3, p4 = _patch_chain(report1=report1, report2=report2, plan=plan)
    from story_automator.commands.trust_verify import cmd_trust_verify

    with p1, p2, p3, p4:
        return _capture(cmd_trust_verify, args)


def _write_inputs(tmp: str) -> tuple[str, str, str]:
    """Create gaps/spec/diff files (content is irrelevant when the chain is
    patched, but the paths must exist so the read_text calls succeed)."""
    gaps = Path(tmp) / "gaps.json"
    gaps.write_text('{"gaps": []}', encoding="utf-8")
    spec = Path(tmp) / "spec.md"
    spec.write_text("REQ-01\n", encoding="utf-8")
    diff = Path(tmp) / "diff.txt"
    diff.write_text("--- a\n+++ b\n", encoding="utf-8")
    return str(gaps), str(spec), str(diff)


class CmdTrustVerifySurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.trust_verify import (  # noqa: F401
            cmd_trust_verify,
        )

    def test_entry_point_signature_matches_command_protocol(self) -> None:
        """``cmd_trust_verify`` must accept a single ``list[str]`` and return
        an int so the controller can register it as a ``Command`` (cli.py
        dispatch is wired separately and is intentionally NOT exercised here
        to keep this module's two files self-contained)."""
        import inspect

        from story_automator.commands.trust_verify import cmd_trust_verify

        params = list(inspect.signature(cmd_trust_verify).parameters)
        self.assertEqual(len(params), 1)
        code, _ = _capture(cmd_trust_verify, [])
        self.assertIsInstance(code, int)


class CmdTrustVerifyFlagParseTests(unittest.TestCase):
    def test_missing_gaps_returns_structured_error(self) -> None:
        from story_automator.commands.trust_verify import cmd_trust_verify

        code, payload = _capture(cmd_trust_verify, [])
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "missing_gaps")

    def test_missing_spec_returns_structured_error(self) -> None:
        from story_automator.commands.trust_verify import cmd_trust_verify

        code, payload = _capture(cmd_trust_verify, ["--gaps", "g.json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "missing_spec")

    def test_missing_diff_returns_structured_error(self) -> None:
        from story_automator.commands.trust_verify import cmd_trust_verify

        code, payload = _capture(
            cmd_trust_verify, ["--gaps", "g.json", "--spec", "s.md"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "missing_diff")

    def test_gaps_file_not_found(self) -> None:
        from story_automator.commands.trust_verify import cmd_trust_verify

        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope.json")
            code, payload = _capture(
                cmd_trust_verify,
                ["--gaps", missing, "--spec", "s.md", "--diff", "d.txt"],
            )
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "gaps_file_not_found")

    def test_invalid_gaps_json_returns_structured_error(self) -> None:
        from story_automator.commands.trust_verify import cmd_trust_verify

        with tempfile.TemporaryDirectory() as tmp:
            gaps = Path(tmp) / "gaps.json"
            gaps.write_text("{ this is not json", encoding="utf-8")
            code, payload = _capture(
                cmd_trust_verify,
                ["--gaps", str(gaps), "--spec", "s.md", "--diff", "d.txt"],
            )
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "invalid_gaps")
        self.assertIn("detail", payload)


class CmdTrustVerifyDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior_root = os.environ.get("PROJECT_ROOT")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["PROJECT_ROOT"] = self._tmp.name
        self.gaps, self.spec, self.diff = _write_inputs(self._tmp.name)
        self.args = [
            "--gaps",
            self.gaps,
            "--spec",
            self.spec,
            "--diff",
            self.diff,
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()
        if self._prior_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._prior_root

    def _result_json(self) -> dict:
        out_path = (
            Path(self._tmp.name) / ".claude" / "trust-verify-output" / "result.json"
        )
        return json.loads(out_path.read_text(encoding="utf-8"))

    def test_pass_when_all_clean(self) -> None:
        code, payload = _run_chain(
            self.args,
            report1=_report1(0.95),
            report2=_report2(("implemented",)),
            plan=_plan(("found",)),
        )
        self.assertEqual(code, 0)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("decision"), "pass")
        self.assertEqual(set(self._result_json()), {
            "layer1",
            "layer2",
            "layer3",
            "decision",
            "verified_at",
        })

    def test_warn_on_low_layer1_confidence(self) -> None:
        code, payload = _run_chain(
            self.args,
            report1=_report1(0.5),
            report2=_report2(("implemented",)),
            plan=_plan(("found",)),
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload.get("decision"), "warn")

    def test_warn_on_layer3_created(self) -> None:
        code, payload = _run_chain(
            self.args,
            report1=_report1(0.95),
            report2=_report2(("implemented",)),
            plan=_plan(("created",)),
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload.get("decision"), "warn")

    def test_block_on_layer2_missing_verdict(self) -> None:
        code, payload = _run_chain(
            self.args,
            report1=_report1(0.95),
            report2=_report2(("implemented", "missing")),
            plan=_plan(("found",)),
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload.get("decision"), "block")

    def test_block_precedence_over_warn(self) -> None:
        code, payload = _run_chain(
            self.args,
            report1=_report1(0.5),
            report2=_report2(("missing",)),
            plan=_plan(("created",)),
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload.get("decision"), "block")

    def test_compliance_error_is_error(self) -> None:
        from story_automator.commands import trust_verify as tv
        from story_automator.commands.trust_verify import cmd_trust_verify

        with (
            mock.patch.object(tv, "parse_gap_list", return_value=[]),
            mock.patch.object(tv, "validate_gaps", return_value=_report1(0.95)),
            mock.patch.object(
                tv,
                "check_compliance",
                side_effect=ComplianceError("`claude -p` exited 1"),
            ),
        ):
            code, payload = _capture(cmd_trust_verify, self.args)
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "layer2_failed")
        self.assertIn("exit", payload.get("detail", "").lower())
        out_path = (
            Path(self._tmp.name) / ".claude" / "trust-verify-output" / "result.json"
        )
        self.assertFalse(out_path.exists())

    def test_result_json_matches_fixture_key_set(self) -> None:
        _run_chain(
            self.args,
            report1=_report1(0.95),
            report2=_report2(("implemented",)),
            plan=_plan(("created",)),
        )
        data = self._result_json()
        self.assertEqual(set(data), {
            "layer1",
            "layer2",
            "layer3",
            "decision",
            "verified_at",
        })
        self.assertEqual(
            set(data["layer1"]),
            {"statuses", "overall_confidence", "validated_at"},
        )
        self.assertEqual(
            set(data["layer2"]),
            {"verdicts", "spec_path", "diff_sha", "model_invocation_ms"},
        )
        for entry in data["layer3"]:
            self.assertEqual(
                set(entry),
                {"req_id", "existing_test_path", "created_test_path", "action"},
            )
        self.assertRegex(
            data["verified_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )


if __name__ == "__main__":
    unittest.main()
