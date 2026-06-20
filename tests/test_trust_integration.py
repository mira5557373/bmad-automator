"""End-to-end trust boundary integration tests.

Validates the Blind Hunter property: the generation child cannot write
evidence, forge audit entries, or bypass the trust boundary.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.adjudicator import run_collector_with_timeout
from story_automator.core.collector_checkout import collector_checkout
from story_automator.core.evidence_io import (
    can_reuse_gate_file,
    compute_evidence_bundle_hash,
    load_evidence_bundle,
    load_gate_file,
    persist_evidence_record,
    persist_gate_file,
    write_gate_marker,
)
from story_automator.core.gate_audit import (
    EvidenceCollectedAudit,
    GateBoundaryViolation,
    GateStartedAudit,
    emit_gate_audit,
)
from story_automator.core.gate_rules import (
    aggregate_verdicts,
    verdict_for_collector_status,
)
from story_automator.core.gate_schema import (
    make_evidence_record,
    make_gate_file,
)
from story_automator.core.trust_boundary import (
    TrustBoundaryError,
    is_child_session,
    resolve_host_evidence_dir,
    sandbox_env,
    validate_evidence_path_isolation,
    verify_sandbox_env,
)


class BlindHunterEnforcementTests(unittest.TestCase):
    """Verify the child generation session cannot write evidence."""

    def _child_env(self) -> dict[str, str]:
        return {"STORY_AUTOMATOR_CHILD": "true"}

    def _host_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        return env

    def _sample_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_child_cannot_persist_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    persist_evidence_record(td, "gate-001", self._sample_record())

    def test_child_cannot_persist_gate_file(self) -> None:
        gate = make_gate_file(
            gate_id="gate-001",
            target={"kind": "story", "id": "1.1"},
            commit_sha="abc123",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    persist_gate_file(td, gate)

    def test_child_cannot_write_gate_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    write_gate_marker(td, "gate-001", "abc123")

    def test_child_can_read_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._host_env(), clear=True):
                persist_evidence_record(td, "gate-001", self._sample_record())
            with patch.dict(os.environ, self._child_env()):
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)

    def test_host_can_persist_and_read_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._host_env(), clear=True):
                persist_evidence_record(td, "gate-001", self._sample_record())
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["status"], "ok")


class SandboxEnvSecurityTests(unittest.TestCase):
    """Verify the sandbox env is properly sanitized."""

    def test_sandbox_env_passes_verification(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret", "PATH": "/usr"}, clear=True):
            env = sandbox_env(agent="claude")
            ok, violations = verify_sandbox_env(env)
            self.assertTrue(ok, f"violations: {violations}")

    def test_sandbox_env_child_is_detected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertTrue(is_child_session(env))

    def test_sandbox_env_strips_audit_key(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=True):
            env = sandbox_env()
            self.assertNotIn("BMAD_AUDIT_KEY", env)

    def test_host_is_not_child(self) -> None:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        self.assertFalse(is_child_session(env))


class EvidencePathIsolationTests(unittest.TestCase):
    """Verify evidence paths are outside child working tree."""

    def test_host_evidence_dir_not_under_child_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            evidence_dir = resolve_host_evidence_dir(project_root)
            child_tree = pathlib.Path(tempfile.mkdtemp())
            try:
                ok, _ = validate_evidence_path_isolation(evidence_dir, child_tree)
                self.assertTrue(ok)
            finally:
                child_tree.rmdir()

    def test_evidence_under_child_fails(self) -> None:
        with tempfile.TemporaryDirectory() as child_tree:
            evidence_dir = pathlib.Path(child_tree) / "_bmad" / "gate"
            ok, reason = validate_evidence_path_isolation(
                evidence_dir, pathlib.Path(child_tree)
            )
            self.assertFalse(ok)
            self.assertIn("under child working tree", reason)


class GateAuditChainTests(unittest.TestCase):
    """Verify gate events integrate with the HMAC audit chain."""

    def test_gate_started_chains_into_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = {"security": {"audit_trail": True}}
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-key"}):
                emit_gate_audit(
                    policy, audit_path,
                    GateStartedAudit(gate_id="g1", commit_sha="sha1", profile_hash="h1"),
                )
                emit_gate_audit(
                    policy, audit_path,
                    EvidenceCollectedAudit(
                        gate_id="g1", category="security", collector="c",
                        tool="semgrep", status="ok", duration_ms=100,
                    ),
                )
            lines = audit_path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 2)
            r1 = json.loads(lines[0])
            r2 = json.loads(lines[1])
            self.assertEqual(r1["seq"], 1)
            self.assertEqual(r2["seq"], 2)
            self.assertNotEqual(r1["tag"], r2["tag"])

    def test_boundary_violation_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = {"security": {"audit_trail": True}}
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-key"}):
                emit_gate_audit(
                    policy, audit_path,
                    GateBoundaryViolation(operation="persist", context="child"),
                )
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateBoundaryViolation")
            self.assertIn("tag", record)


def _init_test_repo(path: pathlib.Path) -> str:
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
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class TrustPipelineRoundTripTests(unittest.TestCase):
    """Full flow: host asserts context → fresh checkout → collect →
    evidence persist → bundle hash → gate file → audit event."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-pipeline-")
        self.project_root = pathlib.Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_test_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_pipeline_pass(self) -> None:
        host_env = dict(os.environ)
        host_env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, host_env, clear=True):
            with collector_checkout(self.project_root, self.sha) as checkout:
                record = run_collector_with_timeout(
                    [sys.executable, "-c", "print('ok')"],
                    collector="test",
                    tool="python",
                    category="correctness",
                    timeout_s=10,
                    cwd=str(checkout),
                )
                self.assertEqual(record["status"], "ok")
            path = persist_evidence_record(
                self.project_root, "gate-001", record,
            )
            self.assertTrue(path.exists())
            records = load_evidence_bundle(self.project_root, "gate-001")
            self.assertEqual(len(records), 1)
            bundle_hash = compute_evidence_bundle_hash(records)
            self.assertEqual(len(bundle_hash), 16)
            verdicts = {
                "correctness": verdict_for_collector_status(record["status"])
            }
            overall = aggregate_verdicts(verdicts)
            self.assertEqual(overall, "PASS")
            gate = make_gate_file(
                gate_id="gate-001",
                target={"kind": "story", "id": "1.1"},
                commit_sha=self.sha,
                profile={"id": "default", "version": 1, "hash": "prof-hash"},
                factory_version="0.1.0",
                categories={"correctness": {"verdict": "PASS"}},
                overall=overall,
                evidence_bundle_hash=bundle_hash,
            )
            persist_gate_file(self.project_root, gate)
            loaded = load_gate_file(self.project_root, "gate-001")
            self.assertEqual(loaded["overall"], "PASS")
            self.assertEqual(loaded["evidence_bundle_hash"], bundle_hash)

    def test_full_pipeline_fail_closed(self) -> None:
        host_env = dict(os.environ)
        host_env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, host_env, clear=True):
            record = run_collector_with_timeout(
                [sys.executable, "-c", "import sys; sys.exit(1)"],
                collector="test",
                tool="failing-tool",
                category="security",
                timeout_s=10,
            )
            self.assertEqual(record["status"], "violation")
            verdict = verdict_for_collector_status(record["status"])
            self.assertEqual(verdict, "FAIL")
            overall = aggregate_verdicts({"security": verdict})
            self.assertEqual(overall, "FAIL")

    def test_evidence_bundle_hash_deterministic(self) -> None:
        r1 = make_evidence_record(
            collector="a", tool="t1", category="c1", status="ok",
        )
        r2 = make_evidence_record(
            collector="b", tool="t2", category="c2", status="ok",
        )
        hash_a = compute_evidence_bundle_hash([r1, r2])
        hash_b = compute_evidence_bundle_hash([r2, r1])
        self.assertEqual(hash_a, hash_b)

    def test_gate_file_reuse_requires_matching_sha(self) -> None:
        gate = make_gate_file(
            gate_id="gate-002",
            target={"kind": "story", "id": "1.1"},
            commit_sha="sha-old",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        ok, reason = can_reuse_gate_file(
            gate, commit_sha="sha-new", profile_hash="h1", factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("commit_sha mismatch", reason)

    def test_collector_checkout_at_sha(self) -> None:
        (self.project_root / "src.py").write_text("x = 2\n")
        subprocess.run(
            ["git", "-C", str(self.project_root), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.project_root), "commit", "-m", "v2"],
            capture_output=True, check=True,
        )
        with collector_checkout(self.project_root, self.sha) as checkout:
            content = (checkout / "src.py").read_text()
            self.assertEqual(content, "x = 1\n")


if __name__ == "__main__":
    unittest.main()
