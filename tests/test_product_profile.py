from __future__ import annotations

import json
import os
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

    def test_profile_id_path_traversal_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        with self.assertRaisesRegex(ProfileError, "invalid profile id"):
            load_bundled_profile("../../../etc/passwd", project_root=str(self.project_root))

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


class EffectiveProfileTests(BundledProfileTests):
    def _write_override(self, payload: dict) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_no_override_returns_bundled(self) -> None:
        from story_automator.core.product_profile import load_effective_profile

        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "default")

    def test_override_deep_merges(self) -> None:
        from story_automator.core.product_profile import load_effective_profile

        self._write_override({
            "id": "custom",
            "rules": {"security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 1}},
        })
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "custom")
        self.assertEqual(profile["rules"]["security"]["secrets_max"], 1)
        # Untouched default rule value still present
        self.assertEqual(profile["rules"]["test_quality"]["min_score"], 70)

    def test_override_array_replaces_not_appends(self) -> None:
        from story_automator.core.product_profile import load_effective_profile

        self._write_override({
            "categories": {"code": ["security"], "system": ["resilience"]},
        })
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["categories"]["code"], ["security"])

    def test_override_validation_failure_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_effective_profile,
        )

        self._write_override({
            "categories": {"code": ["nope"], "system": []},
        })
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_effective_profile(str(self.project_root))

    def test_malformed_override_json_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_effective_profile,
        )

        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            "{bad json", encoding="utf-8"
        )
        with self.assertRaisesRegex(ProfileError, "profile json invalid"):
            load_effective_profile(str(self.project_root))

    def test_env_var_selects_profile_id(self) -> None:
        from unittest.mock import patch

        from story_automator.core.product_profile import load_effective_profile

        # Default profile has id "default"; env var cannot select
        # msme-erp yet (data file created in Task 10). Test the
        # mechanism: env var overrides the default profile_id.
        with patch.dict(os.environ, {"STORY_AUTOMATOR_PROFILE": "default"}):
            profile = load_effective_profile(str(self.project_root))
            self.assertEqual(profile["id"], "default")

    def test_explicit_profile_id_takes_precedence_over_env(self) -> None:
        from unittest.mock import patch

        from story_automator.core.product_profile import load_effective_profile

        with patch.dict(os.environ, {"STORY_AUTOMATOR_PROFILE": "nonexistent"}):
            profile = load_effective_profile(
                str(self.project_root), profile_id="default"
            )
            self.assertEqual(profile["id"], "default")


