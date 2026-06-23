"""End-to-end factory self-evaluation harness (Milestone A).

Drives ``run_production_gate`` against the factory's own working tree
using the bundled ``default.json`` profile and asserts the lifecycle,
Merkle export, audit chain, and reuse-path are all wired correctly.

This is the first regression net that exercises every wiring layer
(profile load -> registry -> trust boundary -> orchestrator lifecycle
-> evidence I/O -> Merkle export -> audit chain) in one closed loop.

Consumer-only: zero changes under ``skills/``, zero new deps. If a
wiring bug surfaces during execution it is filed as a follow-up; this
test is the witness, not the fix.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from story_automator.core.audit import AuditLog, load_key_from_env
from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import (
    compute_evidence_bundle_merkle_root,
    load_evidence_bundle,
    load_gate_file,
)
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.product_profile import (
    compute_profile_hash,
    load_bundled_profile,
)
from story_automator.core.trust_boundary import TrustBoundaryError

# 64-char lowercase hex regex for the Merkle root branch.
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Closed verdict vocabulary per gate_schema.
VALID_VERDICTS = frozenset({"PASS", "CONCERNS", "FAIL", "WAIVED"})


class TestFactorySelfEvaluation(unittest.TestCase):
    """One gate run, many focused asserts (Milestone A — spec §Design)."""

    @classmethod
    def setUpClass(cls) -> None:
        # 1. Resolve repo root: tests/integration/__file__.parents[2] == repo root.
        cls.repo_root = Path(__file__).resolve().parents[2]

        # 2. Detect HEAD commit. text=True + .strip() — rev-parse emits
        #    "<sha>\n" and a stale newline would poison the gate_id regex
        #    ``^[a-zA-Z0-9._-]+$``. Empty stdout treated as "no git" (some
        #    Windows-git-bash configs).
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=cls.repo_root,
                text=True,
            ).strip()
        except FileNotFoundError as exc:
            raise unittest.SkipTest("git binary unavailable") from exc
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git rev-parse HEAD failed: {exc}") from exc
        if not sha:
            raise unittest.SkipTest("git rev-parse HEAD produced empty output")
        cls.commit_sha = sha

        # 3. Isolated temp dir so the gate's _bmad/ artifacts stay out of
        #    the repo. The harness writes nothing to repo_root.
        cls._tmp = tempfile.TemporaryDirectory()
        cls.project_root = Path(cls._tmp.name) / "factory-self-eval"
        cls.project_root.mkdir(parents=True)

        # 4. BMAD_AUDIT_KEY save/restore (gap A-05): canonical save-pop-set
        #    pattern from tests/test_audit_call_sites.py:73. NEVER bare-
        #    overwrite — that would leak the operator's real secret on
        #    teardown if it was already set in env.
        cls._saved_audit_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        os.environ["BMAD_AUDIT_KEY"] = "milestone-a-test-secret"

        # 5. Load bundled default profile + disable all active categories
        #    (gap A-04). Empty registry against the unmodified default
        #    profile fail-closes every active category, so to keep the
        #    verdict branch deterministic we set categories_na to the
        #    union of all declared categories. NA categories aggregate
        #    to FAIL anyway under gate_rules.aggregate_verdicts (empty
        #    active set is fail-closed) — that's expected per spec.
        try:
            cls.profile = load_bundled_profile("default")
        except Exception as exc:  # ProfileError or PathError
            cls._restore_audit_key()
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"bundled default profile unavailable: {exc}"
            ) from exc
        _all_active = sorted(
            set().union(*cls.profile.get("categories", {}).values())
        )
        cls.profile["categories_na"] = _all_active
        cls.profile_hash = compute_profile_hash(cls.profile)

        # 6. Empty registry — fastest possible gate; exercises lifecycle
        #    wiring without depending on any tool being installed.
        cls.registry = CollectorRegistry()

        # 7. Deterministic gate_id (sha[:12] gives uniqueness without a
        #    timestamp; matches _SAFE_GATE_ID regex).
        cls.gate_id = f"factory-self-eval-{cls.commit_sha[:12]}"

        # 8. audit_policy shape (gap A-01): codebase contract is
        #    ``{"security": {"audit_trail": True}}``. The wrong shape
        #    ``{"enabled": True}`` silently disables audit and would
        #    make test_audit_chain_verifies_after_gate flap. audit_path
        #    is the SOLE path source per gap A-11.
        cls.audit_path = cls.project_root / "audit.jsonl"
        cls.audit_policy = {"security": {"audit_trail": True}}

        # 9. Drive the gate. Wrap in try/finally so the env restoration
        #    is unconditional (gap A-05). factory_version is hand-coded
        #    (gap A-03 rationale): production callers use
        #    resolve_factory_version() but the harness pins a constant
        #    so determinism + reuse-path tests do not flap when the
        #    production resolver ticks.
        try:
            cls.gate_file = run_production_gate(
                cls.project_root,
                cls.gate_id,
                commit_sha=cls.commit_sha,
                target={"kind": "repo", "id": "bmad-story-automator"},
                profile=cls.profile,
                factory_version="milestone-a",
                registry=cls.registry,
                priority="P1",
                audit_policy=cls.audit_policy,
                audit_path=cls.audit_path,
            )
        except TrustBoundaryError as exc:
            # Specifically caught (gap A-08): bare ``except RuntimeError``
            # would swallow gate-orchestrator's lock-timeout and marker-
            # corruption RuntimeErrors that we MUST see.
            cls._restore_audit_key()
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"host context rejects gate: {exc}"
            ) from exc
        except (FileNotFoundError, PermissionError) as exc:
            cls._restore_audit_key()
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"sandbox forbids gate IO: {exc}"
            ) from exc

    @classmethod
    def tearDownClass(cls) -> None:
        cls._restore_audit_key()
        cls._tmp.cleanup()

    @classmethod
    def _restore_audit_key(cls) -> None:
        """Restore the operator's prior BMAD_AUDIT_KEY (or unset)."""
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if cls._saved_audit_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key

    # ---------- Lifecycle shape assertions ----------

    def test_gate_returns_dict(self) -> None:
        """run_production_gate must return a dict (the gate file)."""
        self.assertIsInstance(self.gate_file, dict)

    def test_overall_verdict_in_closed_vocabulary(self) -> None:
        """``overall`` must be one of the four documented verdicts.

        We assert membership rather than pinning a single literal so a
        future change to empty-registry semantics (e.g. orchestrator
        emitting a synthetic gate-started evidence record, or different
        categories_na semantics) does not silently regress.
        """
        self.assertIn(self.gate_file["overall"], VALID_VERDICTS)

    def test_gate_id_round_trips_through_load_gate_file(self) -> None:
        """Persisted disk artifact matches the in-memory gate_id."""
        reloaded = load_gate_file(self.project_root, self.gate_id)
        self.assertEqual(reloaded["gate_id"], self.gate_id)

    def test_gate_file_carries_factory_version(self) -> None:
        """factory_version must round-trip the hand-coded constant."""
        self.assertEqual(
            self.gate_file.get("factory_version"),
            "milestone-a",
        )

    def test_profile_hash_recorded_on_gate_file(self) -> None:
        """gate_file["profile"]["hash"] anchored to verdict_engine.

        verdict_engine.evaluate_gate rewrites gate_file["profile"] into
        a 2-key projection ``{"id": ..., "hash": compute_profile_hash}``;
        do NOT assert equality on the full input profile dict — the
        persisted projection is a 2-key view and full-equality fails.
        If the projection schema changes, this assertion AND
        validate_gate_file need a coordinated update.
        """
        self.assertEqual(
            self.gate_file["profile"]["hash"],
            self.profile_hash,
        )

    # ---------- Merkle export ----------

    def test_merkle_root_shape_64_hex_or_empty_sentinel(self) -> None:
        """Merkle root is either a 64-hex string or the empty sentinel.

        Empty bundle (Milestone A empty-registry path) → ``""`` sentinel.
        Non-empty bundle (Milestone B+ with real collectors) → 64-hex.
        Both branches must remain regex-valid so a future milestone
        flipping the live branch does not silently regress.
        """
        root = self.gate_file.get("evidence_merkle_root")
        self.assertIsInstance(root, str)
        if root == "":
            # Empty-registry sentinel branch (Milestone A live path).
            return
        self.assertRegex(root, HEX64)

    def test_evidence_bundle_loads_without_error(self) -> None:
        """Bundle disk readback must not raise (may be empty list)."""
        bundle = load_evidence_bundle(self.project_root, self.gate_id)
        self.assertIsInstance(bundle, list)
        # If the bundle is non-empty, the gate_file root must match a
        # fresh recomputation — auditor's external-verify workflow.
        if bundle:
            expected = compute_evidence_bundle_merkle_root(bundle)
            self.assertEqual(
                self.gate_file["evidence_merkle_root"], expected,
            )

    # ---------- Audit chain ----------

    def test_audit_chain_verifies_after_gate(self) -> None:
        """AuditLog.verify() returns (True, n) with n >= 1.

        The orchestrator emits GateStartedAudit at minimum, so seq is
        always >= 1 on a healthy run with audit_trail enabled.
        """
        key = load_key_from_env()
        self.assertIsNotNone(key, "BMAD_AUDIT_KEY must derive a key")
        # AuditLog is kw_only — both path and key must be named.
        log = AuditLog(path=self.audit_path, key=key)
        ok, last_seq = log.verify()
        self.assertTrue(ok, "audit chain failed integrity check")
        self.assertGreaterEqual(last_seq, 1)

    # ---------- Determinism / reuse path ----------

    def test_second_invocation_returns_reused_gate_file(self) -> None:
        """A second run with identical args MUST hit the reuse path.

        Gap A-09 strengthening: gate_id equality alone is insufficient
        (a buggy re-run that recomputed identical bytes would silently
        pass). Option A — mtime check on the persisted gate file. The
        reuse path returns the pre-existing artifact without rewriting
        it; mtime must be unchanged.

        Note on Merkle equality: the orchestrator adds
        ``evidence_merkle_root`` to the in-memory gate_file AFTER
        ``persist_gate_file`` runs (see gate_orchestrator.py:580). The
        reuse short-circuit (line 538) returns the persisted file —
        which never carried the Merkle root in its on-disk form. So we
        cannot assert ``result["evidence_merkle_root"]`` on the reuse
        return; we assert only what the persisted artifact carries.
        Mtime-unchanged is the operative regression catch.
        """
        gate_path = (
            Path(self.project_root)
            / "_bmad" / "gate" / "verdicts" / f"{self.gate_id}.json"
        )
        self.assertTrue(
            gate_path.is_file(),
            "first-run gate file must already be persisted",
        )
        mtime_before = gate_path.stat().st_mtime_ns

        result = run_production_gate(
            self.project_root,
            self.gate_id,
            commit_sha=self.commit_sha,
            target={"kind": "repo", "id": "bmad-story-automator"},
            profile=self.profile,
            factory_version="milestone-a",
            registry=self.registry,
            priority="P1",
            audit_policy=self.audit_policy,
            audit_path=self.audit_path,
        )

        self.assertEqual(result["gate_id"], self.gate_id)
        self.assertEqual(
            result.get("factory_version"), "milestone-a",
            "reuse must return the original factory_version",
        )
        self.assertEqual(
            gate_path.stat().st_mtime_ns, mtime_before,
            "reuse path must not rewrite the persisted gate file",
        )


