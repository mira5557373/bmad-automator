# tests/test_soak_format.py
from __future__ import annotations

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
        # 'pending' is an accepted sentinel for ended_at (REQ-10); any other
        # non-ISO value is rejected.
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
                "ended_at: not-a-date\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_ended_at_pending_sentinel_is_accepted(self) -> None:
        # REQ-10 carve-out: freshly seeded archives leave ended_at = "pending"
        # until the operator finalizes the run; verify must accept this.
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
            self.assertEqual(main([str(root)]), 0)


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


class SeedSoakDirTests(unittest.TestCase):
    # REQ-13(e), REQ-13(f), REQ-09 (idempotence).

    def test_seed_then_verify_passes(self) -> None:
        from scripts.seed_soak_dir import main as seed_main
        from scripts.verify_soak_format import main as verify_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            rc_seed = seed_main(
                ["--date", "2026-06-13", "--arm", "gate-check", "--root", str(root)]
            )
            self.assertEqual(rc_seed, 0)
            arm_dir = root / "2026-06-13" / "gate-check"
            self.assertTrue((arm_dir / "telemetry.jsonl").is_file())
            self.assertTrue((arm_dir / "config.json").is_file())
            self.assertTrue((arm_dir / "report.md").is_file())
            self.assertEqual(verify_main([str(root)]), 0)

    def test_seed_is_idempotent(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            args = ["--date", "2026-06-13", "--arm", "control", "--root", str(root)]
            self.assertEqual(seed_main(args), 0)
            arm_dir = root / "2026-06-13" / "control"
            # Operator-edited content the second seed must not clobber.
            edited_report = (
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r-final\n"
                "git_sha: deadbee\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n"
                "Operator notes.\n"
            )
            (arm_dir / "report.md").write_text(
                edited_report, encoding="utf-8", newline=""
            )
            edited_telemetry = (
                '{"event_type":"StoryStarted","ts":"2026-06-13T00:00:00Z"}\n'
            )
            (arm_dir / "telemetry.jsonl").write_text(
                edited_telemetry, encoding="utf-8", newline=""
            )
            self.assertEqual(seed_main(args), 0)
            self.assertEqual(
                (arm_dir / "report.md").read_text(encoding="utf-8"),
                edited_report,
            )
            self.assertEqual(
                (arm_dir / "telemetry.jsonl").read_text(encoding="utf-8"),
                edited_telemetry,
            )

    def test_seed_rejects_invalid_date(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            rc = seed_main(["--date", "2026/06/13", "--arm", "control", "--root", tmp])
            self.assertEqual(rc, 2)

    def test_seed_rejects_invalid_arm_slug(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            rc = seed_main(["--date", "2026-06-13", "--arm", "BAD ARM!", "--root", tmp])
            self.assertEqual(rc, 2)
