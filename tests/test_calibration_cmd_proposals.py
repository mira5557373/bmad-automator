"""Tests for the C5 ``calibration`` subcommand surface (spec §7.1 AC-C-01..C-08).

The bare ``story-automator calibration`` invocation is pinned BYTE-IDENTICAL
to ``tests/fixtures/calibration_bare_v1.expected.json`` so the M08 output
shape cannot regress while the C5 subcommands are added on top.

Every other test exercises one of the five subcommand handlers
(``propose`` / ``list-proposals`` / ``show`` / ``apply`` / ``reject``)
against a tmpdir-isolated project root with a synthesized telemetry
fixture and a synthesized ``gate_rules``-style target module. The
production source tree is never mutated.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from story_automator.commands.calibration_cmd import (
    _render_diff,
    cmd_calibration,
)
from story_automator.core import common as common_mod
from story_automator.core.evidence_io import persist_gate_file
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.innovation import threshold_apply as _apply_mod
from story_automator.core.innovation.threshold_decisions import (
    calibration_dir,
    record_decision,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_BARE_GOLDEN = _FIXTURE_DIR / "calibration_bare_v1.expected.json"

_FROZEN_GENERATED_AT = "2026-06-23T12:00:00Z"
_GOLDEN_LEDGER_NAME = "events.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cmd(args: list[str]) -> tuple[int, str]:
    """Invoke ``cmd_calibration``; return ``(exit_code, raw_stdout)``."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_calibration(args)
    return code, buf.getvalue()


def _build_fake_gate_rules(tmp: Path, *, package_name: str, p3_required: int = 70) -> str:
    """Drop a synthetic ``gate_rules.py`` under ``tmp`` and return its
    fully-qualified module name. Mirrors the threshold_apply tests."""
    pkg = tmp / package_name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    body = (
        '"""Synthetic gate_rules for CLI tests."""\n'
        "from __future__ import annotations\n"
        "\n"
        "PRIORITY_THRESHOLDS: dict[str, tuple[int, int]] = {\n"
        '    "P0": (100, 100),\n'
        '    "P1": (95, 90),\n'
        '    "P2": (85, 80),\n'
        f'    "P3": ({p3_required}, 0),\n'
        "}\n"
    )
    (pkg / "gate_rules.py").write_text(body, encoding="utf-8")
    if str(tmp) not in sys.path:
        sys.path.insert(0, str(tmp))
    qual = f"{package_name}.gate_rules"
    sys.modules.pop(qual, None)
    sys.modules.pop(package_name, None)
    importlib.invalidate_caches()
    return qual


def _write_gate_verdict(
    project_root: Path,
    gate_id: str,
    *,
    priority: str = "P3",
    coverage_pct: float = 50.0,
    overall: str = "PASS",
) -> dict[str, Any]:
    """Persist a schema-valid gate file under
    ``_bmad/gate/verdicts/<gate_id>.json`` via :func:`persist_gate_file`."""
    cat: dict[str, Any] = {
        "verdict": overall,
        "required": {"priority": priority},
        "actual": {"coverage_pct": coverage_pct},
    }
    gate = make_gate_file(
        gate_id=gate_id,
        target={"kind": "story", "id": f"E1.S{gate_id[-2:]}"},
        commit_sha="cafefeed" + gate_id.replace("-", "")[-6:].rjust(6, "0"),
        profile={"id": "default", "version": 1, "hash": "11223344"},
        factory_version="0.1.0",
        categories={"correctness": cat},
        overall=overall,
    )
    persist_gate_file(project_root, gate)
    return gate


def _make_proposal_on_disk(
    *,
    project_root: Path,
    target_module: str,
    proposal_id: str = "0123456789abcdef",
    confirm_slug: str = "deadbeef",
    current_value: int = 70,
    proposed_value: int = 65,
    created_at_iso: str = "2026-06-23T17:42:11Z",
    selector: dict[str, Any] | None = None,
) -> Path:
    if selector is None:
        selector = {"kind": "dict_tuple_element", "key": "P3", "index": 0}
    proposals_dir = project_root / "_bmad" / "calibration" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "target_module": target_module,
        "target_symbol": "PRIORITY_THRESHOLDS",
        "target_category": "correctness",
        "target_file_hint": "",
        "selector": selector,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "delta": proposed_value - current_value,
        "rationale": "test rationale",
        "evidence_window": ["g1", "g2", "g3", "g4", "g5"],
        "created_at_iso": created_at_iso,
        "confirm_slug": confirm_slug,
        "proposer_config": {
            "min_evidence_window": 5,
            "target_pass_rate_band": [0.80, 0.95],
            "max_delta_pct": 5,
            "consecutive_runs": 3,
            "enable_drift_band_proposals": False,
            "ttl_hours": 168,
        },
    }
    path = proposals_dir / f"{proposal_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Bare invocation — byte-identical golden fixture
