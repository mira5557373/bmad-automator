import copy
import unittest

from story_automator.core.profile_versioning import (
    ProfileVersion,
    bump_profile_version,
    format_profile_version,
    has_semver_profile,
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


if __name__ == "__main__":
    unittest.main()
