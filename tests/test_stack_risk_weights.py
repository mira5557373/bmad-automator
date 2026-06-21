from __future__ import annotations

import unittest

from story_automator.core.innovation.stack_risk_weights import (
    StackRiskError,
    StackWeight,
    DEFAULT_STACK_WEIGHTS,
    DEFAULT_PATH_TAXONOMY,
    VALID_STACK_IDS,
    classify_path,
    classify_paths,
    weight_for_path,
    weight_for_stack,
    apply_weight,
    aggregate_weights,
    risk_multiplier,
    explain_classification,
    validate_taxonomy,
    validate_weights,
    register_stack,
    is_known_stack,
)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class ClassifyPathTests(unittest.TestCase):
    def test_classify_backend_path(self) -> None:
        self.assertEqual(classify_path("skills/bmad-story-automator/src/foo.py"), "backend")
        self.assertEqual(classify_path("src/story_automator/core/x.py"), "backend")

    def test_classify_tests_path(self) -> None:
        self.assertEqual(classify_path("tests/test_foo.py"), "tests")
        self.assertEqual(classify_path("tests/integration/test_e2e.py"), "tests")

    def test_classify_docs_path(self) -> None:
        self.assertEqual(classify_path("docs/spec/m56.md"), "docs")
        self.assertEqual(classify_path("README.md"), "docs")

    def test_classify_config_path(self) -> None:
        self.assertEqual(classify_path(".claude-plugin/plugin.json"), "config")
        self.assertEqual(classify_path("package.json"), "config")
        self.assertEqual(classify_path("pyproject.toml"), "config")

    def test_classify_scripts_path(self) -> None:
        self.assertEqual(classify_path("scripts/smoke-test.sh"), "scripts")
        self.assertEqual(classify_path("bin/bmad-story-automator"), "scripts")

    def test_classify_unknown_path_returns_other(self) -> None:
        self.assertEqual(classify_path("random/file.xyz"), "other")
        self.assertEqual(classify_path("foo.bar"), "other")

    def test_classify_path_rejects_empty(self) -> None:
        with self.assertRaises(StackRiskError):
            classify_path("")

    def test_classify_path_rejects_non_string(self) -> None:
        with self.assertRaises(StackRiskError):
            classify_path(None)  # type: ignore[arg-type]

    def test_classify_paths_groups_by_stack(self) -> None:
        result = classify_paths(
            [
                "src/foo.py",
                "tests/test_foo.py",
                "docs/x.md",
                "src/bar.py",
            ]
        )
        self.assertEqual(result["backend"], ["src/foo.py", "src/bar.py"])
        self.assertEqual(result["tests"], ["tests/test_foo.py"])
        self.assertEqual(result["docs"], ["docs/x.md"])
        self.assertNotIn("other", result)

    def test_classify_paths_empty(self) -> None:
        self.assertEqual(classify_paths([]), {})


# ---------------------------------------------------------------------------
# Weight lookup
# ---------------------------------------------------------------------------


class WeightLookupTests(unittest.TestCase):
    def test_default_weights_include_all_stacks(self) -> None:
        for stack in VALID_STACK_IDS:
            self.assertIn(stack, DEFAULT_STACK_WEIGHTS)

    def test_weight_for_backend_is_highest(self) -> None:
        backend = weight_for_stack("backend")
        docs = weight_for_stack("docs")
        self.assertGreater(backend.multiplier, docs.multiplier)

    def test_weight_for_path_returns_stack_weight(self) -> None:
        w = weight_for_path("src/foo.py")
        self.assertEqual(w.stack, "backend")

    def test_weight_for_unknown_stack_raises(self) -> None:
        with self.assertRaises(StackRiskError):
            weight_for_stack("not-a-stack")

    def test_is_known_stack(self) -> None:
        self.assertTrue(is_known_stack("backend"))
        self.assertFalse(is_known_stack("not-a-stack"))

    def test_weight_for_stack_is_stable(self) -> None:
        w1 = weight_for_stack("tests")
        w2 = weight_for_stack("tests")
        self.assertEqual(w1.multiplier, w2.multiplier)
        self.assertEqual(w1.stack, w2.stack)


# ---------------------------------------------------------------------------
# Apply / aggregate
# ---------------------------------------------------------------------------


