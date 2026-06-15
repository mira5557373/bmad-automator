"""Unit tests for scripts/verify_retraction_format.py (REQ-10)."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_retraction_format.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_retraction_format", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetractionFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, body: str) -> None:
        (self.dir / name).write_text(body, encoding="utf-8")

    def test_empty_directory_returns_zero(self) -> None:
        self.assertEqual(self.module.main(self.dir), 0)

    def test_no_retractions_section_returns_zero(self) -> None:
        self._write(
            "260101.md",
            "## 260101 - [FULL] x\n\n### Summary\nstuff\n",
        )
        self.assertEqual(self.module.main(self.dir), 0)

    def test_valid_retraction_bullet_returns_zero(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): regressed in CI.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_multiple_valid_bullets_return_zero(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a): first.\n"
            "- [2026-08-01] Retracted by [260801#b]"
            "(./260801.md#b): second.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_malformed_date_format_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [26-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): bad date.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_anchor_text_url_mismatch_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#alpha]"
            "(./260612.md#beta): anchor mismatch.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_yymmdd_ref_file_mismatch_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260613.md#a): file mismatch.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_missing_reason_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a):\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_fenced_code_block_is_skipped(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Worked example\n\n"
            "```markdown\n"
            "### Retractions\n"
            "- not-a-real-bullet\n"
            "```\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_tilde_fenced_code_block_is_skipped(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Worked example\n\n"
            "~~~markdown\n"
            "### Retractions\n"
            "- garbage\n"
            "~~~\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_block_terminates_at_next_heading(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a): ok.\n\n"
            "### Notes\n"
            "- this bullet is outside the retractions block\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_crlf_line_endings_are_tolerated(self) -> None:
        # NFR: correct under Windows CRLF, Unix LF, macOS LF without conversion.
        body = (
            "## 260101 - [FULL] x\r\n"
            "\r\n"
            "### Retractions\r\n"
            "- [2026-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): regressed in CI.\r\n"
        )
        (self.dir / "260101.md").write_bytes(body.encode("utf-8"))
        self.assertEqual(self.module.main(self.dir), 0)

    def test_m12a_worked_example_bullet_validates(self) -> None:
        # The literal bullet from the M12a worked example in CONTRIBUTING.md.
        body = (
            "## 260501 - [FULL] tmux runtime keepalive\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by "
            "[260612#tmux-keepalive-regression-fix]"
            "(./260612.md#tmux-keepalive-regression-fix): "
            "keepalive ping interval regressed in CI; "
            "superseded by the fix entry.\n"
        )
        self._write("260501.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_live_changelog_tree_is_clean(self) -> None:
        # Integration: the real docs/changelog/ tree must be REQ-10 clean.
        self.assertEqual(self.module.main(), 0)


if __name__ == "__main__":
    unittest.main()
