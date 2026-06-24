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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(timeout=1),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(any("cmd builder" in f for f in outcome.evidence.get("findings", [])))
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                cfg,
                self.tmpdir,
                _profile(),
                "gate-001",
                self.project_root,
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
                    cfg,
                    self.tmpdir,
                    _profile(),
                    "gate-001",
                    self.project_root,
                )


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True,
        check=True,
    )
    (path / "src.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
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
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="b",
                tool="python3",
                category="static",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness", "static"]),
                reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"a", "b"})
        self.assertTrue(all(o.evidence["status"] == "ok" for o in outcomes))

    def test_skips_non_applicable_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="b",
                tool="python3",
                category="performance",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.collector_id, "a")

    def test_empty_registry_returns_empty(self) -> None:
        reg = CollectorRegistry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertEqual(outcomes, [])

    def test_evidence_persisted_to_disk(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_mixed_pass_and_fail(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="pass",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="fail",
                tool="python3",
                category="security",
                build_cmd=_fail_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness", "security"]),
                reg,
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
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=capture_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
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
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="b",
                tool="python3",
                category="security",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness", "security"]),
                reg,
                diff_categories={"correctness"},
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.category, "correctness")

    def test_diff_scope_empty_skips_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
                diff_categories=set(),
            )
        self.assertEqual(outcomes, [])

    def test_diff_scope_none_runs_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
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
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_fail_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="b",
                tool="python3",
                category="security",
                build_cmd=_fail_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness", "security"]),
                reg,
            )
        self.assertTrue(all(o.evidence["status"] == "violation" for o in outcomes))

    def test_binary_not_found_produces_error(self) -> None:
        def missing_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["nonexistent-binary-xyz-999"]

        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="missing",
                tool="python3",
                category="correctness",
                build_cmd=missing_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")

    def test_build_cmd_exception_produces_error(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="broken",
                tool="python3",
                category="correctness",
                build_cmd=_error_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")
        self.assertIsNotNone(outcomes[0].persisted_path)
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_one_collector_crash_does_not_kill_others(self) -> None:
        """Phase 1 crash isolation: an Exception from run_single_collector
        is caught and surfaced as an ``error`` evidence record; remaining
        collectors still run."""
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="boom",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="ok",
                tool="python3",
                category="static",
                build_cmd=_ok_cmd,
            )
        )

        original = collector_runner.run_single_collector
        call_count = {"n": 0}

        def crashing_runner(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            cfg = kwargs.get("config") or args[0]
            if cfg.collector_id == "boom":
                raise RuntimeError("synthetic crash")
            return original(*args, **kwargs)

        with (
            patch.dict(os.environ, _host_env(), clear=True),
            _patch.object(
                collector_runner,
                "run_single_collector",
                side_effect=crashing_runner,
            ),
        ):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness", "static"]),
                reg,
            )

        self.assertEqual(len(outcomes), 2)
        statuses = {o.config.collector_id: o.evidence["status"] for o in outcomes}
        self.assertEqual(statuses["boom"], "error")
        self.assertEqual(statuses["ok"], "ok")
        # The crash must surface in findings, not be silently dropped.
        boom = next(o for o in outcomes if o.config.collector_id == "boom")
        self.assertTrue(any("synthetic crash" in f for f in boom.evidence.get("findings", [])))

    def test_collector_crash_keyboardinterrupt_propagates(self) -> None:
        """Operator signals (KeyboardInterrupt/SIGTERM/SystemExit) must
        bubble — only ``Exception`` subclasses are isolated."""
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="signal",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )

        def signal_runner(*args: Any, **kwargs: Any) -> Any:
            raise KeyboardInterrupt()

        with (
            patch.dict(os.environ, _host_env(), clear=True),
            _patch.object(
                collector_runner,
                "run_single_collector",
                side_effect=signal_runner,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_gate_collectors(
                    self.project_root,
                    "gate-001",
                    self.sha,
                    self._profile(["correctness"]),
                    reg,
                )

    def test_multiple_collectors_same_category(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="lint-a",
                tool="python3",
                category="static",
                build_cmd=_ok_cmd,
            )
        )
        reg.register(
            CollectorConfig(
                collector_id="lint-b",
                tool="python3",
                category="static",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["static"]),
                reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"lint-a", "lint-b"})