# ---------- A-follow: smoke profile + in-test collector → real verdict ----------


# Module-level helpers (must be defined at module scope so CollectorConfig
# can hold references to them; lambdas would also work but explicit
# functions read cleaner in failure messages).
def _smoke_build_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Trivial collector command: exit 0, emit a recognizable stdout line.

    The collector's stdout is fed to ``parse_metrics`` which extracts the
    coverage/regressions metrics the correctness rule reads. We do NOT
    inspect ``checkout`` or ``profile`` — the test only needs the
    subprocess to terminate cleanly so the runner stamps ``status=ok``.
    """
    return [sys.executable, "-c", "print('SMOKE_OK coverage=95 regressions=0')"]


def _smoke_parse_metrics(stdout: str) -> dict[str, Any]:
    """Return the metric shape that ``correctness_rule`` consumes.

    P1 priority requires ``coverage_pct >= 90`` for PASS; we emit 95 so
    we sit comfortably above the threshold. ``regressions=0`` is the
    pass condition for the regression gate. Both values are hard-coded
    rather than parsed out of stdout — the test owns the parser so it
    can guarantee deterministic metrics regardless of the trivial
    subprocess's actual output.
    """
    if "SMOKE_OK" not in stdout:
        return {}
    return {"coverage_pct": 95, "regressions": 0}


def _git_init_with_commit(path: Path) -> str:
    """Create a tiny git repo with one commit; return the resolved SHA.

    ``collector_checkout`` requires a real ``.git`` directory in
    ``project_root`` so it can build a detached worktree at the gate's
    ``commit_sha``. A pristine ``git init`` + one empty commit is the
    smallest fixture that satisfies that contract.
    """
    env = {
        **os.environ,
        # Force git to skip system/global config so the test is hermetic
        # across CI hosts that may have signing or hook config enabled.
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(path), *args],
            check=True, capture_output=True, text=True, env=env,
        )

    subprocess.run(
        ["git", "init", "--initial-branch=main", "-q", str(path)],
        check=True, capture_output=True, env=env,
    )
    _run("config", "user.email", "smoke@test")
    _run("config", "user.name", "Smoke Test")
    _run("config", "commit.gpgsign", "false")
    (path / "README.md").write_text("smoke fixture\n")
    _run("add", "README.md")
    _run("commit", "-q", "-m", "smoke init")
    return _run("rev-parse", "HEAD").stdout.strip()


class FactorySmokeProfileTests(unittest.TestCase):
    """Drive ``run_production_gate`` against a profile with ONE active
    category + an in-test collector wired to emit PASS-shaped metrics.

    This closes the gap that ``TestFactorySelfEvaluation`` left open:
    that harness uses an empty registry against the unmodified default
    profile, so ``gate_rules.aggregate_verdicts`` fail-closes on an
    empty active set and the verdict is forced to FAIL regardless of
    anything downstream. The (collector → evidence → adjudicator →
    verdict) chain is therefore NOT exercised end-to-end.

    Smoke harness contract:
      * Profile has exactly one active code category (``correctness``)
        and no ``categories_na`` overrides.
      * Registry holds ONE ``CollectorConfig`` for ``correctness`` whose
        build_cmd emits a trivial exit-0 subprocess and whose
        ``parse_metrics`` returns ``coverage_pct=95, regressions=0``.
      * Therefore: status=ok, coverage 95% > 90% P1 floor, regressions=0
        → ``correctness_rule`` returns PASS → ``aggregate_verdicts``
        returns PASS → ``overall=PASS``.
      * Evidence bundle is non-empty → ``evidence_merkle_root`` lives on
        the live 64-hex branch (sentinel ``""`` would indicate the
        bundle was empty, which would be a wiring regression).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]

        # 1. Hermetic temp project: git init + one commit so the gate's
        #    collector_checkout step can build a detached worktree.
        cls._tmp = tempfile.TemporaryDirectory()
        cls.project_root = Path(cls._tmp.name) / "smoke-project"
        cls.project_root.mkdir(parents=True)
        try:
            cls.commit_sha = _git_init_with_commit(cls.project_root)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"git unavailable for smoke fixture: {exc}"
            ) from exc

        # 2. BMAD_AUDIT_KEY save/restore (canonical pattern — see the
        #    parent harness for the rationale). Bare overwrite would
        #    leak the operator's secret on teardown.
        cls._saved_audit_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        os.environ["BMAD_AUDIT_KEY"] = "smoke-profile-test-secret"

        # 3. STORY_AUTOMATOR_CHILD must NOT be set — the gate code asserts
        #    host context and TrustBoundaryError aborts collection. Save
        #    + clear; restore on teardown.
        cls._saved_child = os.environ.pop("STORY_AUTOMATOR_CHILD", None)

        # 4. Load smoke profile fixture. The JSON lives under
        #    tests/integration/data/profiles/ and is loaded directly via
        #    json.loads rather than load_bundled_profile — it is NOT a
        #    bundled product profile, just a test fixture that exercises
        #    the one-active-category path.
        profile_path = (
            Path(__file__).resolve().parent
            / "data" / "profiles" / "smoke.json"
        )
        cls.profile: dict[str, Any] = json.loads(profile_path.read_text())
        cls.profile_hash = compute_profile_hash(cls.profile)

        # 5. Build the registry with ONE collector wired to emit
        #    PASS-shaped metrics for correctness.
        cls.registry = CollectorRegistry()
        cls.registry.register(
            CollectorConfig(
                collector_id="smoke-correctness",
                tool="python3",
                category="correctness",
                build_cmd=_smoke_build_cmd,
                parse_metrics=_smoke_parse_metrics,
            ),
        )

        # 6. Deterministic gate_id derived from the smoke commit SHA so
        #    re-running the suite does not pollute state from prior runs
        #    (the tmp dir is fresh anyway, but the gate_id stays stable
        #    across runs of this class).
        cls.gate_id = f"smoke-{cls.commit_sha[:12]}"
        cls.audit_path = cls.project_root / "audit.jsonl"
        cls.audit_policy = {"security": {"audit_trail": True}}

        # 7. Drive the gate. Wrap in try/finally so env restoration is
        #    unconditional; specific exceptions become SkipTest rather
        #    than test errors so unrelated host quirks (sandbox path
        #    restrictions, missing git) do not break CI.
        try:
            cls.gate_file = run_production_gate(
                cls.project_root,
                cls.gate_id,
                commit_sha=cls.commit_sha,
                target={"kind": "repo", "id": "smoke-test"},
                profile=cls.profile,
                factory_version="a-follow-smoke",
                registry=cls.registry,
                priority="P1",
                audit_policy=cls.audit_policy,
                audit_path=cls.audit_path,
            )
        except TrustBoundaryError as exc:
            cls._restore_env()
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"host context rejects smoke gate: {exc}"
            ) from exc
        except (FileNotFoundError, PermissionError) as exc:
            cls._restore_env()
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                f"sandbox forbids smoke gate IO: {exc}"
            ) from exc

    @classmethod
    def tearDownClass(cls) -> None:
        cls._restore_env()
        # Best-effort worktree prune so the parent .git doesn't accumulate
        # phantom refs across runs (gate creates ephemeral worktrees
        # under /tmp and cleans them up itself, but `git worktree prune`
        # is the belt-and-braces cleanup).
        try:
            subprocess.run(
                ["git", "-C", str(cls.project_root), "worktree", "prune"],
                check=False, capture_output=True,
            )
        except (FileNotFoundError, OSError):
            pass
        cls._tmp.cleanup()

    @classmethod
    def _restore_env(cls) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if cls._saved_audit_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key
        os.environ.pop("STORY_AUTOMATOR_CHILD", None)
        if cls._saved_child is not None:
            os.environ["STORY_AUTOMATOR_CHILD"] = cls._saved_child

    def test_overall_verdict_is_pass(self) -> None:
        """The collector-to-verdict chain produces PASS — the real
        regression catch this class exists to provide.

        Failure modes this catches:
          * Registry filtering bug → no collectors run → empty active set
            → FAIL.
          * parse_metrics not wired → empty metrics → correctness_rule
            sees coverage_pct=0 → FAIL on P1 floor.
          * Evidence persistence dropped → adjudicator sees empty bundle
            → fail-closed → FAIL.
        """
        self.assertEqual(
            self.gate_file["overall"], "PASS",
            f"expected PASS but got {self.gate_file['overall']}: "
            f"categories={self.gate_file.get('categories')}",
        )

    def test_correctness_category_is_pass(self) -> None:
        """Per-category verdict for the single active category."""
        categories = self.gate_file.get("categories", {})
        self.assertIn("correctness", categories)
        self.assertEqual(categories["correctness"]["verdict"], "PASS")

    def test_evidence_merkle_root_is_64_hex(self) -> None:
        """Non-empty bundle path: Merkle root must be a 64-hex string.

        The parent harness allowed the empty-string sentinel because the
        empty-registry path is the live branch there. Here, the single
        collector MUST persist at least one evidence record, so the live
        branch is the 64-hex root. Catching the sentinel would mean the
        evidence bundle is empty — a wiring regression.
        """
        root = self.gate_file.get("evidence_merkle_root")
        self.assertIsInstance(root, str)
        self.assertRegex(root, HEX64)

    def test_evidence_bundle_root_matches_recomputation(self) -> None:
        """External-verify path: a fresh Merkle recomputation over the
        persisted bundle must equal the gate file's recorded root."""
        bundle = load_evidence_bundle(self.project_root, self.gate_id)
        self.assertTrue(bundle, "smoke collector must persist evidence")
        expected = compute_evidence_bundle_merkle_root(bundle)
        self.assertEqual(self.gate_file["evidence_merkle_root"], expected)

    def test_gate_file_round_trips(self) -> None:
        """Persisted gate file matches in-memory gate_id."""
        reloaded = load_gate_file(self.project_root, self.gate_id)
        self.assertEqual(reloaded["gate_id"], self.gate_id)
        self.assertEqual(reloaded["overall"], "PASS")

    def test_audit_chain_verifies(self) -> None:
        """Audit chain stays intact across the collector-evidence loop."""
        key = load_key_from_env()
        self.assertIsNotNone(key)
        log = AuditLog(path=self.audit_path, key=key)
        ok, last_seq = log.verify()
        self.assertTrue(ok, "audit chain failed integrity check")
        self.assertGreaterEqual(last_seq, 1)


