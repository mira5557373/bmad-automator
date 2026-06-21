"""Tests for the profile composer (compat M44).

The composer merges three profile layers — default, product (e.g. msme-erp),
and bauto-overlay — into a single effective profile with per-category
precedence. Later layers override earlier ones, but the merge is
structure-aware: top-level scalars are replaced wholesale, dict-valued fields
(``toolchain``, ``matrix``, ``categories``, ``rules``, ``timeouts``,
``forbidden_until``, ``cost_tier``, ``invariants``, ``seed_template``,
``snapshot``) deep-merge by key, and list-valued fields
(``categories_na``) union-merge (preserving order, no dupes).

This replaces the ad-hoc layering that historically lived in
``product_profile.load_effective_profile`` — the composer is the single
authority for "how do layers combine".
"""

from __future__ import annotations

import unittest

from story_automator.core.profile_composer import (
    PROFILE_LAYER_NAMES,
    ProfileCompositionError,
    compose_profiles,
    diff_profile,
    profile_layer_summary,
    validate_composed_profile,
)


def _make_default() -> dict:
    return {
        "version": 1,
        "id": "default",
        "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        "seed_template": {"ref": "", "url": ""},
        "toolchain": {},
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
            "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
            "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {
            "code": ["correctness", "static", "security"],
            "system": ["reliability", "resilience"],
        },
        "categories_na": [],
        "rules": {
            "security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
            "license": {"forbidden": [], "boundary": {}},
        },
        "invariants": {"registry_file": ""},
        "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
        "timeouts": {},
        "forbidden_until": {},
    }


def _make_msme_erp() -> dict:
    return {
        "id": "msme-erp",
        "rules": {
            "security": {"sast_max_high": 5},
            "test_quality": {"min_score": 80},
        },
        "categories_na": ["accessibility"],
        "timeouts": {"security": 600},
        "matrix": {
            "P0": {"coverage_pct": 95},
        },
    }


def _make_bauto_overlay() -> dict:
    return {
        "id": "bauto-overlay",
        "rules": {
            "security": {"deps_max_critical": 2},
        },
        "categories_na": ["mutation"],
        "timeouts": {"performance": 1200},
    }


class ProfileComposerBasicTests(unittest.TestCase):
    def test_composes_three_layers_into_single_profile(self) -> None:
        result = compose_profiles(_make_default(), _make_msme_erp(), _make_bauto_overlay())
        self.assertIsInstance(result, dict)
        # id comes from the last layer that defines it
        self.assertEqual(result["id"], "bauto-overlay")
        # version preserved from default since later layers don't override it specifically
        self.assertEqual(result["version"], 1)

    def test_later_layer_overrides_top_level_scalar(self) -> None:
        result = compose_profiles(_make_default(), {"id": "x"}, {"id": "y"})
        self.assertEqual(result["id"], "y")

    def test_dict_fields_deep_merge_by_key(self) -> None:
        result = compose_profiles(_make_default(), _make_msme_erp(), _make_bauto_overlay())
        # rules.security merges from both layers
        sec = result["rules"]["security"]
        self.assertEqual(sec["sast_max_high"], 5)  # from msme-erp
        self.assertEqual(sec["deps_max_critical"], 2)  # from bauto-overlay
        self.assertEqual(sec["secrets_max"], 0)  # preserved from default
        # rules.test_quality only in msme-erp
        self.assertEqual(result["rules"]["test_quality"]["min_score"], 80)
        # rules.license preserved from default untouched
        self.assertEqual(result["rules"]["license"], {"forbidden": [], "boundary": {}})

    def test_list_fields_union_merge_preserving_order(self) -> None:
        result = compose_profiles(_make_default(), _make_msme_erp(), _make_bauto_overlay())
        # categories_na: [] + ["accessibility"] + ["mutation"] -> union with order
        self.assertEqual(result["categories_na"], ["accessibility", "mutation"])

    def test_list_union_dedupes_repeated_entries(self) -> None:
        result = compose_profiles(
            {"categories_na": ["a", "b"]},
            {"categories_na": ["b", "c"]},
            {"categories_na": ["c", "d"]},
        )
        self.assertEqual(result["categories_na"], ["a", "b", "c", "d"])

    def test_matrix_deep_merge_preserves_unspecified_buckets(self) -> None:
        result = compose_profiles(_make_default(), _make_msme_erp(), _make_bauto_overlay())
        # P0.coverage_pct overridden but levels preserved
        self.assertEqual(result["matrix"]["P0"]["coverage_pct"], 95)
        self.assertEqual(
            result["matrix"]["P0"]["levels"],
            ["unit", "integration", "contract", "e2e"],
        )
        # P1 untouched
        self.assertEqual(result["matrix"]["P1"]["coverage_pct"], 90)


