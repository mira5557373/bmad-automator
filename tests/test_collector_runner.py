from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collector_runner import run_single_collector, run_gate_collectors


def _ok_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('all good')"]


def _fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import sys; print('bad'); sys.exit(1)"]


def _slow_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(60)"]


def _error_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    raise ValueError("cmd builder exploded")


def _host_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("STORY_AUTOMATOR_CHILD", None)
    return env


def _profile(timeout: int = 10) -> dict[str, Any]:
    return {"timeouts": {"correctness": timeout}}


class RunSingleCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-runner-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        (self.project_root / "_bmad" / "gate" / "evidence").mkdir(parents=True)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ok_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-ok",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertIsInstance(outcome, CollectorOutcome)
        self.assertEqual(outcome.evidence["status"], "ok")
        self.assertEqual(outcome.config.collector_id, "test-ok")
        self.assertIsNotNone(outcome.persisted_path)
        self.assertTrue(outcome.persisted_path.exists())

    def test_failing_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-fail",
            tool="python3",
            category="correctness",
            build_cmd=_fail_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "violation")
        self.assertGreater(len(outcome.evidence.get("findings", [])), 0)

    def test_timeout_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-timeout",
            tool="python3",
            category="correctness",
            build_cmd=_slow_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(timeout=1),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "timeout")

    def test_build_cmd_error(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-error",
            tool="python3",
            category="correctness",
            build_cmd=_error_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(
            any("cmd builder" in f for f in outcome.evidence.get("findings", []))
        )
        self.assertIsNotNone(outcome.persisted_path)
        self.assertTrue(outcome.persisted_path.exists())

    def test_emits_audit_event(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-audit",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        audit_path = self.project_root / "audit.jsonl"
        policy = {"security": {"audit_trail": True}}
        with patch.dict(os.environ, {**_host_env(), "BMAD_AUDIT_KEY": "test-key"}):
            run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
                audit_policy=policy,
                audit_path=audit_path,
            )
        self.assertTrue(audit_path.exists())
        import json
        line = audit_path.read_text().strip()
        record = json.loads(line)
        self.assertEqual(record["event"], "EvidenceCollected")

    def test_no_audit_when_not_configured(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-noaudit",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        audit_path = self.project_root / "audit.jsonl"
        with patch.dict(os.environ, _host_env(), clear=True):
            run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertFalse(audit_path.exists())

    def test_nondeterministic_flag_propagated(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-nondet",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
            deterministic=False,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertFalse(outcome.evidence["deterministic"])

    def test_deterministic_flag_default_true(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-det",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertTrue(outcome.evidence["deterministic"])

    def test_trust_boundary_enforced(self) -> None:
        from story_automator.core.trust_boundary import TrustBoundaryError

        cfg = CollectorConfig(
            collector_id="test-child",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                run_single_collector(
                    cfg, self.tmpdir, _profile(),
                    "gate-001", self.project_root,
                )


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
    (path / "src.py").write_text("x = 1\n")
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


class RunGateCollectorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-gate-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_runs_all_applicable_collectors(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "static"]), reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"a", "b"})
        self.assertTrue(all(o.evidence["status"] == "ok" for o in outcomes))

    def test_skips_non_applicable_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="performance",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.collector_id, "a")

    def test_empty_registry_returns_empty(self) -> None:
        reg = CollectorRegistry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(outcomes, [])

    def test_evidence_persisted_to_disk(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_mixed_pass_and_fail(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="pass", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="fail", tool="python3", category="security",
            build_cmd=_fail_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
            )
        statuses = {o.config.collector_id: o.evidence["status"] for o in outcomes}
        self.assertEqual(statuses["pass"], "ok")
        self.assertEqual(statuses["fail"], "violation")

    def test_checkout_path_passed_to_collectors(self) -> None:
        captured_paths: list[str] = []
        path_validity: list[bool] = []

        def capture_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            captured_paths.append(checkout)
            # Verify during execution (before cleanup) that path is valid
            path_validity.append(Path(checkout).is_dir())
            return [sys.executable, "-c", "pass"]

        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=capture_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(captured_paths), 1)
        self.assertEqual(len(path_validity), 1)
        self.assertTrue(path_validity[0])


class DiffScopedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-diff-runner-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_diff_scope_filters_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="security",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
                diff_categories={"correctness"},
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.category, "correctness")

    def test_diff_scope_empty_skips_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
                diff_categories=set(),
            )
        self.assertEqual(outcomes, [])

    def test_diff_scope_none_runs_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
                diff_categories=None,
            )
        self.assertEqual(len(outcomes), 1)


class EdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-edge-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_all_collectors_fail(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="security",
            build_cmd=_fail_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
            )
        self.assertTrue(
            all(o.evidence["status"] == "violation" for o in outcomes)
        )

    def test_binary_not_found_produces_error(self) -> None:
        def missing_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["nonexistent-binary-xyz-999"]

        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="missing", tool="python3", category="correctness",
            build_cmd=missing_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")

    def test_build_cmd_exception_produces_error(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="broken", tool="python3", category="correctness",
            build_cmd=_error_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")
        self.assertIsNotNone(outcomes[0].persisted_path)
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_multiple_collectors_same_category(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="lint-a", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="lint-b", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["static"]), reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"lint-a", "lint-b"})


if __name__ == "__main__":
    unittest.main()
