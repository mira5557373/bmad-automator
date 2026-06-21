from __future__ import annotations

import os
import tempfile
import unittest


class LoadYamlRegistryTests(unittest.TestCase):
    def test_loads_simple_entries(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
            "\n"
            "- id: DG-13\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg13.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            path = f.name
        try:
            entries = load_yaml_registry(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["id"], "DG-12")
            self.assertEqual(entries[0]["check_type"], "semgrep")
            self.assertEqual(entries[1]["id"], "DG-13")
        finally:
            os.unlink(path)

    def test_skips_comments_and_blanks(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        content = (
            "# This is a comment\n"
            "\n"
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            path = f.name
        try:
            entries = load_yaml_registry(path)
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        entries = load_yaml_registry("/nonexistent/path.yaml")
        self.assertEqual(entries, [])

    def test_loads_real_msme_registry(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry
        from pathlib import Path

        registry_path = (
            Path(__file__).resolve().parent.parent
            / "skills" / "bmad-story-automator" / "data"
            / "profiles" / "msme-erp.invariants.yaml"
        )
        if not registry_path.exists():
            self.skipTest("msme-erp.invariants.yaml not found")
        entries = load_yaml_registry(str(registry_path))
        self.assertGreaterEqual(len(entries), 6)
        ids = [e["id"] for e in entries]
        self.assertIn("DG-12", ids)
        self.assertIn("DG-25", ids)


class ValidateRegistryTests(unittest.TestCase):
    def test_valid_entries_pass(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "semgrep",
             "rule_file": "semgrep/dg12.yml", "severity": "FAIL"},
        ]
        ok, errors = validate_registry(entries)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_invalid_severity_fails(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "semgrep",
             "rule_file": "semgrep/dg12.yml", "severity": "BAD"},
        ]
        ok, errors = validate_registry(entries)
        self.assertFalse(ok)
        self.assertTrue(any("severity" in e.lower() for e in errors))

    def test_invalid_check_type_fails(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "unknown",
             "rule_file": "f.yml", "severity": "FAIL"},
        ]
        ok, errors = validate_registry(entries)
        self.assertFalse(ok)

    def test_non_checkable_skips_type_validation(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-99", "checkable": "no", "severity": "CONCERNS"},
        ]
        ok, errors = validate_registry(entries)
        self.assertTrue(ok)

    def test_empty_list_passes(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        ok, errors = validate_registry([])
        self.assertTrue(ok)
        self.assertEqual(errors, [])


class LoadInvariantRegistryTests(unittest.TestCase):
    def test_loads_from_profile_registry_file(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
            }
            entries = load_invariant_registry(profile, tmpdir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_registry_file_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        profile = {"invariants": {}}
        entries = load_invariant_registry(profile, "/tmp")
        self.assertEqual(entries, [])

    def test_no_invariants_key_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        entries = load_invariant_registry({}, "/tmp")
        self.assertEqual(entries, [])

    def test_filters_out_invalid_entries(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
            "\n"
            "- id: BAD-ENTRY\n"
            "  checkable: yes\n"
            "  check_type: unknown\n"
            "  rule_file: bad.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
            }
            entries = load_invariant_registry(profile, tmpdir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_absolute_path_used_directly(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-34\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg34.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            abs_path = f.name
        try:
            profile = {
                "invariants": {"registry_file": abs_path},
            }
            entries = load_invariant_registry(profile, "/nonexistent")
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(abs_path)
