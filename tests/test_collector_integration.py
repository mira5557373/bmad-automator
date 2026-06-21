"""End-to-end collector framework integration tests.

Proves the full pipeline: registry → diff scope → doctor → checkout →
collector loop → evidence bundle → audit → verdict aggregation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_doctor import preflight_check
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collector_runner import run_gate_collectors
from story_automator.core.diff_scope import compute_diff_scope
from story_automator.core.evidence_io import (
    compute_evidence_bundle_hash,
    load_evidence_bundle,
)
from story_automator.core.gate_rules import (
    aggregate_verdicts,
    verdict_for_collector_status,
)


def _ok_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('all checks pass')"]


def _fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import sys; print('finding: bad code'); sys.exit(1)"]


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "app.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _add_commit(path: Path, filename: str, content: str) -> str:
    (path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", filename],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", f"add {filename}"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _host_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("STORY_AUTOMATOR_CHILD", None)
    return env


class FullPipelineTests(unittest.TestCase):
    """End-to-end: registry → run → evidence → bundle hash → verdicts."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-integration-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.base_sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": ["correctness", "static", "security"],
                "system": [],
            },
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def _registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="pytest-correctness",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        reg.register(CollectorConfig(
            collector_id="ruff-static",
            tool="python3",
            category="static",
            build_cmd=_ok_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_fail_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        return reg

    def test_full_pass_pipeline(self) -> None:
        profile = self._profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="check-ok",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            ok, _ = preflight_check(reg, profile)
            self.assertTrue(ok)

            outcomes = run_gate_collectors(
                self.project_root, "gate-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "ok")

        records = load_evidence_bundle(self.project_root, "gate-pass")
        self.assertEqual(len(records), 1)

        bundle_hash = compute_evidence_bundle_hash(records)
        self.assertEqual(len(bundle_hash), 16)

        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        overall = aggregate_verdicts(verdicts)
        self.assertEqual(overall, "PASS")

    def test_mixed_verdict_pipeline(self) -> None:
        profile = self._profile()
        reg = self._registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-mixed", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 3)

        records = load_evidence_bundle(self.project_root, "gate-mixed")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["correctness"], "PASS")
        self.assertEqual(verdicts["static"], "PASS")
        self.assertEqual(verdicts["security"], "FAIL")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_diff_scoped_pipeline(self) -> None:
        sha2 = _add_commit(self.project_root, "new.py", "y = 2\n")
        profile = self._profile()
        reg = self._registry()

        diff_cats = compute_diff_scope(
            self.project_root, self.base_sha, sha2,
        )
        self.assertIn("correctness", diff_cats)

        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-diff", sha2,
                profile, reg,
                diff_categories=diff_cats,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertTrue(run_cats.issubset(diff_cats))

    def test_consistent_statuses_across_runs(self) -> None:
        profile = self._profile()
        reg = self._registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-det1", self.base_sha,
                profile, reg,
            )
        records1 = load_evidence_bundle(self.project_root, "gate-det1")

        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-det2", self.base_sha,
                profile, reg,
            )
        records2 = load_evidence_bundle(self.project_root, "gate-det2")

        statuses1 = {r["category"]: r["status"] for r in records1}
        statuses2 = {r["category"]: r["status"] for r in records2}
        self.assertEqual(statuses1, statuses2)

    def test_audit_events_emitted(self) -> None:
        profile = self._profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        audit_path = self.project_root / "audit.jsonl"
        policy = {"security": {"audit_trail": True}}
        with patch.dict(os.environ, {**_host_env(), "BMAD_AUDIT_KEY": "k"}):
            run_gate_collectors(
                self.project_root, "gate-audit", self.base_sha,
                profile, reg,
                audit_policy=policy,
                audit_path=audit_path,
            )
        self.assertTrue(audit_path.exists())
        lines = audit_path.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event"], "EvidenceCollected")

    def test_kill_switch_excludes_collector(self) -> None:
        profile = {
            "categories": {"code": ["static"], "system": []},
            "categories_na": [],
            "rules": {"static": {"disabled_tools": ["ruff"]}},
            "timeouts": {},
        }
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="ruff", tool="ruff", category="static",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="mypy", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-kill", self.base_sha,
                profile, reg,
            )
        ids = [o.config.collector_id for o in outcomes]
        self.assertNotIn("ruff", ids)
        self.assertIn("mypy", ids)


class SecurityCategoryPipelineTests(unittest.TestCase):
    """Pipeline tests with security, license, compliance, supply_chain categories."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-sec-integration-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.base_sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _security_profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": ["security", "license", "compliance", "supply_chain"],
                "system": [],
            },
            "categories_na": [],
            "rules": {
                "security": {},
                "license": {"forbidden": ["BSL-1.1"], "boundary": {}},
                "compliance": {},
                "supply_chain": {},
            },
            "timeouts": {},
        }

    def _security_registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="license-check-license",
            tool="python3",
            category="license",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="compliance-rules-compliance",
            tool="python3",
            category="compliance",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="sbom-supply_chain",
            tool="python3",
            category="supply_chain",
            build_cmd=_ok_cmd,
        ))
        return reg

    def test_all_security_categories_pass(self) -> None:
        profile = self._security_profile()
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 4)
        for outcome in outcomes:
            self.assertEqual(outcome.evidence["status"], "ok")
        records = load_evidence_bundle(self.project_root, "gate-sec-pass")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(aggregate_verdicts(verdicts), "PASS")

    def test_security_fail_propagates(self) -> None:
        profile = self._security_profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="license-check-license",
            tool="python3",
            category="license",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-sec-fail", self.base_sha,
                profile, reg,
            )
        records = load_evidence_bundle(self.project_root, "gate-sec-fail")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["security"], "FAIL")
        self.assertEqual(verdicts["license"], "PASS")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_kill_switch_security_tool(self) -> None:
        profile = self._security_profile()
        profile["rules"]["security"]["disabled_tools"] = ["python3"]
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-kill", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("security", run_cats)
        self.assertIn("license", run_cats)

    def test_categories_na_excludes_compliance(self) -> None:
        profile = self._security_profile()
        profile["categories_na"] = ["compliance"]
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-na", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("compliance", run_cats)
        self.assertIn("security", run_cats)


if __name__ == "__main__":
    unittest.main()