class G2DispatchValidationTests(unittest.TestCase):
    """Stage 3 — early kwarg validation + dispatch on ``isolation_mode``.

    Covers spec §7.1 AC-D-01..AC-D-04. Validation must occur BEFORE
    ``assert_host_context`` (i.e., before any host/child decision) AND
    before any registry filtering — both modes are type-validated even
    though ``max_workers`` only affects the per_unit executor.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-g2-dispatch-")
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

    # AC-D-03 — invalid isolation_mode must raise BEFORE assert_host_context.
    def test_ac_d_03_invalid_isolation_mode_raises_before_host_check(self) -> None:
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        # Even with an empty registry, validation must fire first; we
        # patch assert_host_context to make any reach there observable.
        with _patch.object(
            collector_runner,
            "assert_host_context",
        ) as host_check:
            with self.assertRaises(ValueError):
                run_gate_collectors(
                    self.project_root,
                    "gate-001",
                    self.sha,
                    self._profile(["correctness"]),
                    reg,
                    isolation_mode="bogus",  # type: ignore[arg-type]
                )
            host_check.assert_not_called()

    # AC-D-04 — max_workers="four" raises TypeError in BOTH shared AND
    # per_unit modes; both must be type-validated even though only
    # per_unit consumes the value.
    def test_ac_d_04_max_workers_string_raises_in_shared(self) -> None:
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        with _patch.object(
            collector_runner,
            "assert_host_context",
        ) as host_check:
            with self.assertRaises(TypeError):
                run_gate_collectors(
                    self.project_root,
                    "gate-001",
                    self.sha,
                    self._profile(["correctness"]),
                    reg,
                    isolation_mode="shared",
                    max_workers="four",  # type: ignore[arg-type]
                )
            host_check.assert_not_called()

    def test_ac_d_04_max_workers_string_raises_in_per_unit(self) -> None:
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        with _patch.object(
            collector_runner,
            "assert_host_context",
        ) as host_check:
            with self.assertRaises(TypeError):
                run_gate_collectors(
                    self.project_root,
                    "gate-001",
                    self.sha,
                    self._profile(["correctness"]),
                    reg,
                    isolation_mode="per_unit",
                    max_workers="four",  # type: ignore[arg-type]
                )
            host_check.assert_not_called()

    # AC-V-03 — bool is a subclass of int and must be rejected explicitly.
    def test_max_workers_bool_raises_type_error(self) -> None:
        from unittest.mock import patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        with _patch.object(
            collector_runner,
            "assert_host_context",
        ) as host_check:
            with self.assertRaises(TypeError):
                run_gate_collectors(
                    self.project_root,
                    "gate-001",
                    self.sha,
                    self._profile(["correctness"]),
                    reg,
                    isolation_mode="shared",
                    max_workers=True,  # type: ignore[arg-type]
                )
            host_check.assert_not_called()

    # AC-D-02 — isolation_mode="per_unit" reaches run_collectors_per_unit.
    def test_ac_d_02_per_unit_routes_to_isolation_runner(self) -> None:
        from unittest.mock import patch as _patch

        from story_automator.core import collector_isolation

        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )

        captured: dict[str, Any] = {}

        def fake_per_unit(
            project_root: Any,
            gate_id: str,
            commit_sha: str,
            profile: dict[str, Any],
            collectors: list[CollectorConfig],
            *,
            max_workers: int = 4,
            audit_policy: Any = None,
            audit_path: Any = None,
        ) -> list[CollectorOutcome]:
            captured.update(
                project_root=project_root,
                gate_id=gate_id,
                commit_sha=commit_sha,
                profile=profile,
                collectors=collectors,
                max_workers=max_workers,
                audit_policy=audit_policy,
                audit_path=audit_path,
            )
            return []

        # Ensure that the dispatch picks up our patched function. The
        # production code imports it lazily inside the dispatch branch.
        with (
            patch.dict(os.environ, _host_env(), clear=True),
            _patch.object(
                collector_isolation,
                "run_collectors_per_unit",
                side_effect=fake_per_unit,
            ) as routed,
        ):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
                isolation_mode="per_unit",
                max_workers=2,
            )
        self.assertEqual(outcomes, [])
        routed.assert_called_once()
        self.assertEqual(captured["gate_id"], "gate-001")
        self.assertEqual(captured["commit_sha"], self.sha)
        self.assertEqual(captured["max_workers"], 2)
        self.assertEqual(len(captured["collectors"]), 1)
        self.assertEqual(captured["collectors"][0].collector_id, "a")

    # AC-D-01 — default isolation_mode="shared" preserves the existing
    # inline path (collector_checkout entered exactly once).
    def test_ac_d_01_default_shared_uses_inline_path(self) -> None:
        from unittest.mock import MagicMock, patch as _patch

        from story_automator.core import collector_runner

        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )

        # Wrap collector_checkout with a MagicMock so we can assert it
        # is entered exactly once for the shared path.
        original_cm = collector_runner.collector_checkout

        ckt_mock = MagicMock(side_effect=original_cm)

        with (
            patch.dict(os.environ, _host_env(), clear=True),
            _patch.object(
                collector_runner,
                "collector_checkout",
                ckt_mock,
            ),
        ):
            outcomes = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
        self.assertEqual(len(outcomes), 1)
        # Existing shared-mode path called collector_checkout once.
        ckt_mock.assert_called_once()

    # AC-D-01 supplement — explicit isolation_mode="shared" yields the
    # same byte-identical outcome surface as the default.
    def test_ac_d_01_explicit_shared_matches_default(self) -> None:
        reg = CollectorRegistry()
        reg.register(
            CollectorConfig(
                collector_id="a",
                tool="python3",
                category="correctness",
                build_cmd=_ok_cmd,
            )
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            default = run_gate_collectors(
                self.project_root,
                "gate-001",
                self.sha,
                self._profile(["correctness"]),
                reg,
            )
            explicit = run_gate_collectors(
                self.project_root,
                "gate-002",
                self.sha,
                self._profile(["correctness"]),
                reg,
                isolation_mode="shared",
                max_workers=4,
            )
        self.assertEqual(len(default), 1)
        self.assertEqual(len(explicit), 1)
        self.assertEqual(default[0].evidence["status"], "ok")
        self.assertEqual(explicit[0].evidence["status"], "ok")
        self.assertEqual(
            default[0].config.collector_id,
            explicit[0].config.collector_id,
        )


if __name__ == "__main__":
    unittest.main()
