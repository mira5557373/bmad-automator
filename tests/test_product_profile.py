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


class AncillaryValidationTests(BundledProfileTests):
    """Tests for toolchain, rules, seed_template, invariants, snapshot validators."""

    def _valid_base(self) -> dict:
        return {
            "version": 1, "id": "x",
            "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
            "categories": {"code": [], "system": []},
        }

    def test_toolchain_entry_missing_name_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["toolchain"] = {"python": [{"version_min": "0.5.0"}]}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"toolchain\.python\[0\]\.name must be"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_toolchain_entry_bad_required_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["toolchain"] = {"python": [{"name": "ruff", "required": "yes"}]}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"toolchain\.python\[0\]\.required must be a bool"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_rules_entry_must_be_object(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["rules"] = {"security": "strict"}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"rules\.security must be an object"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_seed_template_ref_must_be_string(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["seed_template"] = {"ref": 42}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "seed_template.ref must be a string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_invariants_registry_file_must_be_string(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["invariants"] = {"registry_file": 42}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "invariants.registry_file must be a string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_snapshot_relative_dir_required(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["snapshot"] = {"relativeDir": ""}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "snapshot.relativeDir must be a non-empty string"):
            load_bundled_profile(project_root=str(self.project_root))


class Sec64ValidationTests(BundledProfileTests):
    """Tests for §6.4 fields: cost_tier, categories_na, timeouts, forbidden_until."""

    def _valid_base(self) -> dict:
        return {
            "version": 1, "id": "x",
            "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
            "categories": {"code": [], "system": []},
        }

    def test_cost_tier_must_be_object(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["cost_tier"] = []
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "cost_tier must be an object"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_cost_tier_arpu_must_be_non_negative_number(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["cost_tier"] = {"sku_id": "x", "arpu_monthly": -1}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "cost_tier.arpu_monthly must be a non-negative number"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_categories_na_must_be_string_array(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["categories_na"] = "performance"
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "categories_na must be a string array"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_categories_na_unknown_entry_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["categories_na"] = ["bogus"]
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "unknown categories_na entries: bogus"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_timeouts_unknown_category_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["timeouts"] = {"bogus_cat": 300}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "unknown category in timeouts: bogus_cat"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_timeouts_must_be_positive_integer(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["timeouts"] = {"security": 0}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "timeouts.security must be a positive integer"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_forbidden_until_value_must_be_string_array(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["forbidden_until"] = {"ADR-0083": "E*.envelope-*"}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"forbidden_until\.ADR-0083 must be a string array"):
            load_bundled_profile(project_root=str(self.project_root))


if __name__ == "__main__":
    unittest.main()
