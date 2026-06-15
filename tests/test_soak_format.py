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
