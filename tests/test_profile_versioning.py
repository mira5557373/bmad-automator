import copy
import unittest

from story_automator.core.profile_versioning import (
    ProfileVersion,
    bump_profile_version,
    classify_changes,
    compute_breaking_hash,
    format_profile_version,
    has_semver_profile,
    is_breaking_change,
    parse_profile_version,
)


class ParseProfileVersionTests(unittest.TestCase):
    def test_integer_version(self) -> None:
        profile = {"version": 3, "id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 3)
        self.assertEqual(pv.feature, 0)

    def test_dict_version(self) -> None:
        profile = {"version": {"breaking": 2, "feature": 5}, "id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 2)
        self.assertEqual(pv.feature, 5)

    def test_missing_version_defaults(self) -> None:
        profile = {"id": "test"}
        pv = parse_profile_version(profile)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 0)


class FormatProfileVersionTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        pv = ProfileVersion(breaking=2, feature=3)
        d = format_profile_version(pv)
        self.assertEqual(d, {"breaking": 2, "feature": 3})


class HasSemverProfileTests(unittest.TestCase):
    def test_integer_version(self) -> None:
        self.assertFalse(has_semver_profile({"version": 1}))

    def test_dict_version(self) -> None:
        self.assertTrue(has_semver_profile({"version": {"breaking": 1, "feature": 0}}))


_BUMP_PROFILE = {
    "version": {"breaking": 1, "feature": 2},
    "id": "test",
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": ["unit"]},
        "P1": {"coverage_pct": 90, "levels": ["unit"]},
        "P2": {"coverage_pct": 50, "levels": ["unit"]},
        "P3": {"coverage_pct": 20, "levels": ["smoke"]},
    },
    "categories": {"code": [], "system": []},
}


class BumpProfileVersionTests(unittest.TestCase):
    def test_bump_feature(self) -> None:
        profile = copy.deepcopy(_BUMP_PROFILE)
        result = bump_profile_version(profile, "feature")
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 3)

    def test_bump_breaking_resets_feature(self) -> None:
        profile = copy.deepcopy(_BUMP_PROFILE)
        profile["version"] = {"breaking": 1, "feature": 5}
        result = bump_profile_version(profile, "breaking")
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 2)
        self.assertEqual(pv.feature, 0)

    def test_bump_from_integer_upgrades_format(self) -> None:
        profile = copy.deepcopy(_BUMP_PROFILE)
        profile["version"] = 1
        result = bump_profile_version(profile, "feature")
        self.assertTrue(has_semver_profile(result))
        pv = parse_profile_version(result)
        self.assertEqual(pv.breaking, 1)
        self.assertEqual(pv.feature, 1)

    def test_original_not_mutated(self) -> None:
        profile = copy.deepcopy(_BUMP_PROFILE)
        profile["version"] = {"breaking": 1, "feature": 0}
        original = copy.deepcopy(profile)
        bump_profile_version(profile, "feature")
        self.assertEqual(profile, original)


_BASE_PROFILE = {
    "version": {"breaking": 1, "feature": 0},
    "id": "test",
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": ["unit"]},
        "P1": {"coverage_pct": 90, "levels": ["unit"]},
        "P2": {"coverage_pct": 50, "levels": ["unit"]},
        "P3": {"coverage_pct": 20, "levels": ["smoke"]},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
    "rules": {"security": {"sast_max_high": 0}},
    "timeouts": {"security": 300},
    "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
    "forbidden_until": {},
    "invariants": {"registry_file": ""},
    "toolchain": {},
    "seed_template": {},
    "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
}


class IsBreakingChangeTests(unittest.TestCase):
    def test_no_change(self) -> None:
        self.assertFalse(is_breaking_change(_BASE_PROFILE, copy.deepcopy(_BASE_PROFILE)))

    def test_timeout_change_is_not_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        self.assertFalse(is_breaking_change(_BASE_PROFILE, new))

    def test_matrix_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_categories_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["categories"]["code"].append("docs")
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_rules_change_is_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["rules"]["security"]["sast_max_high"] = 1
        self.assertTrue(is_breaking_change(_BASE_PROFILE, new))

    def test_cost_tier_change_is_not_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["cost_tier"]["arpu_monthly"] = 100
        self.assertFalse(is_breaking_change(_BASE_PROFILE, new))


class ClassifyChangesTests(unittest.TestCase):
    def test_no_changes(self) -> None:
        self.assertEqual(classify_changes(_BASE_PROFILE, copy.deepcopy(_BASE_PROFILE)), [])

    def test_classifies_timeout_as_feature(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        changes = classify_changes(_BASE_PROFILE, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["field"], "timeouts")
        self.assertEqual(changes[0]["change_type"], "feature")

    def test_classifies_matrix_as_breaking(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        changes = classify_changes(_BASE_PROFILE, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["field"], "matrix")
        self.assertEqual(changes[0]["change_type"], "breaking")


class ComputeBreakingHashTests(unittest.TestCase):
    def test_same_profile_same_hash(self) -> None:
        h1 = compute_breaking_hash(_BASE_PROFILE)
        h2 = compute_breaking_hash(copy.deepcopy(_BASE_PROFILE))
        self.assertEqual(h1, h2)

    def test_timeout_change_same_hash(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["timeouts"]["security"] = 600
        self.assertEqual(
            compute_breaking_hash(_BASE_PROFILE),
            compute_breaking_hash(new),
        )

    def test_matrix_change_different_hash(self) -> None:
        new = copy.deepcopy(_BASE_PROFILE)
        new["matrix"]["P0"]["coverage_pct"] = 95
        self.assertNotEqual(
            compute_breaking_hash(_BASE_PROFILE),
            compute_breaking_hash(new),
        )


if __name__ == "__main__":
    unittest.main()
