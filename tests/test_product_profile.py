from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class BundledProfileTests(unittest.TestCase):
    """Base class: copies the skill bundle into a temp project directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install_bundle(self) -> None:
        bundle_src = REPO_ROOT / "skills" / "bmad-story-automator"
        bundle_dest = (
            self.project_root / ".claude" / "skills" / "bmad-story-automator"
        )
        shutil.copytree(bundle_src, bundle_dest)

    def _bundled_path(self, profile_id: str = "default") -> Path:
        return (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "data"
            / "profiles"
            / f"{profile_id}.json"
        )

    def _write_bundled(self, payload: dict) -> None:
        self._bundled_path().write_text(
            json.dumps(payload), encoding="utf-8"
        )


class LoadBundledProfileTests(BundledProfileTests):
    def test_bundled_default_profile_loads(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(profile["id"], "default")
        self.assertIsInstance(profile["version"], int)
        self.assertIn("matrix", profile)
        self.assertIn("categories", profile)

    def test_profile_error_is_value_error(self) -> None:
        from story_automator.core.product_profile import ProfileError

        self.assertTrue(issubclass(ProfileError, ValueError))

    def test_unknown_profile_id_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        with self.assertRaisesRegex(ProfileError, "unknown bundled profile"):
            load_bundled_profile(
                "nonexistent", project_root=str(self.project_root)
            )

    def test_valid_constants_exist(self) -> None:
        from story_automator.core.product_profile import (
            DEFAULT_TIMEOUT_FALLBACK,
            DEFAULT_TIMEOUTS,
            VALID_CODE_CATEGORIES,
            VALID_PRIORITIES,
            VALID_SYSTEM_CATEGORIES,
            VALID_TOP_LEVEL_KEYS,
        )

        self.assertIn("id", VALID_TOP_LEVEL_KEYS)
        self.assertIn("cost_tier", VALID_TOP_LEVEL_KEYS)
        self.assertIn("categories_na", VALID_TOP_LEVEL_KEYS)
        self.assertIn("timeouts", VALID_TOP_LEVEL_KEYS)
        self.assertIn("forbidden_until", VALID_TOP_LEVEL_KEYS)
        self.assertEqual(VALID_PRIORITIES, {"P0", "P1", "P2", "P3"})
        self.assertIn("correctness", VALID_CODE_CATEGORIES)
        self.assertIn("agentic", VALID_CODE_CATEGORIES)
        self.assertIn("reliability", VALID_SYSTEM_CATEGORIES)
        self.assertIn("cost_to_serve", VALID_SYSTEM_CATEGORIES)
        self.assertEqual(DEFAULT_TIMEOUTS["security"], 300)
        self.assertEqual(DEFAULT_TIMEOUTS["correctness"], 1800)
        self.assertEqual(DEFAULT_TIMEOUT_FALLBACK, 120)


class ProfileShapeTests(BundledProfileTests):
    def test_unknown_top_level_key_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x", "bogus": True,
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown top-level profile keys: bogus"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_version_must_be_positive_int(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": "1.0", "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "profile.version must be a positive integer"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_id_must_be_non_empty_string(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "profile.id must be a non-empty string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_matrix_must_include_all_priorities(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {"P0": {"coverage_pct": 100, "levels": []}},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "matrix priorities must include all of"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_coverage_pct_out_of_range_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 101, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, r"matrix\.P0\.coverage_pct must be int 0\.\.100"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_unknown_code_category_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": ["nope"], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_unknown_system_category_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": ["nope"]}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown system categories: nope"):
            load_bundled_profile(project_root=str(self.project_root))


if __name__ == "__main__":
    unittest.main()
