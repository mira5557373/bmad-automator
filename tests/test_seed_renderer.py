"""Tests for seed_renderer module — variable resolution, file listing, rendering, instantiation."""

from __future__ import annotations

import unittest

from story_automator.core.seed_renderer import (
    SeedRenderError,
    resolve_variables,
)


def _make_manifest_with_vars(variables):
    """Return a manifest dict with the given variables section."""
    m = {
        "schema_version": 1,
        "template_id": "test",
        "template_version": "1.0.0",
        "categories": {
            "c": {
                "description": "cat",
                "files": [{"src": "a.tmpl", "dst": "a.py"}],
            }
        },
    }
    if variables is not None:
        m["variables"] = variables
    return m


class ResolveVariablesTests(unittest.TestCase):
    def test_required_provided(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        result = resolve_variables(m, {"name": "World"})
        self.assertEqual(result["name"], "World")

    def test_required_missing_raises(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        with self.assertRaises(SeedRenderError):
            resolve_variables(m, {})

    def test_optional_uses_default(self):
        m = _make_manifest_with_vars({"port": {"default": "8080"}})
        result = resolve_variables(m, {})
        self.assertEqual(result["port"], "8080")

    def test_provided_overrides_default(self):
        m = _make_manifest_with_vars({"port": {"default": "8080"}})
        result = resolve_variables(m, {"port": "3000"})
        self.assertEqual(result["port"], "3000")

    def test_no_variables_in_manifest(self):
        m = _make_manifest_with_vars(None)
        result = resolve_variables(m, {"extra": "val"})
        self.assertEqual(result, {"extra": "val"})

    def test_extra_provided_kept(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        result = resolve_variables(m, {"name": "X", "bonus": "Y"})
        self.assertIn("bonus", result)
        self.assertEqual(result["bonus"], "Y")

    def test_empty_provided_empty_manifest(self):
        m = _make_manifest_with_vars({})
        result = resolve_variables(m, {})
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
