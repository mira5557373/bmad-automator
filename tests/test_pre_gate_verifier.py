"""Tests for the six inline pre-gate checks (Phase 3)."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.pre_gate_verifier import (
    CHECK_NAMES,
    verify_pre_gate,
)
from story_automator.core.result_json import (
    make_session_result,
    write_result_json,
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
    (path / "a").write_text("1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _add_commit(path: Path, filename: str, content: str = "y\n") -> str:
    (path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", filename],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class CheckNamesTests(unittest.TestCase):
    def test_six_checks_in_fixed_order(self) -> None:
        self.assertEqual(
            CHECK_NAMES,
            (
                "result_present",
                "result_schema",
                "baseline_commit",
                "files_present",
                "no_critical_escalations",
                "claimed_files_in_diff",
            ),
        )


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-pgv-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.baseline = _init_repo(self.repo)
        self.result_path = Path(self.tmpdir) / "result.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class CheckResultPresentTests(_Fixture):
    def test_missing_result_json_first_check_fails(self) -> None:
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertFalse(d["ok"])
        self.assertEqual(d["failed_check"], "result_present")
        self.assertEqual(d["verify"]["reason"], "missing_result_json")
        self.assertTrue(d["verify"]["fixable"])
        self.assertIsNone(d["payload"])


class CheckResultSchemaTests(_Fixture):
    def test_invalid_schema_caught_at_check_2(self) -> None:
        self.result_path.write_text(json.dumps({"api_version": 1}))
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertFalse(d["ok"])
        self.assertEqual(d["failed_check"], "result_schema")
        self.assertIn("result_json_invalid", d["verify"]["reason"])
        self.assertTrue(d["verify"]["fixable"])

    def test_api_version_mismatch_escalates(self) -> None:
        self.result_path.write_text(json.dumps({
            "api_version": 99,
            "claims": {"commit_sha": "x" * 40, "files_changed": [], "summary": "s"},
            "spec_file": "",
            "escalations": [],
        }))
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertEqual(d["failed_check"], "result_schema")
        self.assertEqual(d["verify"]["severity"], "CRITICAL")
        self.assertFalse(d["verify"]["fixable"])

    def test_invalid_json_caught(self) -> None:
        self.result_path.write_text("{not json")
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertEqual(d["failed_check"], "result_schema")
        self.assertIn("result_json_unreadable", d["verify"]["reason"])


class CheckBaselineCommitTests(_Fixture):
    def test_head_matches_claimed_passes(self) -> None:
        write_result_json(self.result_path, make_session_result(
            commit_sha=self.baseline, files_changed=[], summary="s",
        ))
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        # Note: passes for now but check 6 might still trigger. With
        # no claimed files and no baseline_sha, check 6 passes too.
        self.assertTrue(d["ok"])
        self.assertEqual(d["failed_check"], "")

    def test_head_at_baseline_when_session_claims_new_sha(self) -> None:
        write_result_json(self.result_path, make_session_result(
            commit_sha="deadbeef" * 5, files_changed=[], summary="s",
        ))
        d = verify_pre_gate(
            self.repo,
            result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(d["failed_check"], "baseline_commit")
        self.assertEqual(d["verify"]["reason"], "baseline_drift")

    def test_empty_claimed_commit_sha(self) -> None:
        # claims.commit_sha == "" should fail before lie-detector runs.
        write_result_json(self.result_path, make_session_result(
            commit_sha="", files_changed=[], summary="s",
        ))
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertEqual(d["failed_check"], "baseline_commit")
        self.assertIn("missing_claimed_commit_sha", d["verify"]["reason"])


class CheckFilesPresentTests(_Fixture):
    def test_missing_file_caught(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py", "phantom.py"],
            summary="s",
        ))
        d = verify_pre_gate(self.repo, result_path=self.result_path)
        self.assertEqual(d["failed_check"], "files_present")
        self.assertIn("phantom.py", d["verify"]["reason"])

    def test_all_files_present_passes(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py"],
            summary="s",
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertTrue(d["ok"])


class CheckNoCriticalEscalationsTests(_Fixture):
    def test_critical_escalation_escalates(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py"],
            summary="s",
            escalations=[
                {"severity": "CRITICAL", "reason": "data loss risk"},
            ],
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(d["failed_check"], "no_critical_escalations")
        self.assertEqual(d["verify"]["severity"], "CRITICAL")
        self.assertFalse(d["verify"]["fixable"])

    def test_preference_escalation_does_not_block(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py"],
            summary="s",
            escalations=[
                {"severity": "PREFERENCE", "reason": "style"},
            ],
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertTrue(d["ok"])


class CheckClaimedFilesInDiffTests(_Fixture):
    def test_unchanged_file_claimed_is_drift(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        # Claim 'a' (which was in the baseline, not touched here) as if
        # we'd modified it. The diff baseline..HEAD will not include 'a'.
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["a"],
            summary="s",
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(d["failed_check"], "claimed_files_in_diff")
        self.assertIn("a", d["verify"]["reason"])

    def test_claimed_file_in_diff_passes(self) -> None:
        new_sha = _add_commit(self.repo, "c.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["c.py"],
            summary="s",
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertTrue(d["ok"])

    def test_no_baseline_skips_diff_check(self) -> None:
        # claims includes a file that is NOT in the worktree; that means
        # check 4 (files_present) will catch it first. So make the file
        # exist on disk and have an empty diff scenario: HEAD ==
        # baseline (no commit), no baseline_sha provided.
        (self.repo / "extra.py").write_text("x\n")
        # No new commit; HEAD is still baseline.
        write_result_json(self.result_path, make_session_result(
            commit_sha=self.baseline,
            files_changed=["extra.py"],
            summary="s",
        ))
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=None,  # skip diff check
        )
        self.assertTrue(d["ok"])


class FirstFailureWinsTests(_Fixture):
    def test_check1_failure_skips_all_others(self) -> None:
        # No result.json on disk. Even if a later check would also fail,
        # we only see check 1's failure.
        d = verify_pre_gate(
            self.repo, result_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(d["failed_check"], "result_present")
        self.assertIsNone(d["payload"])


if __name__ == "__main__":
    unittest.main()
