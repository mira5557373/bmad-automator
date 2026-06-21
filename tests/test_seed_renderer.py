"""Tests for seed_renderer module — variable resolution, file listing, rendering, instantiation."""

from __future__ import annotations

import unittest

from story_automator.core.seed_renderer import (
    SeedRenderError,
    list_template_files,
    render_template_content,
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


def _make_multi_category_manifest():
    return {
        "schema_version": 1,
        "template_id": "test",
        "template_version": "1.0.0",
        "categories": {
            "contracts": {
                "description": "Contract tests",
                "files": [
                    {"src": "c/conftest.py.tmpl", "dst": "tests/contracts/conftest.py"},
                    {"src": "c/pact.py.tmpl", "dst": "tests/contracts/pact.py", "on_conflict": "overwrite"},
                ],
            },
            "network": {
                "description": "Network interception",
                "files": [
                    {"src": "n/net.py.tmpl", "dst": "tests/network/net.py"},
                ],
            },
            "empty": {
                "description": "Empty category",
                "files": [],
            },
        },
    }


class ListTemplateFilesTests(unittest.TestCase):
    def test_list_all_files(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m)
        self.assertEqual(len(result), 3)
        categories = {e["category"] for e in result}
        self.assertEqual(categories, {"contracts", "network"})

    def test_filter_by_category(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="contracts")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(e["category"] == "contracts" for e in result))

    def test_unknown_category_raises(self):
        m = _make_multi_category_manifest()
        with self.assertRaises(SeedRenderError):
            list_template_files(m, category="nonexistent")

    def test_default_on_conflict(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="network")
        self.assertEqual(result[0]["on_conflict"], "skip")

    def test_explicit_on_conflict(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="contracts")
        overwrite_entries = [e for e in result if e["on_conflict"] == "overwrite"]
        self.assertEqual(len(overwrite_entries), 1)

    def test_empty_category_files(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="empty")
        self.assertEqual(result, [])


class RenderTemplateContentTests(unittest.TestCase):
    def test_simple_substitution(self):
        self.assertEqual(
            render_template_content("Hello $name", {"name": "World"}),
            "Hello World",
        )

    def test_braced_substitution(self):
        self.assertEqual(
            render_template_content("${service}_api", {"service": "erp"}),
            "erp_api",
        )

    def test_dollar_escape(self):
        self.assertEqual(
            render_template_content("Price: $$5", {}),
            "Price: $5",
        )

    def test_missing_var_safe(self):
        self.assertEqual(
            render_template_content("Hello $unknown", {}),
            "Hello $unknown",
        )

    def test_empty_content(self):
        self.assertEqual(render_template_content("", {"x": "y"}), "")

    def test_multiline(self):
        tpl = "line1: $a\nline2: $b"
        result = render_template_content(tpl, {"a": "X", "b": "Y"})
        self.assertEqual(result, "line1: X\nline2: Y")

    def test_no_variables_passthrough(self):
        plain = "no variables here"
        self.assertEqual(render_template_content(plain, {}), plain)


if __name__ == "__main__":
    unittest.main()
