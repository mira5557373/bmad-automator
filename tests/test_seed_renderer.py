"""Tests for seed_renderer module — variable resolution, file listing, rendering, instantiation."""

from __future__ import annotations

import unittest

import shutil
import tempfile
from pathlib import Path

from story_automator.core.seed_renderer import (
    InstantiationResult,
    SeedRenderError,
    instantiate_template,
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

    def test_non_string_provided_raises(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        with self.assertRaises(SeedRenderError):
            resolve_variables(m, {"name": 123})

    def test_non_string_default_raises(self):
        m = _make_manifest_with_vars({"port": {"default": 8080}})
        with self.assertRaises(SeedRenderError):
            resolve_variables(m, {})


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
                    {
                        "src": "c/pact.py.tmpl",
                        "dst": "tests/contracts/pact.py",
                        "on_conflict": "overwrite",
                    },
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


class InstantiateTemplateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._bundle = Path(self._tmp) / "bundle"
        self._target = Path(self._tmp) / "target"
        self._bundle.mkdir()
        self._target.mkdir()
        self._manifest = {
            "schema_version": 1,
            "template_id": "test",
            "template_version": "1.0.0",
            "variables": {"product_name": {"required": True}},
            "categories": {
                "cat1": {
                    "description": "Category 1",
                    "files": [
                        {"src": "cat1/hello.py.tmpl", "dst": "src/hello.py"},
                    ],
                },
                "cat2": {
                    "description": "Category 2",
                    "files": [
                        {"src": "cat2/world.py.tmpl", "dst": "lib/world.py"},
                    ],
                },
            },
        }
        cat1_dir = self._bundle / "cat1"
        cat1_dir.mkdir()
        (cat1_dir / "hello.py.tmpl").write_text(
            '# $product_name\nprint("hello")\n', encoding="utf-8"
        )
        cat2_dir = self._bundle / "cat2"
        cat2_dir.mkdir()
        (cat2_dir / "world.py.tmpl").write_text(
            '# $product_name\nprint("world")\n', encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_basic_instantiation(self):
        instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "MyApp"},
        )
        dst = self._target / "src" / "hello.py"
        self.assertTrue(dst.is_file())
        self.assertIn("MyApp", dst.read_text(encoding="utf-8"))

    def test_creates_parent_dirs(self):
        instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "X"},
        )
        self.assertTrue((self._target / "src").is_dir())
        self.assertTrue((self._target / "lib").is_dir())

    def test_multiple_files(self):
        result = instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "X"},
            category="cat1",
        )
        self.assertEqual(len(result.written), 1)

    def test_multiple_categories(self):
        result = instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "X"},
        )
        self.assertEqual(len(result.written), 2)

    def test_filter_by_category(self):
        result = instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "X"},
            category="cat2",
        )
        self.assertEqual(len(result.written), 1)
        self.assertIn("lib/world.py", result.written[0])

    def test_rendered_content(self):
        instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "ACME"},
        )
        content = (self._target / "src" / "hello.py").read_text(encoding="utf-8")
        self.assertIn("ACME", content)
        self.assertNotIn("$product_name", content)

    def test_result_tracks_written(self):
        result = instantiate_template(
            self._bundle,
            self._manifest,
            self._target,
            {"product_name": "X"},
        )
        self.assertEqual(len(result.written), 2)
        self.assertEqual(len(result.skipped), 0)
        self.assertEqual(len(result.errors), 0)

    def test_instantiation_result_fields(self):
        r = InstantiationResult()
        self.assertEqual(r.written, [])
        self.assertEqual(r.skipped, [])
        self.assertEqual(r.errors, [])


class InstantiationSafeguardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._bundle = Path(self._tmp) / "bundle"
        self._target = Path(self._tmp) / "target"
        self._bundle.mkdir()
        self._target.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _manifest_with_file(self, src, dst, on_conflict="skip"):
        return {
            "schema_version": 1,
            "template_id": "test",
            "template_version": "1.0.0",
            "categories": {
                "c": {
                    "description": "cat",
                    "files": [{"src": src, "dst": dst, "on_conflict": on_conflict}],
                }
            },
        }

    def test_skip_existing_file(self):
        (self._bundle / "a.tmpl").write_text("new", encoding="utf-8")
        dst = self._target / "a.py"
        dst.write_text("old", encoding="utf-8")
        m = self._manifest_with_file("a.tmpl", "a.py", "skip")
        result = instantiate_template(self._bundle, m, self._target, {})
        self.assertEqual(dst.read_text(encoding="utf-8"), "old")
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.written), 0)

    def test_overwrite_existing_file(self):
        (self._bundle / "a.tmpl").write_text("new", encoding="utf-8")
        dst = self._target / "a.py"
        dst.write_text("old", encoding="utf-8")
        m = self._manifest_with_file("a.tmpl", "a.py", "overwrite")
        result = instantiate_template(self._bundle, m, self._target, {})
        self.assertEqual(dst.read_text(encoding="utf-8"), "new")
        self.assertEqual(len(result.written), 1)
        self.assertEqual(len(result.skipped), 0)

    def test_dst_path_traversal_blocked(self):
        (self._bundle / "a.tmpl").write_text("x", encoding="utf-8")
        m = self._manifest_with_file("a.tmpl", "../../etc/passwd")
        with self.assertRaises(SeedRenderError):
            instantiate_template(self._bundle, m, self._target, {})

    def test_src_path_traversal_blocked(self):
        m = self._manifest_with_file("../../secrets.py", "out.py")
        with self.assertRaises(SeedRenderError):
            instantiate_template(self._bundle, m, self._target, {})

    def test_missing_src_recorded_as_error(self):
        m = self._manifest_with_file("missing.tmpl", "out.py")
        result = instantiate_template(self._bundle, m, self._target, {})
        self.assertEqual(len(result.errors), 1)
        self.assertIn("missing.tmpl", result.errors[0])

    def test_binary_src_recorded_as_error(self):
        (self._bundle / "bin.tmpl").write_bytes(b"\x80\x81\x82\xff")
        m = self._manifest_with_file("bin.tmpl", "out.py")
        result = instantiate_template(self._bundle, m, self._target, {})
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.written), 0)


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = (
    REPO_ROOT
    / "skills"
    / "bmad-story-automator"
    / "data"
    / "templates"
    / "msme-erp-golden-template"
)
STANDARD_VARS = {
    "product_name": "TestProduct",
    "service_prefix": "tst",
    "health_port": "9090",
    "otel_endpoint": "http://otel:4317",
    "pact_broker_url": "http://pact:9292",
    "db_name": "test_db",
}