# ---------------------------------------------------------------------------


class CalibrationBareGoldenFixtureTests(unittest.TestCase):
    """AC-C-01 — bare ``calibration`` byte-equal to pre-C5 surface."""

    def test_bare_invocation_byte_identical(self) -> None:
        # The golden fixture is the raw stdout the bare invocation
        # emitted at the moment the C5 series was authored. Any field
        # reorder / new field added to the bare path will break this.
        self.assertTrue(_BARE_GOLDEN.is_file(), f"golden fixture missing: {_BARE_GOLDEN}")
        golden = _BARE_GOLDEN.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / _GOLDEN_LEDGER_NAME
            # Empty ledger ⇒ deterministic shape (no entries).
            ledger.write_text("", encoding="utf-8")
            with mock.patch.object(common_mod, "iso_now", return_value=_FROZEN_GENERATED_AT):
                # The calibration module imports iso_now via the bare
                # ``from .common import iso_now`` form, so patch it on
                # the consumer too.
                import story_automator.core.calibration as cal_mod

                with mock.patch.object(cal_mod, "iso_now", return_value=_FROZEN_GENERATED_AT):
                    code, raw = _run_cmd(["--events", str(ledger)])
        self.assertEqual(code, 0)
        # Render the golden template with the tmp ledger path so we
        # compare byte-equal modulo the unavoidable absolute path.
        expected = golden.replace("__LEDGER_PATH__", str(ledger))
        self.assertEqual(raw, expected)


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------


class CalibrationProposeTests(unittest.TestCase):
    """AC-C-02 — ``propose`` returns id + slug at the top level."""

    def test_propose_emits_id_and_slug_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            qual = _build_fake_gate_rules(tmp_path, package_name="fakepkg_prop")
            project_root = tmp_path / "project"
            project_root.mkdir()
            # Coverage well below the P3 threshold (70) so the
            # tail-of-window is all FAIL and the proposer ratchets
            # ``required_pct`` down (spec §3 below-band branch).
            for idx in range(6):
                _write_gate_verdict(
                    project_root,
                    f"g{idx:03d}",
                    coverage_pct=20.0,
                    overall="FAIL",
                )
            with mock.patch(
                "story_automator.commands.calibration_cmd.ThresholdProposer"
            ) as patched:
                from story_automator.core.innovation.threshold_proposer import (
                    ThresholdProposer as _Real,
                )

                patched.side_effect = lambda **kw: _Real(target_module=qual, **kw)
                code, raw = _run_cmd(
                    [
                        "propose",
                        "--project-root",
                        str(project_root),
                        "--window",
                        "5",
                    ]
                )
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertIs(parsed["ok"], True)
        self.assertIn("proposal_id", parsed)
        self.assertIn("confirm_slug", parsed)
        # Slug is 8 hex chars per the proposer's confirm-slug contract.
        self.assertEqual(len(parsed["confirm_slug"]), 8)
        self.assertIsNotNone(parsed["proposal"])

    def test_propose_no_evidence_returns_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            code, raw = _run_cmd(["propose", "--project-root", str(project_root)])
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertEqual(parsed, {"ok": True, "proposal": None})


# ---------------------------------------------------------------------------
# list-proposals
# ---------------------------------------------------------------------------


