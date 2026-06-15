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


# REQ-12: verifier rejects unresolved four-letter bracketed placeholder tokens.
# The literal tokens are kept out of CONTRIBUTING.md and the verifier source
# (which is grep-gated in CI) and live only inside this test module.
_PLACEHOLDER_TOKEN = "[" + "T" + "O" + "D" + "O" + "]"
_FIXME_TOKEN = "[" + "F" + "I" + "X" + "M" + "]"


class PlaceholderTokenTests(unittest.TestCase):
    def test_placeholder_in_report_md_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n"
                f"Body with {_PLACEHOLDER_TOKEN} left in it.\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_placeholder_in_config_json_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":1,"model":"m","concurrency":1,'
                f'"notes":"{_FIXME_TOKEN}"' + "}",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_markdown_link_is_not_a_placeholder(self) -> None:
        # Numeric brackets like [1234] are footnote-style references and must
        # not be flagged; only uppercase four-letter bracketed tokens are.
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n"
                "See [link](https://example.com) and [1234] for details.\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)


class SeedSoakDirExtraTests(unittest.TestCase):
    """Coverage and NFR pin-down tests for seed_soak_dir; supplements REQ-13."""

    def test_seed_missing_required_arg_returns_two(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        self.assertEqual(seed_main([]), 2)

    def test_seed_writes_lf_line_endings(self) -> None:
        # NFR line-ending portability: report.md bytes must be LF on all OSes.
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            self.assertEqual(
                seed_main(
                    ["--date", "2026-06-13", "--arm", "control", "--root", str(root)]
                ),
                0,
            )
            arm_dir = root / "2026-06-13" / "control"
            report_bytes = (arm_dir / "report.md").read_bytes()
            self.assertNotIn(b"\r\n", report_bytes)
            self.assertIn(b"\n", report_bytes)

    def test_seed_uses_story_automator_helpers_when_importable(self) -> None:
        # REQ-09: prefer story_automator helpers; only fall back on ImportError.
        import scripts.seed_soak_dir as seed_module
        from story_automator.core.common import iso_now as expected_iso_now

        self.assertIs(seed_module.iso_now, expected_iso_now)

    def test_seed_fallback_path_works_when_story_automator_missing(self) -> None:
        # REQ-09: the inlined-stdlib fallback must produce a verify-passing
        # arm when story_automator is unimportable (operator on a clean
        # checkout). Without this test the fallback ships at 0% coverage.
        import importlib

        import scripts.seed_soak_dir as seed_module
        from scripts.verify_soak_format import main as verify_main

        blocked_names = (
            "story_automator",
            "story_automator.core",
            "story_automator.core.common",
        )
        saved = {n: sys.modules[n] for n in list(sys.modules) if n in blocked_names}
        try:
            for name in blocked_names:
                sys.modules[name] = None  # type: ignore[assignment]
            reloaded = importlib.reload(seed_module)
            # Fallback iso_now is defined inside the except branch of
            # scripts.seed_soak_dir, not imported from story_automator.
            self.assertEqual(reloaded.iso_now.__module__, "scripts.seed_soak_dir")
            self.assertRegex(
                reloaded.iso_now(),
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "soak"
                rc = reloaded.main(
                    [
                        "--date",
                        "2026-06-13",
                        "--arm",
                        "fallback",
                        "--root",
                        str(root),
                    ]
                )
                self.assertEqual(rc, 0)
                self.assertEqual(verify_main([str(root)]), 0)
        finally:
            for name in blocked_names:
                sys.modules.pop(name, None)
            for name, mod in saved.items():
                sys.modules[name] = mod
            # Restore the primary path so subsequent tests see the
            # story_automator-backed helpers again.
            importlib.reload(seed_module)


class ContributingGrepGateTests(unittest.TestCase):
    """Mirrors the CI grep gate from the M13 quality gates."""

    def test_contributing_md_has_no_placeholder_tokens(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        text = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIsNone(
            stdlib_re.search(r"\[[A-Z]{4}\]", text),
            "CONTRIBUTING.md contains an unresolved four-letter placeholder token",
        )
