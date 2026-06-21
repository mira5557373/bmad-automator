from __future__ import annotations

import os
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
from story_automator.core.collector_runner import run_single_collector


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


if __name__ == "__main__":
    unittest.main()
