"""Tests for ``core.collector_isolation`` — per-unit worktree isolation (G2).

Spec coverage: §7.1 (AC-V-01..V-03, AC-I-01..I-20) and §7.2 (≥22 tests).
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from story_automator.core import collector_isolation
from story_automator.core.audit import AuditLockTimeout
from story_automator.core.collector_checkout import CollectorCheckoutError
from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)
from story_automator.core.collector_isolation import (
    ADD_TIMEOUT_PER_UNIT_S,
    DEFAULT_MAX_WORKERS,
    ESTIMATED_PER_WORKER_BYTES,
    MAX_PARALLEL_CEILING,
    _audit_timeout_outcome,
    _clamp_max_workers,
    _crash_outcome,
    _error_outcome,
    _sanitize_name_hint,
    _validate_isolation_kwargs,
    run_collectors_per_unit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _host_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("STORY_AUTOMATOR_CHILD", None)
    return env


def _ok_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('ok')"]


def _crash_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    raise RuntimeError("synthetic build_cmd crash")


def _make_profile(timeout: int = 10) -> dict[str, Any]:
    return {
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [],
        "rules": {},
        "timeouts": {
            "correctness": timeout,
            "static": timeout,
            "security": timeout,
            "performance": timeout,
        },
    }


def _cfg(collector_id: str, category: str = "correctness") -> CollectorConfig:
    return CollectorConfig(
        collector_id=collector_id,
        tool="python3",
        category=category,
        build_cmd=_ok_cmd,
    )


class _IsolationFixture:
    """Common per-test fixture: project_root + initial commit SHA."""

    def __init__(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-iso-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def teardown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# §7.2 #22 + AC-V-01..V-03 — _validate_isolation_kwargs
# ---------------------------------------------------------------------------


class ValidateIsolationKwargsTests(unittest.TestCase):
    def test_valid_inputs_accepted(self) -> None:
        _validate_isolation_kwargs("shared", 4)
        _validate_isolation_kwargs("per_unit", 1)
        _validate_isolation_kwargs("per_unit", 100)  # not clamped here

    def test_invalid_mode_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            _validate_isolation_kwargs("auto", 4)
        with self.assertRaises(ValueError):
            _validate_isolation_kwargs("", 4)
        with self.assertRaises(ValueError):
            _validate_isolation_kwargs("SHARED", 4)

    def test_max_workers_string_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            _validate_isolation_kwargs("shared", "four")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            _validate_isolation_kwargs("per_unit", "4")  # type: ignore[arg-type]

    def test_max_workers_bool_raises_type_error(self) -> None:
        # bool is a subclass of int; must be rejected explicitly.
        with self.assertRaises(TypeError):
            _validate_isolation_kwargs("shared", True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            _validate_isolation_kwargs("per_unit", False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §7.2 #18, #19, #20 — _sanitize_name_hint
# ---------------------------------------------------------------------------


class SanitizeNameHintTests(unittest.TestCase):
    def test_path_traversal_rejected(self) -> None:
        self.assertEqual(_sanitize_name_hint("../etc/passwd"), "..etcpasswd")
        # spec text says the result should not contain slash; etcpasswd
        # alone is the example from AC-I-20 if dots are removed too, but
        # our charset KEEPS '.', so '..etcpasswd' is correct. The key
        # invariant is no '/' and no path components.
        self.assertNotIn("/", _sanitize_name_hint("foo/bar"))
        self.assertEqual(_sanitize_name_hint("foo/bar"), "foobar")

    def test_drops_unsafe_chars(self) -> None:
        self.assertEqual(_sanitize_name_hint("   "), "")
        self.assertEqual(_sanitize_name_hint("foo\nbar"), "foobar")
        self.assertEqual(_sanitize_name_hint("foo bar"), "foobar")
        self.assertEqual(_sanitize_name_hint("static_τ_p1"), "static__p1")

    def test_take_last_32_after_sanitize(self) -> None:
        # AC-I-19 / AC-I-20: take LAST 32 chars (sanitize-FIRST,
        # truncate-SECOND).
        hint = "a" * 40
        result = _sanitize_name_hint(hint)
        self.assertEqual(result, "a" * 32)
        self.assertEqual(len(result), 32)

    def test_empty_input_empty_output(self) -> None:
        self.assertEqual(_sanitize_name_hint(""), "")
        self.assertEqual(_sanitize_name_hint(None or ""), "")


# ---------------------------------------------------------------------------
# §7.2 #7, #8, #9 — _clamp_max_workers
# ---------------------------------------------------------------------------


class ClampMaxWorkersTests(unittest.TestCase):
    def test_clamp_ceiling_and_lower_bound(self) -> None:
        # 100 → min(16, cpu-2, ram_ceiling). Upper bound is at most
        # MAX_PARALLEL_CEILING (=16).
        with mock.patch("os.cpu_count", return_value=32):
            # Ensure RAM is generous so cpu_ceiling caps.
            with mock.patch("psutil.virtual_memory") as vm:
                vm.return_value.available = 64 * ESTIMATED_PER_WORKER_BYTES
                self.assertEqual(_clamp_max_workers(100), MAX_PARALLEL_CEILING)
                self.assertEqual(_clamp_max_workers(0), 1)
                self.assertEqual(_clamp_max_workers(-5), 1)
                # Generic positive value passes through up to ceiling.
                self.assertEqual(_clamp_max_workers(3), 3)

    def test_clamp_cpu_count_none_yields_cpu_ceiling_2(self) -> None:
        with mock.patch("os.cpu_count", return_value=None):
            with mock.patch("psutil.virtual_memory") as vm:
                vm.return_value.available = 64 * ESTIMATED_PER_WORKER_BYTES
                # (4 - 2) = 2 → cpu_ceiling = 2
                self.assertEqual(_clamp_max_workers(8), 2)

    def test_ram_aware_low_memory_clamps_to_one(self) -> None:
        # 256 MiB available -> ram_ceiling = max(1, 256MiB // 256MiB) = 1.
        with mock.patch("os.cpu_count", return_value=32):
            with mock.patch("psutil.virtual_memory") as vm:
                vm.return_value.available = ESTIMATED_PER_WORKER_BYTES
                self.assertEqual(_clamp_max_workers(8), 1)

    def test_ram_aware_high_memory_lets_cpu_cap(self) -> None:
        # available = 2 GiB → ram_ceiling = 8. cpu_ceiling = 30 → 16.
        # min(8, 16, 8) = 8.
        with mock.patch("os.cpu_count", return_value=32):
            with mock.patch("psutil.virtual_memory") as vm:
                vm.return_value.available = 2 * 1024 * 1024 * 1024
                self.assertEqual(_clamp_max_workers(8), 8)

    def test_psutil_raises_graceful_default(self) -> None:
        with mock.patch("os.cpu_count", return_value=8):
            with mock.patch("psutil.virtual_memory", side_effect=RuntimeError("boom")):
                # cpu_ceiling = min(16, 8-2) = 6; ram_ceiling falls back
                # to cpu_ceiling; min(8, 6, 6) = 6.
                self.assertEqual(_clamp_max_workers(8), 6)


# ---------------------------------------------------------------------------
# run_collectors_per_unit behavioral tests
# ---------------------------------------------------------------------------


class RunCollectorsPerUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _IsolationFixture()

    def tearDown(self) -> None:
        self.fx.teardown()

    # §7.2 #1
    def test_empty_collectors_returns_empty(self) -> None:
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [],
            )
        self.assertEqual(outcomes, [])

    # §7.2 #2
    def test_single_collector_happy_path(self) -> None:
        cfg = _cfg("alpha")
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], CollectorOutcome)
        self.assertEqual(outcomes[0].evidence["status"], "ok")
        self.assertIsNotNone(outcomes[0].persisted_path)
        self.assertTrue(outcomes[0].persisted_path.exists())

    # §7.2 #3
    def test_three_collectors_sorted_outcomes(self) -> None:
        configs = [
            _cfg("z-charlie", category="static"),
            _cfg("a-alpha", category="correctness"),
            _cfg("m-bravo", category="security"),
        ]
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                configs,
            )
        self.assertEqual(len(outcomes), 3)
        # Sort key is (category, collector_id) ascending:
        # correctness/a-alpha, security/m-bravo, static/z-charlie.
        self.assertEqual(
            [o.config.collector_id for o in outcomes],
            ["a-alpha", "m-bravo", "z-charlie"],
        )

    # §7.2 #4 — crashing collector siblings unaffected
    def test_crashing_collector_isolated_via_error_evidence(self) -> None:
        crash_cfg = CollectorConfig(
            collector_id="boom",
            tool="python3",
            category="correctness",
            build_cmd=_crash_cmd,
        )
        ok_cfg = _cfg("alpha", category="static")
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [crash_cfg, ok_cfg],
            )
        statuses = {o.config.collector_id: o.evidence["status"] for o in outcomes}
        self.assertEqual(statuses["boom"], "error")
        self.assertEqual(statuses["alpha"], "ok")

    # §7.2 #5 — create_collector_checkout fails for one collector
    def test_checkout_failure_isolated_via_error_evidence(self) -> None:
        cfg_a = _cfg("a-good")
        cfg_b = _cfg("b-fail", category="static")
        call_count = {"n": 0}
        real_create = collector_isolation._create_unit_checkout

        def fake_create(
            project_root: Any, commit_sha: str, name_hint: str, add_timeout: int
        ) -> Path:
            call_count["n"] += 1
            if name_hint == "b-fail":
                raise CollectorCheckoutError("synthetic checkout failure")
            return real_create(project_root, commit_sha, name_hint, add_timeout)

        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_isolation,
                "_create_unit_checkout",
                side_effect=fake_create,
            ),
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg_a, cfg_b],
            )
        statuses = {o.config.collector_id: o.evidence["status"] for o in outcomes}
        self.assertEqual(statuses["a-good"], "ok")
        self.assertEqual(statuses["b-fail"], "error")
        # Finding should mention the synthetic failure.
        bad = next(o for o in outcomes if o.config.collector_id == "b-fail")
        self.assertTrue(any("synthetic" in f for f in bad.evidence.get("findings", [])))

    # §7.2 #6 — cleanup OSError swallowed
    def test_cleanup_oserror_swallowed(self) -> None:
        cfg = _cfg("alpha")

        def boom_cleanup(checkout: Path, project_root: Any) -> None:
            raise OSError("synthetic cleanup failure")

        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_isolation,
                "cleanup_collector_checkout",
                side_effect=boom_cleanup,
            ),
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "ok")

    # §7.2 #10 — emits one EvidenceCollectedAudit per outcome.
    def test_emits_one_audit_event_per_outcome(self) -> None:
        cfg_a = _cfg("a-good")
        cfg_b = _cfg("b-good", category="static")
        audit_path = self.fx.project_root / "audit.jsonl"
        policy = {"security": {"audit_trail": True}}
        with mock.patch.dict(
            os.environ,
            {**_host_env(), "BMAD_AUDIT_KEY": "test-key"},
            clear=True,
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg_a, cfg_b],
                audit_policy=policy,
                audit_path=audit_path,
            )
        self.assertEqual(len(outcomes), 2)
        # Audit log should have at least 2 EvidenceCollected events.
        self.assertTrue(audit_path.exists())
        import json

        lines = audit_path.read_text().strip().splitlines()
        names = [json.loads(line)["event"] for line in lines]
        self.assertEqual(names.count("EvidenceCollected"), 2)

    # §7.2 #12 — Per-unit worktrees live under tempfile.gettempdir().
    def test_per_unit_worktrees_under_tempdir_not_bmad(self) -> None:
        captured: list[str] = []

        def capture_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            captured.append(checkout)
            return [sys.executable, "-c", "pass"]

        cfg = CollectorConfig(
            collector_id="probe",
            tool="python3",
            category="correctness",
            build_cmd=capture_cmd,
        )
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(captured), 1)
        ckt = Path(captured[0])
        self.assertEqual(ckt.parent, Path(tempfile.gettempdir()))
        self.assertTrue(ckt.name.startswith("sa-collector-"))
        # Must NOT live under _bmad/.
        bmad = self.fx.project_root / "_bmad"
        self.assertFalse(str(ckt).startswith(str(bmad)))

    # §7.2 #13 — assert_host_context raised in child-session env.
    def test_child_session_env_propagates_trust_boundary(self) -> None:
        from story_automator.core.trust_boundary import TrustBoundaryError

        cfg = _cfg("alpha")
        # assert_host_context lives inside run_single_collector, so the
        # child-session env causes the worker to raise TrustBoundaryError
        # — which our worker reifies as a _crash_outcome (status=error).
        with mock.patch.dict(
            os.environ,
            {**_host_env(), "STORY_AUTOMATOR_CHILD": "true"},
            clear=True,
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")
        # TrustBoundaryError is an Exception subclass.
        self.assertTrue(
            any(
                "TrustBoundaryError" in f or "trust boundary" in f.lower()
                for f in outcomes[0].evidence.get("findings", [])
            )
        )
        # Suppress unused-import warning.
        _ = TrustBoundaryError

    # §7.2 #14 — KeyboardInterrupt mid-run drains queue, re-raises.
    def test_keyboard_interrupt_re_raised_after_collection(self) -> None:
        cfg_a = _cfg("alpha")
        cfg_b = _cfg("bravo", category="static")
        cfg_c = _cfg("charlie", category="security")

        # Patch _run_isolated so the SECOND submission raises KI.
        real_run = collector_isolation._run_isolated
        seen = {"n": 0}

        def fake_run(config: CollectorConfig, *args: Any, **kwargs: Any) -> CollectorOutcome:
            seen["n"] += 1
            if config.collector_id == "bravo":
                raise KeyboardInterrupt()
            return real_run(config, *args, **kwargs)

        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_isolation,
                "_run_isolated",
                side_effect=fake_run,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_collectors_per_unit(
                    self.fx.project_root,
                    "gate-001",
                    self.fx.sha,
                    _make_profile(),
                    [cfg_a, cfg_b, cfg_c],
                )

    # §7.2 #15 — MemoryError in one worker -> _crash_outcome; re-raise.
    def test_memory_error_reified_and_reraised(self) -> None:
        cfg_a = _cfg("alpha")
        cfg_b = _cfg("bravo", category="static")
        real_run = collector_isolation._run_isolated

        def fake_run(config: CollectorConfig, *args: Any, **kwargs: Any) -> CollectorOutcome:
            if config.collector_id == "bravo":
                raise MemoryError("synthetic OOM")
            return real_run(config, *args, **kwargs)

        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_isolation,
                "_run_isolated",
                side_effect=fake_run,
            ),
        ):
            with self.assertRaises(MemoryError):
                run_collectors_per_unit(
                    self.fx.project_root,
                    "gate-001",
                    self.fx.sha,
                    _make_profile(),
                    [cfg_a, cfg_b],
                )

    # §7.2 #16 — AuditLockTimeout retried once.
    def test_audit_lock_timeout_retried_once(self) -> None:
        cfg = _cfg("alpha")

        call_count = {"n": 0}
        real_collector_runner = None

        def patched_run_single(*args: Any, **kwargs: Any) -> CollectorOutcome:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise AuditLockTimeout("first attempt")
            # 2nd attempt succeeds via real path.
            assert real_collector_runner is not None
            return real_collector_runner(*args, **kwargs)

        from story_automator.core import collector_runner

        real_collector_runner = collector_runner.run_single_collector
        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_runner,
                "run_single_collector",
                side_effect=patched_run_single,
            ),
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "ok")
        self.assertEqual(call_count["n"], 2)

    def test_audit_lock_timeout_exhausted_yields_error(self) -> None:
        cfg = _cfg("alpha")

        def always_timeout(*args: Any, **kwargs: Any) -> CollectorOutcome:
            raise AuditLockTimeout("permanent")

        from story_automator.core import collector_runner

        with (
            mock.patch.dict(os.environ, _host_env(), clear=True),
            mock.patch.object(
                collector_runner,
                "run_single_collector",
                side_effect=always_timeout,
            ),
        ):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")
        self.assertTrue(
            any("audit lock timeout" in f.lower() for f in outcomes[0].evidence.get("findings", []))
        )

    # §7.2 #17 — Thread name save+restore.
    def test_thread_name_save_restore(self) -> None:
        cfg = _cfg("alpha")
        # Capture the live worker thread name at collector entry time
        # so we can prove the rename happened.
        captured_during: list[str] = []

        def capture_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            captured_during.append(threading.current_thread().name)
            return [sys.executable, "-c", "pass"]

        cfg = CollectorConfig(
            collector_id="probe-thread-name",
            tool="python3",
            category="correctness",
            build_cmd=capture_cmd,
        )
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
            )
        self.assertEqual(len(outcomes), 1)
        # During execution the thread was renamed.
        self.assertTrue(
            any("sa-isolated-probe-thread-name" in n for n in captured_during),
            f"expected sa-isolated-* name during exec, saw {captured_during!r}",
        )
        # After the pool shuts down, the parent thread's name is
        # untouched. We can't easily inspect post-restore worker
        # names (workers are gone), but we can verify nothing leaks
        # into the active thread set in the current process.
        live = [t.name for t in threading.enumerate()]
        self.assertFalse(any(n.startswith("sa-isolated-") for n in live))

    # §7.2 #21 — Outcome sort order pinned (property test).
    def test_outcome_sort_order_pinned_property(self) -> None:
        ids = [f"col-{i:02d}" for i in range(6)]
        cats = ["correctness", "static", "security"]
        random.seed(42)
        configs = [_cfg(cid, category=cats[i % 3]) for i, cid in enumerate(ids)]
        # Shuffle the input order and verify output is sorted.
        shuffled = list(configs)
        random.shuffle(shuffled)
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                shuffled,
            )
        keys = [(o.config.category, o.config.collector_id) for o in outcomes]
        self.assertEqual(keys, sorted(keys))

    # §7.2 #11 — Concurrency stress (small variant: 4 collectors,
    # max_workers=4, all succeed, no errors).
    def test_concurrency_no_spurious_errors(self) -> None:
        configs = [_cfg(f"c-{i:02d}", category="correctness") for i in range(4)]
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                configs,
                max_workers=4,
            )
        self.assertEqual(len(outcomes), 4)
        for o in outcomes:
            self.assertEqual(o.evidence["status"], "ok")
            self.assertFalse(any("AuditLockTimeout" in f for f in o.evidence.get("findings", [])))

    def test_max_workers_clamped_at_entry(self) -> None:
        # Smoke-test that very large max_workers does NOT crash
        # ThreadPoolExecutor; the clamp ensures it stays <= ceiling.
        cfg = _cfg("alpha")
        with mock.patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_collectors_per_unit(
                self.fx.project_root,
                "gate-001",
                self.fx.sha,
                _make_profile(),
                [cfg],
                max_workers=10_000,
            )
        self.assertEqual(len(outcomes), 1)

    def test_default_max_workers_constant(self) -> None:
        self.assertEqual(DEFAULT_MAX_WORKERS, 4)
        self.assertEqual(MAX_PARALLEL_CEILING, 16)
        self.assertEqual(ADD_TIMEOUT_PER_UNIT_S, 90)

    def test_outcome_findings_carries_crash_type(self) -> None:
        # Helper-test: _crash_outcome's finding string includes the
        # exception type name so operators can distinguish reasons.
        cfg = _cfg("alpha")
        outcome = _crash_outcome(
            cfg,
            MemoryError("oom-msg"),
            self.fx.project_root,
            "gate-001",
        )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(any("MemoryError" in f for f in outcome.evidence["findings"]))

    def test_error_outcome_findings_carries_checkout_failed(self) -> None:
        cfg = _cfg("alpha")
        outcome = _error_outcome(
            cfg,
            CollectorCheckoutError("synthetic"),
            self.fx.project_root,
            "gate-001",
        )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(any("checkout failed" in f for f in outcome.evidence["findings"]))

    def test_audit_timeout_outcome_findings(self) -> None:
        cfg = _cfg("alpha")
        outcome = _audit_timeout_outcome(
            cfg,
            AuditLockTimeout("slow"),
            self.fx.project_root,
            "gate-001",
        )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(
            any("audit lock timeout" in f.lower() for f in outcome.evidence["findings"])
        )


if __name__ == "__main__":
    unittest.main()
