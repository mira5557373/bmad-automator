from __future__ import annotations

import os
import tempfile
import unittest


class EnrichProfileInvariantsTests(unittest.TestCase):
    def test_populates_registry_from_file(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

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
                "rules": {},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            registry = enriched["rules"]["invariants"]["registry"]
            self.assertEqual(len(registry), 1)
            self.assertEqual(registry[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_preserves_existing_rules(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        profile = {
            "invariants": {},
            "rules": {"security": {"sast_max_high": 0}},
        }
        enriched = enrich_profile_invariants(profile, "/tmp")
        self.assertEqual(enriched["rules"]["security"]["sast_max_high"], 0)

    def test_no_registry_file_leaves_empty(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        profile = {"invariants": {}, "rules": {}}
        enriched = enrich_profile_invariants(profile, "/tmp")
        registry = (enriched.get("rules") or {}).get("invariants", {}).get("registry", [])
        self.assertEqual(registry, [])

    def test_does_not_mutate_original(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

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
                "rules": {},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            self.assertNotIn("invariants", profile["rules"])
            self.assertIn("invariants", enriched["rules"])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_merges_with_existing_invariant_rules(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

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
                "rules": {"invariants": {"some_key": "some_value"}},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            inv_rules = enriched["rules"]["invariants"]
            self.assertEqual(inv_rules["some_key"], "some_value")
            self.assertEqual(len(inv_rules["registry"]), 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
