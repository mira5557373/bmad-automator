# tests/test_soak_format.py
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


class VerifyExitCodesTests(unittest.TestCase):
    def test_main_returns_zero_on_empty_root(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([tmp]), 0)

    def test_main_returns_two_on_usage_error(self) -> None:
        from scripts.verify_soak_format import main

        # Passing an unknown flag is a usage error (exit 2).
        self.assertEqual(main(["--no-such-flag"]), 2)

    def test_main_returns_one_when_path_missing(self) -> None:
        from scripts.verify_soak_format import main

        self.assertEqual(main(["/definitely/does/not/exist/soak-root"]), 1)


class DateAndArmValidationTests(unittest.TestCase):
    def _make_root(self, tmp: str) -> Path:
        root = Path(tmp) / "soak"
        root.mkdir()
        return root

    def test_invalid_date_directory_is_reported(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "not-a-date").mkdir()
            self.assertEqual(main([str(root)]), 1)

    def test_invalid_arm_slug_is_reported(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            arm = root / "2026-06-13" / "BAD ARM!"
            arm.mkdir(parents=True)
            # Even with required files present, the slug is invalid.
            (arm / "telemetry.jsonl").write_text("", encoding="utf-8")
            (arm / "report.md").write_text("", encoding="utf-8")
            (arm / "config.json").write_text("{}", encoding="utf-8")
            self.assertEqual(main([str(root)]), 1)

    def test_empty_date_dir_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "2026-06-13").mkdir()
            self.assertEqual(main([str(root)]), 0)


def _write_minimal_arm(
    root: Path, date_str: str = "2026-06-13", arm: str = "control"
) -> Path:
    arm_dir = root / date_str / arm
    arm_dir.mkdir(parents=True)
    (arm_dir / "telemetry.jsonl").write_text(
        '{"event_type":"StoryStarted","ts":"2026-06-13T00:00:00Z"}\n',
        encoding="utf-8",
        newline="",
    )
    (arm_dir / "report.md").write_text(
        "---\n"
        "arm: control\n"
        "date: 2026-06-13\n"
        "run_id: r1\n"
        "git_sha: abc1234\n"
        "started_at: 2026-06-13T00:00:00Z\n"
        "ended_at: 2026-06-13T01:00:00Z\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
        newline="",
    )
    (arm_dir / "config.json").write_text(
        '{"arm":"control","seed":1,"model":"m","concurrency":1,"notes":"n"}',
        encoding="utf-8",
        newline="",
    )
    return arm_dir


class RequiredFilesTests(unittest.TestCase):
    def test_valid_arm_passes(self) -> None:
        # REQ-13(a)
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            _write_minimal_arm(root)
            self.assertEqual(main([str(root)]), 0)

    def test_each_missing_required_file_fails(self) -> None:
        # REQ-13(b) — covers each of the three required files individually.
        from scripts.verify_soak_format import main

        for missing in ("telemetry.jsonl", "report.md", "config.json"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "soak"
                root.mkdir()
                arm_dir = _write_minimal_arm(root)
                (arm_dir / missing).unlink()
                self.assertEqual(main([str(root)]), 1, missing)


class FrontmatterTests(unittest.TestCase):
    # REQ-13(c)

    def test_missing_frontmatter_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "Body only.\n", encoding="utf-8", newline=""
            )
            self.assertEqual(main([str(root)]), 1)

    def test_unterminated_frontmatter_fails(self) -> None:
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
                "no closing fence\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_required_key_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            # Drop git_sha.
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_unparseable_started_at_fails(self) -> None:
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
                "started_at: nope\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_unparseable_ended_at_fails(self) -> None:
        # REQ-05 is literal: ended_at must parse via fromisoformat. No
        # 'pending' carve-out here — that tension is M2 scope.
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
                "ended_at: pending\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)


class ConfigJsonTests(unittest.TestCase):
    def test_non_object_root_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text("[]", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 1)

    def test_missing_key_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":1,"model":"m","concurrency":1}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_wrong_type_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":"one","model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_bool_does_not_satisfy_int(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":true,"model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_arm_mismatch_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)  # arm dir named "control"
            (arm_dir / "config.json").write_text(
                '{"arm":"treatment","seed":1,"model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_invalid_json_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                "{not json", encoding="utf-8", newline=""
            )
            self.assertEqual(main([str(root)]), 1)


class TelemetryJsonlTests(unittest.TestCase):
    def test_empty_file_passes(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text("", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 0)

    def test_blank_lines_are_skipped(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\n\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)

    def test_invalid_json_line_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\nnot-json\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_event_type_fails(self) -> None:
        # REQ-13(d)
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"ts":"2026-06-13T00:00:00Z"}\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_ts_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X"}\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_non_object_line_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '["not","object"]\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)


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
                "Body with [TODO] left in it.\n",
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
                '{"arm":"control","seed":1,"model":"m","concurrency":1,"notes":"[FIXM]"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_markdown_link_is_not_a_placeholder(self) -> None:
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