class AccessorTests(BundledProfileTests):
    def test_required_for_priority_p0(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        req = required_for_priority(profile, "P0")
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])

    def test_required_for_priority_unknown_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        with self.assertRaisesRegex(ProfileError, "unknown priority: P9"):
            required_for_priority(profile, "P9")

    def test_required_for_priority_returns_copy(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        req = required_for_priority(profile, "P0")
        req["levels"].append("mutated")
        again = required_for_priority(profile, "P0")
        self.assertNotIn("mutated", again["levels"])

    def test_toolchain_for_unknown_language_returns_empty(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            toolchain_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(toolchain_for(profile, "rust"), [])

    def test_rule_for_missing_category_returns_empty(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            rule_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(rule_for(profile, "performance"), {})

    def test_rule_for_present_category(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            rule_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        rule = rule_for(profile, "security")
        self.assertEqual(rule["sast_max_high"], 0)

    def test_toolchain_for_returns_deep_copy(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            toolchain_for,
        )

        # Write a profile with nested toolchain data
        bundled = json.loads(self._bundled_path().read_text(encoding="utf-8"))
        bundled["toolchain"] = {"python": [{"name": "ruff", "required": True, "opts": {"fix": True}}]}
        self._write_bundled(bundled)
        profile = load_bundled_profile(project_root=str(self.project_root))
        tools = toolchain_for(profile, "python")
        tools[0]["opts"]["fix"] = False
        again = toolchain_for(profile, "python")
        self.assertTrue(again[0]["opts"]["fix"])


class ForbiddenUntilTests(BundledProfileTests):
    def _write_forbidden(self, mapping: dict) -> None:
        bundled = json.loads(self._bundled_path().read_text(encoding="utf-8"))
        bundled["forbidden_until"] = mapping
        self._write_bundled(bundled)

    def test_no_forbidden_means_unblocked(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(is_story_blocked(profile, "E1.S1"), (False, ""))

    def test_glob_pattern_blocks_matching_story(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({"ADR-0083": ["E*.envelope-*"]})
        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            is_story_blocked(profile, "E1.envelope-sign"), (True, "ADR-0083")
        )
        self.assertEqual(
            is_story_blocked(profile, "E1.ledger-write"), (False, "")
        )

    def test_multiple_blockers_returns_first_sorted(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({
            "DG-3": ["E*.envelope-*"],
            "ADR-0083": ["E*.envelope-*"],
        })
        profile = load_bundled_profile(project_root=str(self.project_root))
        blocked, adr = is_story_blocked(profile, "E1.envelope-sign")
        self.assertTrue(blocked)
        self.assertEqual(adr, "ADR-0083")

    def test_dg2_blocks_cost_to_serve(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({"DG-2": ["*.cost-to-serve"]})
        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            is_story_blocked(profile, "E5.cost-to-serve"), (True, "DG-2")
        )


class ProfileHashTests(BundledProfileTests):
    def test_hash_is_deterministic(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            compute_profile_hash(profile), compute_profile_hash(profile)
        )

    def test_hash_changes_on_modification(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        h1 = compute_profile_hash(profile)
        profile["id"] = "modified"
        h2 = compute_profile_hash(profile)
        self.assertNotEqual(h1, h2)

    def test_hash_is_8_char_hex(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        h = compute_profile_hash(profile)
        self.assertEqual(len(h), 8)
        int(h, 16)  # must be valid hex


class ProfileSnapshotTests(BundledProfileTests):
    def test_snapshot_is_deterministic(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        first = snapshot_effective_profile(str(self.project_root))
        second = snapshot_effective_profile(str(self.project_root))
        self.assertEqual(
            first["profileSnapshotHash"], second["profileSnapshotHash"]
        )

    def test_snapshot_file_lives_under_project_root(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        snap = snapshot_effective_profile(str(self.project_root))
        snap_path = self.project_root / snap["profileSnapshotFile"]
        self.assertTrue(snap_path.is_file())

    def test_snapshot_includes_profile_hash(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        snap = snapshot_effective_profile(str(self.project_root))
        self.assertIn("profileHash", snap)
        self.assertEqual(len(snap["profileHash"]), 8)

    def test_snapshot_escape_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            snapshot_effective_profile,
        )

        bundled = json.loads(
            self._bundled_path().read_text(encoding="utf-8")
        )
        bundled["snapshot"]["relativeDir"] = "../outside"
        self._write_bundled(bundled)
        with self.assertRaisesRegex(ProfileError, "escapes allowed root"):
            snapshot_effective_profile(str(self.project_root))

    def test_load_snapshot_detects_hash_mismatch(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_profile_snapshot,
            snapshot_effective_profile,
        )

        snap = snapshot_effective_profile(str(self.project_root))
        with self.assertRaisesRegex(ProfileError, "profile snapshot hash mismatch"):
            load_profile_snapshot(
                snap["profileSnapshotFile"],
                project_root=str(self.project_root),
                expected_hash="deadbeef",
            )


class MsmeErpProfileTests(BundledProfileTests):
    def test_msme_erp_loads_and_validates(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["id"], "msme-erp")
        self.assertEqual(profile["version"], 1)

    def test_msme_erp_p0_full_coverage(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        req = required_for_priority(profile, "P0")
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])

    def test_msme_erp_forbidden_until_adr0083(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, adr = is_story_blocked(profile, "E1.envelope-sign")
        self.assertTrue(blocked)
        self.assertEqual(adr, "ADR-0083")

    def test_msme_erp_forbidden_until_dg2(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, dg = is_story_blocked(profile, "E5.cost-to-serve")
        self.assertTrue(blocked)
        self.assertEqual(dg, "DG-2")

    def test_msme_erp_cost_tier_zero_placeholders(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["cost_tier"]["arpu_monthly"], 0)
        self.assertEqual(profile["cost_tier"]["max_pod_cost_per_tenant"], 0)

    def test_msme_erp_timeouts_match_spec(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["timeouts"]["security"], 300)
        self.assertEqual(profile["timeouts"]["performance"], 600)
        self.assertEqual(profile["timeouts"]["accessibility"], 180)
        self.assertEqual(profile["timeouts"]["test_quality"], 900)
        self.assertEqual(profile["timeouts"]["correctness"], 1800)

    def test_msme_erp_full_code_categories(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        code_cats = profile["categories"]["code"]
        for required in ("correctness", "security", "agentic", "docs", "process"):
            self.assertIn(required, code_cats)

    def test_msme_erp_dg3_blocks_ca_channel(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, dg = is_story_blocked(profile, "E3.ca-channel-premium")
        self.assertTrue(blocked)
        self.assertEqual(dg, "DG-3")


class ProfileCustomizeFactsTests(BundledProfileTests):
    def test_facts_include_profile_identity(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_customize_facts

        profile = load_bundled_profile(project_root=str(self.project_root))
        facts = profile_customize_facts(profile)
        self.assertEqual(facts["profile_id"], "default")
        self.assertEqual(facts["profile_version"], 1)
        self.assertEqual(len(facts["profile_hash"]), 8)

    def test_facts_include_forbidden_adrs(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_customize_facts

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        facts = profile_customize_facts(profile)
        self.assertIn("ADR-0083", facts["forbidden_adrs"])
        self.assertIn("DG-2", facts["forbidden_adrs"])
        self.assertIn("forbidden_patterns", facts)

    def test_facts_include_gate_rules(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_customize_facts

        profile = load_bundled_profile(project_root=str(self.project_root))
        facts = profile_customize_facts(profile)
        self.assertIn("gate_rules", facts)
        self.assertIn("security", facts["gate_rules"])

    def test_facts_include_invariants_registry(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_customize_facts

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        facts = profile_customize_facts(profile)
        self.assertEqual(
            facts["invariants_registry"],
            "data/profiles/msme-erp.invariants.yaml",
        )

    def test_facts_include_categories_na(self) -> None:
        from story_automator.core.profile_bridge import profile_customize_facts

        profile = {
            "id": "test", "version": 1,
            "categories_na": ["accessibility", "performance"],
        }
        facts = profile_customize_facts(profile)
        self.assertEqual(facts["categories_na"], ["accessibility", "performance"])


class ProfileActivationBlocksTests(BundledProfileTests):
    def test_prepend_includes_profile_id(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_activation_blocks

        profile = load_bundled_profile(project_root=str(self.project_root))
        blocks = profile_activation_blocks(profile)
        self.assertIn("default", blocks["prepend"])
        self.assertIn("Product Profile", blocks["prepend"])

    def test_prepend_includes_blocked_adrs(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_activation_blocks

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocks = profile_activation_blocks(profile)
        self.assertIn("ADR-0083", blocks["prepend"])

    def test_append_is_empty_by_default(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.profile_bridge import profile_activation_blocks

        profile = load_bundled_profile(project_root=str(self.project_root))
        blocks = profile_activation_blocks(profile)
        self.assertEqual(blocks["append"], "")


if __name__ == "__main__":
    unittest.main()
