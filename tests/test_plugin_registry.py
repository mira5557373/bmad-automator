"""Tests for declarative-only plugin registry (Path B compat layer, N6.4).

The registry loads TOML plugin manifests from ``_bmad/plugins/<name>.toml``,
validates them against an explicit allowlist, and surfaces hook commands
to the HookBusShim. Python-import plugins are rejected by design — that is
the trust boundary that justifies Path B over a full engine adoption.

These tests pin the public surface and the rejection rules so a future
contributor cannot quietly relax them.
"""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

from story_automator.core.plugins import (
    PLUGIN_MANIFEST_KEYS,
    PluginRegistry,
    PluginSpec,
    PluginTrustError,
)


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


_VALID_MANIFEST = """\
name = "example"
version = "1.0.0"

[hooks]
post_gate = "my-plugin --gate-id $BMAD_GATE_ID"
"""


class PluginSpecTests(unittest.TestCase):
    def test_pluginspec_is_frozen(self) -> None:
        spec = PluginSpec(
            name="example",
            version="1.0.0",
            manifest_path="/abs/path/example.toml",
            hooks={"post_gate": "cmd"},
        )
        with self.assertRaises(FrozenInstanceError):
            spec.version = "9.9.9"  # type: ignore[misc]

    def test_pluginspec_defaults(self) -> None:
        spec = PluginSpec(
            name="example",
            version="1.0.0",
            manifest_path="/abs/path/example.toml",
            hooks={},
        )
        self.assertEqual(spec.timeout_s, 30.0)
        self.assertFalse(spec.fail_closed)


class PluginManifestKeysTests(unittest.TestCase):
    def test_manifest_keys_constant(self) -> None:
        self.assertIsInstance(PLUGIN_MANIFEST_KEYS, frozenset)
        self.assertEqual(
            PLUGIN_MANIFEST_KEYS,
            frozenset({"name", "version", "hooks", "timeout_s", "fail_closed"}),
        )