class ApplyWeightTests(unittest.TestCase):
    def test_apply_weight_scales_base_risk(self) -> None:
        backend_w = weight_for_stack("backend")
        result = apply_weight(10.0, backend_w)
        self.assertEqual(result, 10.0 * backend_w.multiplier)

    def test_apply_weight_rejects_negative_base(self) -> None:
        backend_w = weight_for_stack("backend")
        with self.assertRaises(StackRiskError):
            apply_weight(-1.0, backend_w)

    def test_aggregate_weights_max_strategy(self) -> None:
        paths = ["src/foo.py", "tests/test_foo.py", "docs/x.md"]
        multiplier = aggregate_weights(paths, strategy="max")
        backend_mult = weight_for_stack("backend").multiplier
        self.assertEqual(multiplier, backend_mult)

    def test_aggregate_weights_mean_strategy(self) -> None:
        paths = ["src/foo.py", "src/bar.py"]
        multiplier = aggregate_weights(paths, strategy="mean")
        backend_mult = weight_for_stack("backend").multiplier
        self.assertAlmostEqual(multiplier, backend_mult)

    def test_aggregate_weights_weighted_strategy(self) -> None:
        # Two backend, one docs: weighted mean should be closer to backend mult
        paths = ["src/foo.py", "src/bar.py", "docs/x.md"]
        weighted = aggregate_weights(paths, strategy="weighted")
        backend_mult = weight_for_stack("backend").multiplier
        docs_mult = weight_for_stack("docs").multiplier
        expected = (backend_mult * 2 + docs_mult * 1) / 3
        self.assertAlmostEqual(weighted, expected)

    def test_aggregate_weights_unknown_strategy(self) -> None:
        with self.assertRaises(StackRiskError):
            aggregate_weights(["src/foo.py"], strategy="bogus")

    def test_aggregate_weights_empty_returns_neutral(self) -> None:
        self.assertEqual(aggregate_weights([], strategy="max"), 1.0)
        self.assertEqual(aggregate_weights([], strategy="mean"), 1.0)
        self.assertEqual(aggregate_weights([], strategy="weighted"), 1.0)

    def test_risk_multiplier_for_path_set(self) -> None:
        mult = risk_multiplier(["src/foo.py"])
        self.assertEqual(mult, weight_for_stack("backend").multiplier)


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


class ExplainTests(unittest.TestCase):
    def test_explain_classification_lists_groups(self) -> None:
        text = explain_classification(["src/foo.py", "tests/test_foo.py"])
        self.assertIn("backend", text)
        self.assertIn("tests", text)
        self.assertIn("src/foo.py", text)

    def test_explain_classification_empty(self) -> None:
        text = explain_classification([])
        self.assertIn("no paths", text.lower())


# ---------------------------------------------------------------------------
# Validation + registration
# ---------------------------------------------------------------------------


class ValidationTests(unittest.TestCase):
    def test_validate_taxonomy_passes_default(self) -> None:
        validate_taxonomy(DEFAULT_PATH_TAXONOMY)

    def test_validate_taxonomy_rejects_empty(self) -> None:
        with self.assertRaises(StackRiskError):
            validate_taxonomy({})

    def test_validate_taxonomy_rejects_non_list_patterns(self) -> None:
        with self.assertRaises(StackRiskError):
            validate_taxonomy({"backend": "not-a-list"})  # type: ignore[arg-type]

    def test_validate_weights_passes_default(self) -> None:
        validate_weights(DEFAULT_STACK_WEIGHTS)

    def test_validate_weights_rejects_negative(self) -> None:
        bad = {"backend": StackWeight(stack="backend", multiplier=-1.0)}
        with self.assertRaises(StackRiskError):
            validate_weights(bad)

    def test_validate_weights_rejects_empty(self) -> None:
        with self.assertRaises(StackRiskError):
            validate_weights({})

    def test_register_stack_adds_entry(self) -> None:
        registry: dict[str, StackWeight] = {}
        register_stack(registry, "custom", 1.5)
        self.assertIn("custom", registry)
        self.assertEqual(registry["custom"].multiplier, 1.5)

    def test_register_stack_rejects_duplicate(self) -> None:
        registry = {"custom": StackWeight(stack="custom", multiplier=1.5)}
        with self.assertRaises(StackRiskError):
            register_stack(registry, "custom", 2.0)

    def test_register_stack_rejects_blank_id(self) -> None:
        registry: dict[str, StackWeight] = {}
        with self.assertRaises(StackRiskError):
            register_stack(registry, "", 1.0)

    def test_register_stack_rejects_negative_multiplier(self) -> None:
        registry: dict[str, StackWeight] = {}
        with self.assertRaises(StackRiskError):
            register_stack(registry, "custom", -0.1)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_classify_path_is_pure(self) -> None:
        a = classify_path("src/foo.py")
        b = classify_path("src/foo.py")
        self.assertEqual(a, b)

    def test_aggregate_is_pure(self) -> None:
        paths = ["src/foo.py", "tests/test_foo.py"]
        a = aggregate_weights(paths, strategy="weighted")
        b = aggregate_weights(paths, strategy="weighted")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
