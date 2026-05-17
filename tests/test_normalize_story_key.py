from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from story_automator.core.story_keys import normalize_story_key


class NormalizeStoryKeyTests(unittest.TestCase):
    """Coverage for normalize_story_key, focused on non-numeric epic keys
    (e.g. ``multi-leg.3``) that previously returned ``None`` and broke every
    downstream helper (verify-step, story-file-status, sprint-status, commit-ready).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        (self.project_root / "_bmad-output" / "implementation-artifacts").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # --- Numeric epics (regression coverage for the pre-existing path) ---

    def test_numeric_dotted_id(self) -> None:
        result = normalize_story_key(str(self.project_root), "1.2")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")

    def test_numeric_dashed_prefix(self) -> None:
        result = normalize_story_key(str(self.project_root), "1-2")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")

    def test_numeric_full_key(self) -> None:
        result = normalize_story_key(str(self.project_root), "1-2-user-authentication")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")
        self.assertEqual(result.key, "1-2-user-authentication")

    # --- Non-numeric epic keys (the regression this patch restores) ---

    def test_non_numeric_dotted_id(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg.3")
        assert result is not None, "multi-leg.3 must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")

    def test_non_numeric_dashed_prefix(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-3")
        assert result is not None, "multi-leg-3 must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")

    def test_non_numeric_full_key(self) -> None:
        result = normalize_story_key(
            str(self.project_root),
            "multi-leg-3-lossless-quantity-serialization",
        )
        assert result is not None, "multi-leg-3-... must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-lossless-quantity-serialization")

    def test_compound_epic_name(self) -> None:
        # aerofoil-original.5 — the rpartition logic must split on the LAST '-'
        # to keep the compound epic name intact.
        result = normalize_story_key(str(self.project_root), "aerofoil-original-5")
        assert result is not None
        self.assertEqual(result.id, "aerofoil-original.5")
        self.assertEqual(result.prefix, "aerofoil-original-5")

    # --- Key resolution via filesystem and sprint-status ---

    def test_resolves_key_from_artifact_glob_non_numeric(self) -> None:
        artifacts = self.project_root / "_bmad-output" / "implementation-artifacts"
        (artifacts / "multi-leg-3-lossless-quantity-serialization.md").write_text("", encoding="utf-8")
        result = normalize_story_key(str(self.project_root), "multi-leg.3")
        assert result is not None
        self.assertEqual(result.key, "multi-leg-3-lossless-quantity-serialization")

    def test_resolves_key_from_sprint_status_non_numeric(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  multi-leg-3-lossless-quantity-serialization: done
                  multi-leg-4-strict-asset-precision-registration: ready-for-dev
                """
            ),
            encoding="utf-8",
        )
        result = normalize_story_key(str(self.project_root), "multi-leg.4")
        assert result is not None
        self.assertEqual(result.key, "multi-leg-4-strict-asset-precision-registration")

    # --- Rejection paths ---

    def test_unrecognized_format_returns_none(self) -> None:
        self.assertIsNone(normalize_story_key(str(self.project_root), "garbage"))
        self.assertIsNone(normalize_story_key(str(self.project_root), ""))
        self.assertIsNone(normalize_story_key(str(self.project_root), "1"))
        # Leading digit is not a valid non-numeric epic prefix.
        self.assertIsNone(normalize_story_key(str(self.project_root), "9multi.1"))


if __name__ == "__main__":
    unittest.main()
