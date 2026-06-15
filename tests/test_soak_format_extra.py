# tests/test_soak_format_extra.py
from __future__ import annotations

import contextlib
import io
import re as stdlib_re
import sys
import tempfile
import unittest
from pathlib import Path

# Belt-and-suspenders: make sure the repo root is on sys.path so
# `from scripts.verify_soak_format import main` resolves regardless of
# how the test runner sets PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.test_soak_format import _write_minimal_arm  # noqa: E402


class DeterministicOutputTests(unittest.TestCase):
    def _run_capture(self, root: Path) -> list[str]:
        from scripts.verify_soak_format import main

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = main([str(root)])
        self.assertEqual(rc, 1)
        return [line for line in buf.getvalue().split("\n") if line]

    def test_findings_are_sorted_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            for arm in ("zeta", "alpha", "mid"):
                arm_dir = root / "2026-06-13" / arm
                arm_dir.mkdir(parents=True)
                # All three missing files → three findings per arm.
            findings = self._run_capture(root)
            self.assertEqual(findings, sorted(findings))


class LineEndingTests(unittest.TestCase):
    def test_crlf_report_md_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            crlf_report = (
                "---\r\n"
                "arm: control\r\n"
                "date: 2026-06-13\r\n"
                "run_id: r1\r\n"
                "git_sha: abc1234\r\n"
                "started_at: 2026-06-13T00:00:00Z\r\n"
                "ended_at: 2026-06-13T01:00:00Z\r\n"
                "---\r\n"
                "Body.\r\n"
            )
            (arm_dir / "report.md").write_text(
                crlf_report, encoding="utf-8", newline=""
            )
            self.assertEqual(main([str(root)]), 0)

    def test_crlf_telemetry_jsonl_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\r\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)


class ImportAllowlistTests(unittest.TestCase):
    def test_verifier_only_imports_allowlisted_stdlib(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "verify_soak_format.py"
        text = path.read_text(encoding="utf-8")
        allowed = {"__future__", "json", "pathlib", "datetime", "argparse", "sys", "re"}
        import_lines = [
            ln
            for ln in text.split("\n")
            if ln.startswith("import ") or ln.startswith("from ")
        ]
        for line in import_lines:
            match = stdlib_re.match(
                r"^(?:from|import)\s+([A-Za-z_][A-Za-z_0-9.]*)", line
            )
            self.assertIsNotNone(match, line)
            top = match.group(1).split(".")[0]
            self.assertIn(
                top,
                allowed,
                f"verify_soak_format.py imports non-allowlisted module {top!r} ({line})",
            )

    def test_verifier_does_not_import_story_automator(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "verify_soak_format.py"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("story_automator", text)