class CalibrationListTests(unittest.TestCase):
    """AC-C-03 — empty listing exits 0; sort + --include-failed semantics."""

    def test_list_empty_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(["list-proposals", "--project-root", str(project_root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw), {"ok": True, "proposals": []})

    def test_list_excludes_confirm_failed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _make_proposal_on_disk(
                project_root=project_root,
                target_module="story_automator.core.gate_rules",
                proposal_id="aaaaaaaaaaaaaaaa",
            )
            calibration_dir(project_root, create=True)
            record_decision(
                project_root,
                "aaaaaaaaaaaaaaaa",
                "confirm_failed",
                "local",
                "",
            )
            code_default, raw_default = _run_cmd(
                ["list-proposals", "--project-root", str(project_root)]
            )
            code_failed, raw_failed = _run_cmd(
                ["list-proposals", "--project-root", str(project_root), "--include-failed"]
            )
        self.assertEqual(code_default, 0)
        self.assertEqual(code_failed, 0)
        default_parsed = json.loads(raw_default)
        failed_parsed = json.loads(raw_failed)
        self.assertEqual(default_parsed["proposals"], [])
        self.assertEqual(len(failed_parsed["proposals"]), 1)
        self.assertEqual(failed_parsed["proposals"][0]["latest_decision"], "confirm_failed")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


class CalibrationShowTests(unittest.TestCase):
    """AC-C-04 — show redacts slug by default; --include-slug reveals;
    missing id exits 1 with PROPOSAL_NOT_FOUND."""

    def test_show_redacts_slug_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _make_proposal_on_disk(
                project_root=project_root,
                target_module="story_automator.core.gate_rules",
                proposal_id="bbbbbbbbbbbbbbbb",
                confirm_slug="cafebabe",
            )
            code, raw = _run_cmd(["show", "bbbbbbbbbbbbbbbb", "--project-root", str(project_root)])
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertEqual(parsed["proposal"]["confirm_slug"], "<redacted>")
        self.assertIn("diff", parsed)
        # Diff is bounded ≤7 lines per spec §6.1.
        self.assertLessEqual(parsed["diff"].count("\n") + 1, 7)
        self.assertIsNone(parsed["applied_record"])

    def test_show_include_slug_reveals_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _make_proposal_on_disk(
                project_root=project_root,
                target_module="story_automator.core.gate_rules",
                proposal_id="cccccccccccccccc",
                confirm_slug="cafebabe",
            )
            code, raw = _run_cmd(
                [
                    "show",
                    "cccccccccccccccc",
                    "--include-slug",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertEqual(parsed["proposal"]["confirm_slug"], "cafebabe")

    def test_show_missing_id_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(["show", "deadbeefdeadbeef", "--project-root", str(project_root)])
        self.assertEqual(code, 1)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)
        self.assertEqual(parsed["error"], "PROPOSAL_NOT_FOUND")
        self.assertEqual(parsed["proposal_id"], "deadbeefdeadbeef")

    def test_show_missing_positional_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(["show", "--project-root", str(project_root)])
        self.assertEqual(code, 2)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class CalibrationApplyTests(unittest.TestCase):
    """AC-C-05 — apply happy path, bad-length confirm, missing flag."""

    def test_apply_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            qual = _build_fake_gate_rules(tmp_path, package_name="fakepkg_apply")
            project_root = tmp_path / "project"
            project_root.mkdir()
            _make_proposal_on_disk(
                project_root=project_root,
                target_module=qual,
                proposal_id="1111111111111111",
                confirm_slug="aabbccdd",
                current_value=70,
                proposed_value=65,
            )
            code, raw = _run_cmd(
                [
                    "apply",
                    "--proposal-id",
                    "1111111111111111",
                    "--confirm",
                    "aabbccdd",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertIs(parsed["ok"], True)
        self.assertIs(parsed["applied"], True)
        self.assertIn("target_file", parsed)

    def test_apply_bad_length_confirm_exits_1_with_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            qual = _build_fake_gate_rules(tmp_path, package_name="fakepkg_apply_bad")
            project_root = tmp_path / "project"
            project_root.mkdir()
            _make_proposal_on_disk(
                project_root=project_root,
                target_module=qual,
                proposal_id="2222222222222222",
                confirm_slug="ffeeddcc",
            )
            code, raw = _run_cmd(
                [
                    "apply",
                    "--proposal-id",
                    "2222222222222222",
                    "--confirm",
                    "short",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 1)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)
        self.assertEqual(parsed["error"], "CONFIRM_MISMATCH")
        self.assertIn("hint", parsed)
        self.assertIn("8 hex", parsed["hint"])

    def test_apply_missing_proposal_id_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(
                ["apply", "--confirm", "aabbccdd", "--project-root", str(project_root)]
            )
        self.assertEqual(code, 2)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)
        self.assertIn("proposal-id", parsed["error"])

    def test_apply_missing_confirm_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(
                [
                    "apply",
                    "--proposal-id",
                    "1111111111111111",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 2)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)
        self.assertIn("confirm", parsed["error"])


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


class CalibrationRejectTests(unittest.TestCase):
    """AC-C-06 — reject happy path, missing id, missing flag."""

    def test_reject_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _make_proposal_on_disk(
                project_root=project_root,
                target_module="story_automator.core.gate_rules",
                proposal_id="3333333333333333",
            )
            code, raw = _run_cmd(
                [
                    "reject",
                    "--proposal-id",
                    "3333333333333333",
                    "--reason",
                    "needs more telemetry",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 0)
        parsed = json.loads(raw)
        self.assertIs(parsed["ok"], True)
        self.assertIs(parsed["rejected"], True)

    def test_reject_missing_id_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            code, raw = _run_cmd(
                [
                    "reject",
                    "--reason",
                    "stale",
                    "--project-root",
                    str(project_root),
                ]
            )
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# --help (AC-C-07) + dispatcher polish
# ---------------------------------------------------------------------------


class CalibrationHelpTests(unittest.TestCase):
    """AC-C-07 — ``--help`` lists every subcommand; unknown subcommand → 2."""

    def test_help_lists_all_subcommands(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cmd_calibration(["--help"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        for sub in ("propose", "list-proposals", "show", "apply", "reject"):
            self.assertIn(sub, out)

    def test_unknown_subcommand_exits_2(self) -> None:
        code, raw = _run_cmd(["frobnicate"])
        self.assertEqual(code, 2)
        parsed = json.loads(raw)
        self.assertEqual(parsed["ok"], False)
        self.assertIn("unknown subcommand", parsed["error"])


# ---------------------------------------------------------------------------
# Diff render helper (spec §6.1)
# ---------------------------------------------------------------------------


class RenderDiffTests(unittest.TestCase):
    """Spec §6.1: bounded ASCII LF deterministic unified diff."""

    def test_diff_bounded_to_seven_lines(self) -> None:
        before = "\n".join(f"line {i}" for i in range(20))
        after = "\n".join(f"line {i}" if i != 10 else "CHANGED" for i in range(20))
        out = _render_diff(before, after, lineno=10)
        self.assertLessEqual(len(out.splitlines()), 7)

    def test_diff_is_ascii_and_lf(self) -> None:
        out = _render_diff("alpha", "beta", lineno=1)
        out.encode("ascii")  # must not raise
        self.assertNotIn("\r", out)

    def test_diff_is_deterministic(self) -> None:
        out1 = _render_diff("alpha", "beta", lineno=1)
        out2 = _render_diff("alpha", "beta", lineno=1)
        self.assertEqual(out1, out2)

    def test_diff_truncation_preserves_minus_and_plus_lines(self) -> None:
        """Post-impl review fix: a naive ``[:7]`` slice of unified-diff
        output cuts between the ``-`` removal and the matching ``+``
        addition when the diff exceeds 7 lines, leaving the operator
        seeing only what was removed and never what replaced it.
        Hunk-aware truncation must always preserve BOTH sides.
        """
        before = "\n".join(f"line {i}" for i in range(20))
        after = "\n".join(f"line {i}" if i != 10 else "CHANGED" for i in range(20))
        out = _render_diff(before, after, lineno=10)
        lines = out.splitlines()
        self.assertLessEqual(len(lines), 7, "still bounded to 7 lines")
        # Detect a ``-`` removal AND a matching ``+`` addition. We
        # ignore the file-header pair ``---`` / ``+++`` which always
        # leads unified_diff output.
        change_minus = [
            line for line in lines if line.startswith("-") and not line.startswith("---")
        ]
        change_plus = [
            line for line in lines if line.startswith("+") and not line.startswith("+++")
        ]
        self.assertTrue(
            change_minus and change_plus,
            f"truncated diff must contain BOTH a removal AND an addition; got\n{out}",
        )
        # Specifically the change must reflect ``line 10`` → ``CHANGED``.
        self.assertIn("-line 10", out)
        self.assertIn("+CHANGED", out)


# ---------------------------------------------------------------------------
# Cleanup of sys.modules / sys.path side effects between tests
# ---------------------------------------------------------------------------


class _SysPathCleanupHook:
    """Drop any ``fakepkg_*`` modules from sys.modules / sys.path between
    test classes so a previous test's synthesized target module does not
    leak into another's :func:`importlib.util.find_spec` lookup."""


def tearDownModule() -> None:  # pragma: no cover - cleanup hook
    for mod in list(sys.modules):
        if mod.startswith("fakepkg_"):
            sys.modules.pop(mod, None)
    sys.path[:] = [p for p in sys.path if "fakepkg_" not in p]
    # Defensive: confirm threshold_apply module reference still resolves
    # even after we tear our shim down.
    _ = _apply_mod


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
