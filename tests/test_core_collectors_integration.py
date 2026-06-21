"""Integration test: core collectors -> registry -> runner -> evidence.

Verifies that the concrete core collectors register correctly, produce
valid build_cmd output, and when run with synthetic success/failure tools
through the M4 pipeline, produce well-formed evidence records.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collectors import register_core_collectors
from story_automator.core.evidence_io import (
    compute_evidence_bundle_hash,
    load_evidence_bundle,
)
from story_automator.core.gate_schema import validate_evidence_record


class CoreCollectorBuildCmdTests(unittest.TestCase):
    """Every registered collector must produce a valid command list."""

    def setUp(self) -> None:
        self.registry = CollectorRegistry()
        register_core_collectors(self.registry)
        self.profile: dict[str, Any] = {
            "matrix": {
                "P0": {"coverage_pct": 80, "levels": ["unit"]},
                "P1": {"coverage_pct": 60, "levels": ["unit"]},
                "P2": {"coverage_pct": 30, "levels": ["smoke"]},
                "P3": {"coverage_pct": 10, "levels": ["smoke"]},
            },
            "categories": {
                "code": ["correctness", "static", "docs", "process"],
            },
            "categories_na": [],
            "rules": {},
        }

    def test_all_build_cmds_return_string_lists(self) -> None:
        for config in self.registry.all_collectors():
            cmd = config.build_cmd("/tmp/checkout", self.profile)
            self.assertIsInstance(cmd, list, f"{config.collector_id}")
            self.assertTrue(
                all(isinstance(s, str) for s in cmd),
                f"{config.collector_id} returned non-string elements",
            )
            self.assertTrue(len(cmd) > 0, f"{config.collector_id} empty cmd")

    def test_checker_scripts_exist(self) -> None:
        for config in self.registry.all_collectors():
            cmd = config.build_cmd("/tmp/checkout", self.profile)
            if cmd[0] == sys.executable and len(cmd) > 1:
                script = cmd[1]
                self.assertTrue(
                    Path(script).is_file(),
                    f"{config.collector_id}: script not found: {script}",
                )


class CoreCollectorProfileFilteringTests(unittest.TestCase):
    """Profile-driven filtering works with real collector configs."""

    def setUp(self) -> None:
        self.registry = CollectorRegistry()
        register_core_collectors(self.registry)

    def test_all_four_categories_when_all_active(self) -> None:
        profile: dict[str, Any] = {
            "categories": {
                "code": ["correctness", "static", "docs", "process"],
            },
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"correctness", "static", "docs", "process"})

    def test_single_category(self) -> None:
        profile: dict[str, Any] = {
            "categories": {"code": ["correctness"]},
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        self.assertTrue(all(c.category == "correctness" for c in applicable))
        self.assertTrue(len(applicable) > 0)

    def test_empty_profile_returns_nothing(self) -> None:
        profile: dict[str, Any] = {
            "categories": {},
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        self.assertEqual(len(applicable), 0)


class CoreCollectorEvidenceTests(unittest.TestCase):
    """Checker-script collectors produce valid evidence via the pipeline."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir
        self.gate_id = "test-gate-001"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_presence_collector_pass(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            runbook = Path(checkout, "docs", "operations")
            runbook.mkdir(parents=True)
            (runbook / "gate-troubleshooting.md").write_text("# Runbook\n")
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            ev = outcome.evidence
            self.assertEqual(ev["status"], "ok")
            self.assertEqual(ev["collector"], "doc-presence-docs")
            self.assertEqual(ev["tool"], "python3")
            self.assertEqual(ev["category"], "docs")
            self.assertEqual(ev["exit_code"], 0)
            self.assertTrue(ev["deterministic"])
            validate_evidence_record(ev)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_presence_collector_violation(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            self.assertEqual(outcome.evidence["status"], "violation")
            self.assertTrue(
                any("MISSING" in f for f in outcome.evidence["findings"]),
            )
            validate_evidence_record(outcome.evidence)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_evidence_persistence_round_trip(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            self.assertIsNotNone(outcome.persisted_path)
            bundle = load_evidence_bundle(self.project_root, self.gate_id)
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0]["collector"], "doc-presence-docs")
            bundle_hash = compute_evidence_bundle_hash(bundle)
            self.assertTrue(len(bundle_hash) > 0)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