class ContractTemplateRenderTests(unittest.TestCase):
    def _render(self, src_file):
        content = (TEMPLATE_DIR / src_file).read_text(encoding="utf-8")
        return render_template_content(content, STANDARD_VARS)

    def test_conftest_renders(self):
        out = self._render("contracts/conftest.py.tmpl")
        self.assertIn("tst", out)
        self.assertNotIn("$service_prefix", out)

    def test_pact_consumer_renders(self):
        out = self._render("contracts/pact_consumer.py.tmpl")
        self.assertIn("tst", out)

    def test_network_first_renders(self):
        out = self._render("network/network_first.py.tmpl")
        self.assertIn("tst", out)

    def test_har_recorder_renders(self):
        out = self._render("network/har_recorder.py.tmpl")
        self.assertIn("har", out.lower())


class ResilienceFactoryObservabilityTemplateTests(unittest.TestCase):
    def _render(self, src_file):
        content = (TEMPLATE_DIR / src_file).read_text(encoding="utf-8")
        return render_template_content(content, STANDARD_VARS)

    def test_selectors_renders(self):
        out = self._render("resilience/selectors.py.tmpl")
        self.assertIn("data-testid", out)

    def test_factory_base_renders(self):
        out = self._render("factories/factory_base.py.tmpl")
        self.assertIn("cleanup", out.lower())
        self.assertIn("test_db", out)

    def test_otel_setup_renders(self):
        out = self._render("observability/otel_setup.py.tmpl")
        self.assertIn("tst", out)
        self.assertIn("http://otel:4317", out)

    def test_health_endpoints_renders(self):
        out = self._render("observability/health_endpoints.py.tmpl")
        self.assertIn("healthz", out)
        self.assertIn("readyz", out)

    def test_slo_config_renders(self):
        out = self._render("observability/slo_config.yaml.tmpl")
        self.assertIn("tst", out)


class EndToEndIntegrationTests(unittest.TestCase):
    """Full round-trip: load profile → resolve template → instantiate → verify."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._target = Path(self._tmp) / "project"
        self._target.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_full_round_trip(self):
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.seed_template import seed_template_for_profile

        profile = load_bundled_profile("msme-erp")
        manifest, bundle_dir = seed_template_for_profile(profile)
        self.assertIsNotNone(manifest)

        result = instantiate_template(
            bundle_dir,
            manifest,
            self._target,
            {"product_name": "TestERP", "service_prefix": "erp"},
        )
        self.assertEqual(len(result.written), 9)
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.errors, [])

    def test_round_trip_skip_existing(self):
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.seed_template import seed_template_for_profile

        profile = load_bundled_profile("msme-erp")
        manifest, bundle_dir = seed_template_for_profile(profile)

        pre_existing = self._target / "tests" / "contracts" / "conftest.py"
        pre_existing.parent.mkdir(parents=True)
        pre_existing.write_text("existing", encoding="utf-8")

        result = instantiate_template(
            bundle_dir,
            manifest,
            self._target,
            {"product_name": "TestERP", "service_prefix": "erp"},
        )
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.written), 8)
        self.assertEqual(pre_existing.read_text(encoding="utf-8"), "existing")

    def test_default_profile_no_op(self):
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.seed_template import seed_template_for_profile

        profile = load_bundled_profile("default")
        manifest, bundle_dir = seed_template_for_profile(profile)
        self.assertIsNone(manifest)
        self.assertIsNone(bundle_dir)

    def test_idempotent_skip(self):
        from story_automator.core.product_profile import load_bundled_profile
        from story_automator.core.seed_template import seed_template_for_profile

        profile = load_bundled_profile("msme-erp")
        manifest, bundle_dir = seed_template_for_profile(profile)
        variables = {"product_name": "TestERP", "service_prefix": "erp"}

        instantiate_template(bundle_dir, manifest, self._target, variables)
        result2 = instantiate_template(bundle_dir, manifest, self._target, variables)
        self.assertEqual(len(result2.skipped), 9)
        self.assertEqual(result2.written, [])


if __name__ == "__main__":
    unittest.main()