class PluginRegistryLoadTests(unittest.TestCase):
    def test_empty_dir_returns_empty_list(self) -> None:
        with TemporaryDirectory() as td:
            reg = PluginRegistry(Path(td), allowlist=frozenset({"example"}))
            self.assertEqual(reg.load_all(), [])

    def test_load_valid_manifest_allowlist_match(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", _VALID_MANIFEST)
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            specs = reg.load_all()
            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].name, "example")
            self.assertEqual(specs[0].version, "1.0.0")
            self.assertEqual(
                specs[0].hooks,
                {"post_gate": "my-plugin --gate-id $BMAD_GATE_ID"},
            )

    def test_allowlist_mismatch_rejects(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "rogue.toml", _VALID_MANIFEST.replace("example", "rogue"))
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_python_import_key_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n'
                'python_module = "evil.module"\n'
                '[hooks]\npost_gate = "cmd"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_py_module_key_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n'
                'py_module = "evil.module"\n'
                '[hooks]\npost_gate = "cmd"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_unknown_key_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n'
                'bogus_field = "nope"\n'
                '[hooks]\npost_gate = "cmd"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_non_string_hook_value_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n[hooks]\npost_gate = 42\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_missing_required_key_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            # missing `version`
            _write(
                root / "example.toml",
                'name = "example"\n[hooks]\npost_gate = "cmd"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_malformed_toml_rejected(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", "this is = = not = toml [[[")
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            with self.assertRaises(PluginTrustError):
                reg.load_all()

    def test_timeout_default_is_thirty(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", _VALID_MANIFEST)
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            specs = reg.load_all()
            self.assertEqual(specs[0].timeout_s, 30.0)

    def test_fail_closed_default_false(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", _VALID_MANIFEST)
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            specs = reg.load_all()
            self.assertFalse(specs[0].fail_closed)

    def test_explicit_timeout_and_fail_closed_honored(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n'
                "timeout_s = 60.0\nfail_closed = true\n"
                '[hooks]\npost_gate = "cmd"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            specs = reg.load_all()
            self.assertEqual(specs[0].timeout_s, 60.0)
            self.assertTrue(specs[0].fail_closed)

    def test_manifest_path_is_absolute(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", _VALID_MANIFEST)
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            spec = reg.load_all()[0]
            self.assertTrue(Path(spec.manifest_path).is_absolute())

    def test_bmad_placeholder_preserved_verbatim(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root / "example.toml",
                'name = "example"\nversion = "1.0.0"\n[hooks]\n'
                'post_gate = "tool --id $BMAD_GATE_ID --story $BMAD_STORY"\n',
            )
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            spec = reg.load_all()[0]
            self.assertEqual(
                spec.hooks["post_gate"],
                "tool --id $BMAD_GATE_ID --story $BMAD_STORY",
            )


class PluginRegistryQueryTests(unittest.TestCase):
    def _build_registry_with_two(self) -> PluginRegistry:
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        _write(
            root / "alpha.toml",
            'name = "alpha"\nversion = "1.0.0"\n[hooks]\n'
            'post_gate = "alpha-tool"\npre_review = "alpha-review"\n',
        )
        _write(
            root / "beta.toml",
            'name = "beta"\nversion = "2.0.0"\n[hooks]\n'
            'post_gate = "beta-tool"\n',
        )
        reg = PluginRegistry(root, allowlist=frozenset({"alpha", "beta"}))
        reg.load_all()
        return reg

    def test_hooks_for_filters_by_event(self) -> None:
        reg = self._build_registry_with_two()
        post_gate = reg.hooks_for("post_gate")
        self.assertEqual(len(post_gate), 2)
        names = {n for n, _ in post_gate}
        self.assertEqual(names, {"alpha", "beta"})
        pre_review = reg.hooks_for("pre_review")
        self.assertEqual(pre_review, [("alpha", "alpha-review")])

    def test_hooks_for_unknown_event_returns_empty(self) -> None:
        reg = self._build_registry_with_two()
        self.assertEqual(reg.hooks_for("never_registered"), [])

    def test_list_plugins_sorted_by_name(self) -> None:
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        # write zebra first so insertion order ≠ sorted order
        _write(
            root / "zebra.toml",
            'name = "zebra"\nversion = "1.0.0"\n[hooks]\npost_gate = "z"\n',
        )
        _write(
            root / "alpha.toml",
            'name = "alpha"\nversion = "1.0.0"\n[hooks]\npost_gate = "a"\n',
        )
        _write(
            root / "mango.toml",
            'name = "mango"\nversion = "1.0.0"\n[hooks]\npost_gate = "m"\n',
        )
        reg = PluginRegistry(root, allowlist=frozenset({"zebra", "alpha", "mango"}))
        reg.load_all()
        self.assertEqual(
            [p.name for p in reg.list_plugins()],
            ["alpha", "mango", "zebra"],
        )

    def test_multiple_plugins_same_event_registration_order(self) -> None:
        """When two plugins both register `post_gate`, hooks_for must return
        them in deterministic order. We use sorted-by-name as the
        registration order so the dispatch chain is reproducible regardless
        of filesystem readdir ordering."""
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        _write(
            root / "zebra.toml",
            'name = "zebra"\nversion = "1.0.0"\n[hooks]\npost_gate = "z"\n',
        )
        _write(
            root / "alpha.toml",
            'name = "alpha"\nversion = "1.0.0"\n[hooks]\npost_gate = "a"\n',
        )
        reg = PluginRegistry(root, allowlist=frozenset({"zebra", "alpha"}))
        reg.load_all()
        order = [n for n, _ in reg.hooks_for("post_gate")]
        # Deterministic — sorted by plugin name.
        self.assertEqual(order, ["alpha", "zebra"])


class PluginRegistryIdempotencyTests(unittest.TestCase):
    def test_load_all_is_idempotent(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "example.toml", _VALID_MANIFEST)
            reg = PluginRegistry(root, allowlist=frozenset({"example"}))
            first = reg.load_all()
            second = reg.load_all()
            self.assertEqual([s.name for s in first], [s.name for s in second])
            self.assertEqual(len(first), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
