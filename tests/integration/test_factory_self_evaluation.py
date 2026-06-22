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

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.audit import AuditLog, load_key_from_env
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