class ProfileComposerEdgeCaseTests(unittest.TestCase):
    def test_empty_layers_produce_empty_result(self) -> None:
        result = compose_profiles({}, {}, {})
        self.assertEqual(result, {})

    def test_single_layer_returns_independent_copy(self) -> None:
        base = _make_default()
        result = compose_profiles(base)
        self.assertEqual(result, base)
        # mutating result must not mutate input
        result["id"] = "mutated"
        self.assertEqual(base["id"], "default")
        # nested mutation must not bleed back
        result["rules"]["security"]["sast_max_high"] = 99
        self.assertEqual(base["rules"]["security"]["sast_max_high"], 0)

    def test_unknown_top_level_key_raises(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            compose_profiles({"version": 1}, {"unknown_key": True})

    def test_mismatched_field_types_raises(self) -> None:
        # rules is supposed to be a dict; passing list -> error
        with self.assertRaises(ProfileCompositionError):
            compose_profiles(_make_default(), {"rules": ["not", "a", "dict"]})

    def test_no_layers_raises(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            compose_profiles()

    def test_non_dict_layer_raises(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            compose_profiles(_make_default(), "not-a-dict")  # type: ignore[arg-type]


class ProfileComposerValidationTests(unittest.TestCase):
    def test_validate_composed_profile_accepts_well_formed(self) -> None:
        result = compose_profiles(_make_default(), _make_msme_erp(), _make_bauto_overlay())
        validate_composed_profile(result)  # must not raise

    def test_validate_rejects_invalid_priority_in_matrix(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            validate_composed_profile({"matrix": {"P9": {"coverage_pct": 100}}})

    def test_validate_rejects_negative_timeout(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            validate_composed_profile({"timeouts": {"security": -1}})

    def test_validate_rejects_non_int_version(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            validate_composed_profile({"version": "1"})

    def test_validate_rejects_non_list_categories_na(self) -> None:
        with self.assertRaises(ProfileCompositionError):
            validate_composed_profile({"categories_na": "accessibility"})


class ProfileComposerIntrospectionTests(unittest.TestCase):
    def test_profile_layer_summary_reports_origin_per_key(self) -> None:
        summary = profile_layer_summary(
            _make_default(),
            _make_msme_erp(),
            _make_bauto_overlay(),
        )
        # rules.security.sast_max_high came from layer 1 (msme-erp)
        self.assertEqual(summary["rules.security.sast_max_high"], 1)
        # rules.security.deps_max_critical came from layer 2 (bauto-overlay)
        self.assertEqual(summary["rules.security.deps_max_critical"], 2)
        # version came from layer 0 (default)
        self.assertEqual(summary["version"], 0)

    def test_profile_layer_summary_omits_unset_keys(self) -> None:
        summary = profile_layer_summary({}, {}, {})
        self.assertEqual(summary, {})

    def test_diff_profile_reports_added_changed_removed(self) -> None:
        before = {"id": "a", "rules": {"security": {"sast_max_high": 0}}}
        after = {
            "id": "b",
            "rules": {"security": {"sast_max_high": 5, "deps_max_critical": 2}},
        }
        diff = diff_profile(before, after)
        self.assertEqual(diff["changed"]["id"], ("a", "b"))
        self.assertEqual(diff["changed"]["rules.security.sast_max_high"], (0, 5))
        self.assertEqual(diff["added"]["rules.security.deps_max_critical"], 2)
        self.assertEqual(diff["removed"], {})

    def test_diff_profile_reports_removed_keys(self) -> None:
        before = {"id": "a", "categories_na": ["accessibility"]}
        after = {"id": "a"}
        diff = diff_profile(before, after)
        self.assertEqual(diff["removed"], {"categories_na": ["accessibility"]})
        self.assertEqual(diff["added"], {})
        self.assertEqual(diff["changed"], {})


class ProfileComposerConstantsTests(unittest.TestCase):
    def test_profile_layer_names_lists_three_layers_in_order(self) -> None:
        self.assertEqual(
            PROFILE_LAYER_NAMES,
            ("default", "product", "bauto-overlay"),
        )


if __name__ == "__main__":
    unittest.main()