# ---------- A-follow-2: multi-category aggregation (3-cat smoke) ----------


# Module-level pass/fail command builders for static + docs fake collectors.
# ``status=ok`` on subprocess exit 0 ⇒ static_rule / generic_rule ⇒ PASS.
# ``status=violation`` on non-zero exit ⇒ FAIL. Both rules are status-driven
# (see core/category_rules.py:_status_based_rule), so we drive the verdict
# by toggling the subprocess exit code, never by changing rule thresholds.


def _smoke_static_pass_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Static collector: clean lint run (exit 0)."""
    return [sys.executable, "-c", "print('SMOKE_STATIC_OK')"]


def _smoke_static_fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Static collector: lint violations detected (exit 1)."""
    return [
        sys.executable,
        "-c",
        "import sys; print('SMOKE_STATIC_VIOLATION lint=1'); sys.exit(1)",
    ]


def _smoke_docs_pass_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Docs collector: docs coverage check passes (exit 0)."""
    return [sys.executable, "-c", "print('SMOKE_DOCS_OK')"]


def _smoke_docs_fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    """Docs collector: missing docs detected (exit 1)."""
    return [
        sys.executable,
        "-c",
        "import sys; print('SMOKE_DOCS_VIOLATION missing=1'); sys.exit(1)",
    ]


def _smoke_static_parse(stdout: str) -> dict[str, Any]:
    """Return a deterministic metric tag; static_rule is status-driven so
    the exact key does not affect the verdict — emit something stable for
    audit-trail / merkle determinism."""
    return {"lint_violations": 0 if "SMOKE_STATIC_OK" in stdout else 1}


def _smoke_docs_parse(stdout: str) -> dict[str, Any]:
    """Same shape as the static parser — docs_rule falls through to the
    status-driven generic rule, so the metric is informational only."""
    return {"doc_coverage_pct": 100 if "SMOKE_DOCS_OK" in stdout else 0}


def _drive_smoke_gate(
    profile: dict[str, Any],
    *,
    project_root: Path,
    commit_sha: str,
    gate_id: str,
    audit_path: Path,
    factory_version: str,
    static_cmd: Any,
    docs_cmd: Any,
) -> dict[str, Any]:
    """Build a 3-collector registry (correctness PASS, static + docs
    parameterized) and drive ``run_production_gate`` once.
    Helper kept at module scope so each test method gets an isolated
    project_root + audit_path without leaking state across the suite.
    """
    registry = CollectorRegistry()
    registry.register(
        CollectorConfig(
            collector_id="smoke-correctness",
            tool="python3",
            category="correctness",
            build_cmd=_smoke_build_cmd,
            parse_metrics=_smoke_parse_metrics,
        ),
    )
    registry.register(
        CollectorConfig(
            collector_id="smoke-static",
            tool="python3",
            category="static",
            build_cmd=static_cmd,
            parse_metrics=_smoke_static_parse,
        ),
    )
    registry.register(
        CollectorConfig(
            collector_id="smoke-docs",
            tool="python3",
            category="docs",
            build_cmd=docs_cmd,
            parse_metrics=_smoke_docs_parse,
        ),
    )

    return run_production_gate(
        project_root,
        gate_id,
        commit_sha=commit_sha,
        target={"kind": "repo", "id": "smoke-3cat-test"},
        profile=profile,
        factory_version=factory_version,
        registry=registry,
        priority="P1",
        audit_policy={"security": {"audit_trail": True}},
        audit_path=audit_path,
    )


class FactorySmoke3CategoryTests(unittest.TestCase):
    """Multi-category aggregation harness — closes the gap that the
    single-category ``FactorySmokeProfileTests`` left open.

    The single-cat smoke only proves that PASS plumbing works end-to-end
    with one active category. It does NOT exercise:
      * Merkle root over a multi-record bundle (sort-order determinism).
      * Per-category verdict rendering when categories disagree.
      * Audit-chain coverage of N>1 EvidenceCollected events.
      * Aggregate-verdict downgrade when any single category fails.

    Each test method runs its own gate against a fresh tmp project so
    the registry + verdict + Merkle root + audit chain are all isolated.
    The 3-cat profile lives in ``tests/integration/data/profiles/smoke_3cat.json``.
    The 1-cat ``smoke.json`` profile is kept untouched so the existing
    happy-path class remains a regression net for the single-category
    code path.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]

        # Load 3-cat profile fixture once for the class. Each test method
        # then drives the gate against a per-test tmp project so the
        # gate-reuse short-circuit (matches on gate_id under
        # project_root/_bmad/) cannot cross-contaminate cases.
        profile_path = (
            Path(__file__).resolve().parent
            / "data" / "profiles" / "smoke_3cat.json"
        )
        cls.profile = json.loads(profile_path.read_text())

        # Canonical save/clear of env vars touched by the gate
        # (BMAD_AUDIT_KEY for HMAC chain, STORY_AUTOMATOR_CHILD for the
        # trust boundary). The single-cat class uses the same pattern.
        cls._saved_audit_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        cls._saved_child = os.environ.pop("STORY_AUTOMATOR_CHILD", None)
        os.environ["BMAD_AUDIT_KEY"] = "smoke-3cat-test-secret"

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if cls._saved_audit_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key
        os.environ.pop("STORY_AUTOMATOR_CHILD", None)
        if cls._saved_child is not None:
            os.environ["STORY_AUTOMATOR_CHILD"] = cls._saved_child

    def setUp(self) -> None:
        # Per-method tmp project — guarantees a fresh ``_bmad/`` so the
        # gate-reuse path never short-circuits across test methods. The
        # outer cleanup is registered via addCleanup so a SkipTest mid-
        # method still purges the directory.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name) / "smoke-3cat-project"
        self.project_root.mkdir(parents=True)
        try:
            self.commit_sha = _git_init_with_commit(self.project_root)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise unittest.SkipTest(
                f"git unavailable for 3-cat fixture: {exc}",
            ) from exc
        self.gate_id = f"smoke3-{self.commit_sha[:12]}"
        self.audit_path = self.project_root / "audit.jsonl"

    def _run(
        self,
        *,
        static_cmd: Any = _smoke_static_pass_cmd,
        docs_cmd: Any = _smoke_docs_pass_cmd,
        gate_id: str | None = None,
        factory_version: str = "a-follow-2-3cat",
    ) -> dict[str, Any]:
        try:
            return _drive_smoke_gate(
                self.profile,
                project_root=self.project_root,
                commit_sha=self.commit_sha,
                gate_id=gate_id or self.gate_id,
                audit_path=self.audit_path,
                factory_version=factory_version,
                static_cmd=static_cmd,
                docs_cmd=docs_cmd,
            )
        except TrustBoundaryError as exc:
            raise unittest.SkipTest(
                f"host context rejects 3-cat gate: {exc}",
            ) from exc
        except (FileNotFoundError, PermissionError) as exc:
            raise unittest.SkipTest(
                f"sandbox forbids 3-cat gate IO: {exc}",
            ) from exc

    # ---------- happy path: all 3 PASS ----------

    def test_3category_all_pass_overall_pass(self) -> None:
        """Three PASS-shaped collectors ⇒ overall PASS.

        Catches multi-category aggregation regressions where a registry
        filtering bug, a per-category rule dispatch bug, or an
        aggregate_verdicts ordering bug would silently demote PASS.
        """
        gate_file = self._run()
        self.assertEqual(
            gate_file["overall"], "PASS",
            f"expected PASS, got {gate_file['overall']}: "
            f"categories={gate_file.get('categories')}",
        )

    # ---------- negative paths: single category fails ⇒ overall NOT PASS ----------

    def test_3category_static_fails_overall_concerns_or_fail(self) -> None:
        """One failing category ⇒ aggregate verdict is NOT PASS.

        We assert NOT PASS (rather than pinning FAIL or CONCERNS) so a
        future tweak to ``aggregate_verdicts`` — for example introducing
        a CONCERNS tier for static — does not silently regress this test.
        Current code: any FAIL ⇒ overall FAIL.
        """
        gate_file = self._run(static_cmd=_smoke_static_fail_cmd)
        self.assertNotEqual(
            gate_file["overall"], "PASS",
            f"expected NOT PASS, got PASS: "
            f"categories={gate_file.get('categories')}",
        )
        # The static category MUST be the offender — guards against a
        # bug where the failing collector's evidence is mis-routed to
        # another category (or dropped entirely).
        self.assertNotEqual(
            gate_file["categories"]["static"]["verdict"], "PASS",
        )

    def test_3category_docs_fails_overall_concerns_or_fail(self) -> None:
        """Symmetric to the static case: failing docs collector also
        downgrades the overall verdict. Validates that the failure path
        is per-category, not hard-coded to one category."""
        gate_file = self._run(docs_cmd=_smoke_docs_fail_cmd)
        self.assertNotEqual(
            gate_file["overall"], "PASS",
            f"expected NOT PASS, got PASS: "
            f"categories={gate_file.get('categories')}",
        )
        self.assertNotEqual(
            gate_file["categories"]["docs"]["verdict"], "PASS",
        )

    # ---------- per-category rendering ----------

    def test_3category_each_category_renders_individual_verdict(self) -> None:
        """Per-category map carries ALL three active categories.

        Catches the case where ``compute_all_verdicts`` silently drops a
        category whose evidence is empty (vs the live-spec behaviour of
        rendering a fail-closed verdict). Each category must produce a
        dict with a ``verdict`` key in the closed vocabulary.
        """
        gate_file = self._run()
        categories = gate_file.get("categories", {})
        for cat in ("correctness", "static", "docs"):
            self.assertIn(cat, categories, f"missing category {cat}")
            self.assertIn(
                categories[cat]["verdict"], VALID_VERDICTS,
                f"{cat} verdict {categories[cat]['verdict']!r} not in "
                f"{VALID_VERDICTS}",
            )

    # ---------- Merkle determinism ----------

    def test_3category_merkle_root_changes_with_category_count(self) -> None:
        """Bundle hash distinguishes a 1-cat run from a 3-cat run.

        The Merkle root is computed over the canonical-JSON evidence
        records in sorted order (per the gate_orchestrator export). A
        bundle with three records MUST produce a different root than a
        bundle with one record — otherwise the export step is dropping
        records before hashing.
        """
        gate_file_3 = self._run(gate_id=f"{self.gate_id}-3cat")
        root_3 = gate_file_3.get("evidence_merkle_root")
        # 3-cat bundle: non-empty, 64-hex.
        self.assertIsInstance(root_3, str)
        self.assertRegex(root_3, HEX64)

        # Now drive a 1-cat gate against a fresh tmp project (the parent
        # smoke profile has only correctness active).
        with tempfile.TemporaryDirectory() as solo_tmp:
            solo_root = Path(solo_tmp) / "smoke-1cat-project"
            solo_root.mkdir(parents=True)
            try:
                solo_sha = _git_init_with_commit(solo_root)
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise unittest.SkipTest(
                    f"git unavailable for 1-cat comparison: {exc}",
                ) from exc
            solo_audit = solo_root / "audit.jsonl"
            solo_profile_path = (
                Path(__file__).resolve().parent
                / "data" / "profiles" / "smoke.json"
            )
            solo_profile = json.loads(solo_profile_path.read_text())
            solo_registry = CollectorRegistry()
            solo_registry.register(
                CollectorConfig(
                    collector_id="smoke-correctness",
                    tool="python3",
                    category="correctness",
                    build_cmd=_smoke_build_cmd,
                    parse_metrics=_smoke_parse_metrics,
                ),
            )
            try:
                gate_file_1 = run_production_gate(
                    solo_root,
                    f"smoke1-{solo_sha[:12]}",
                    commit_sha=solo_sha,
                    target={"kind": "repo", "id": "smoke-1cat-test"},
                    profile=solo_profile,
                    factory_version="a-follow-2-1cat",
                    registry=solo_registry,
                    priority="P1",
                    audit_policy={"security": {"audit_trail": True}},
                    audit_path=solo_audit,
                )
            except TrustBoundaryError as exc:
                raise unittest.SkipTest(
                    f"host context rejects 1-cat gate: {exc}",
                ) from exc
            root_1 = gate_file_1.get("evidence_merkle_root")
            self.assertIsInstance(root_1, str)
            self.assertRegex(root_1, HEX64)
            self.assertNotEqual(
                root_1, root_3,
                "Merkle root must differ between 1-cat and 3-cat bundles; "
                "identical roots imply records dropped before hashing",
            )

    # ---------- audit chain coverage ----------

    def test_3category_audit_chain_records_each_collector(self) -> None:
        """Each of the 3 in-test collectors emits its own
        ``EvidenceCollected`` audit event.

        Reads the audit JSONL directly (one record per line) and counts
        the per-collector events by ``payload.collector``. A bug where
        the runner emits a single batched event, or short-circuits on
        the first collector, would surface here.
        """
        self._run()
        self.assertTrue(
            self.audit_path.is_file(),
            "audit file must exist after a gate run with audit_trail on",
        )
        collectors_seen: set[str] = set()
        with self.audit_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("event") != "EvidenceCollected":
                    continue
                payload = record.get("payload") or {}
                collector = payload.get("collector")
                if collector:
                    collectors_seen.add(collector)
        self.assertEqual(
            collectors_seen,
            {"smoke-correctness", "smoke-static", "smoke-docs"},
            f"audit chain missing EvidenceCollected events: "
            f"saw {collectors_seen}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
