"""Tests for the orphan-worktree recovery helper (Phase 2)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.worktree_recovery import (
    list_orphan_candidates,
    recover_orphan_worktrees,
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
    (path / "a").write_text("1\n")
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


class RecoverOrphanWorktreesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-orph-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)
        # Isolate /tmp probe to a per-test scratch dir so concurrent
        # repos don't see each other's `sa-collector-*` leftovers.
        self.tmp_root = Path(self.tmpdir) / "tmp"
        self.tmp_root.mkdir()
        self._tmp_patcher = patch(
            "story_automator.core.worktree_recovery.tempfile.gettempdir",
            return_value=str(self.tmp_root),
        )
        self._tmp_patcher.start()

    def tearDown(self) -> None:
        self._tmp_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_repo_no_orphans(self) -> None:
        d = recover_orphan_worktrees(self.repo)
        self.assertTrue(d["pruned"])
        self.assertEqual(d["scratch_removed"], [])
        self.assertEqual(d["scratch_kept"], [])

    def test_old_orphan_dir_is_removed(self) -> None:
        orphan = self.tmp_root / "sa-collector-deadbeef"
        orphan.mkdir()
        # Backdate mtime to 2 hours ago — older than the default cutoff.
        old_time = time.time() - 7200
        import os

        os.utime(orphan, (old_time, old_time))
        d = recover_orphan_worktrees(self.repo)
        self.assertEqual(d["scratch_removed"], [str(orphan.resolve())])
        self.assertFalse(orphan.exists())

    def test_recent_orphan_is_kept(self) -> None:
        recent = self.tmp_root / "sa-collector-fresh"
        recent.mkdir()
        # mtime now → younger than the 1 h cutoff.
        d = recover_orphan_worktrees(self.repo)
        self.assertEqual(d["scratch_removed"], [])
        self.assertIn(str(recent.resolve()), d["scratch_kept"])
        self.assertTrue(recent.exists())

    def test_unrelated_tmp_dir_ignored(self) -> None:
        unrelated = self.tmp_root / "some-other-prefix-x"
        unrelated.mkdir()
        d = recover_orphan_worktrees(self.repo)
        # Neither removed nor kept — it's outside our prefix.
        self.assertNotIn(str(unrelated.resolve()), d["scratch_removed"])
        self.assertNotIn(str(unrelated.resolve()), d["scratch_kept"])
        self.assertTrue(unrelated.exists())

    def test_registered_worktree_is_kept_regardless_of_age(self) -> None:
        # Create a real git worktree and put it under our scratch prefix.
        wt = self.tmp_root / "sa-collector-real"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "--detach", str(wt), "HEAD"],
            capture_output=True,
            check=True,
        )
        import os

        old = time.time() - 7200
        os.utime(wt, (old, old))
        try:
            d = recover_orphan_worktrees(self.repo)
            self.assertEqual(d["scratch_removed"], [])
            self.assertIn(str(wt.resolve()), d["scratch_kept"])
            self.assertTrue(wt.exists())
        finally:
            subprocess.run(
                ["git", "-C", str(self.repo), "worktree", "remove", "--force", str(wt)],
                capture_output=True,
            )

    def test_min_age_s_zero_removes_all_orphans(self) -> None:
        orphan = self.tmp_root / "sa-collector-x"
        orphan.mkdir()
        d = recover_orphan_worktrees(self.repo, min_age_s=0)
        self.assertIn(str(orphan.resolve()), d["scratch_removed"])

    def test_descriptor_has_no_timestamps(self) -> None:
        d = recover_orphan_worktrees(self.repo)
        for v in d.values():
            self.assertNotIsInstance(v, float)
            if isinstance(v, str):
                self.assertNotIn("T", v[:20])  # rough ISO-8601 negative check

    def test_dry_run_list_orphan_candidates(self) -> None:
        orphan = self.tmp_root / "sa-collector-y"
        orphan.mkdir()
        import os

        old = time.time() - 7200
        os.utime(orphan, (old, old))
        cands = list_orphan_candidates(self.repo)
        self.assertIn(str(orphan.resolve()), cands)
        # The candidate must NOT have been removed.
        self.assertTrue(orphan.exists())

    def test_not_a_repo_still_returns_descriptor(self) -> None:
        not_a_repo = Path(self.tmpdir) / "nope"
        not_a_repo.mkdir()
        d = recover_orphan_worktrees(not_a_repo)
        # pruned is False (the git call failed), but the call still
        # returned a well-formed descriptor.
        self.assertFalse(d["pruned"])
        self.assertEqual(d["registered_paths"], 0)


class PerUnitWindowTests(unittest.TestCase):
    """AC-R-01..R-03 — per_unit_window_s safety margin (G2 §5.4 / §7.1)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-orph-puw-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)
        self.tmp_root = Path(self.tmpdir) / "tmp"
        self.tmp_root.mkdir()
        self._tmp_patcher = patch(
            "story_automator.core.worktree_recovery.tempfile.gettempdir",
            return_value=str(self.tmp_root),
        )
        self._tmp_patcher.start()

    def tearDown(self) -> None:
        self._tmp_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_scratch(self, name: str, age_s: float) -> Path:
        """Create a sa-collector-* dir aged ``age_s`` seconds in the past."""
        p = self.tmp_root / name
        p.mkdir()
        import os

        ts = time.time() - age_s
        os.utime(p, (ts, ts))
        return p

    def test_ac_r_01_default_per_unit_window_byte_identical(self) -> None:
        """AC-R-01 — default per_unit_window_s=0.0 keeps min_age_s in force.

        A scratch dir aged 1800s should be KEPT under min_age_s=3600.0
        (default) regardless of whether per_unit_window_s is unset
        (default 0.0) or explicitly set to 0.0.
        """
        orphan = self._make_scratch("sa-collector-default", age_s=1800.0)

        d_default = recover_orphan_worktrees(self.repo)
        self.assertEqual(d_default["scratch_removed"], [])
        self.assertIn(str(orphan.resolve()), d_default["scratch_kept"])

        d_explicit = recover_orphan_worktrees(
            self.repo,
            per_unit_window_s=0.0,
        )
        self.assertEqual(d_explicit["scratch_removed"], [])
        self.assertIn(str(orphan.resolve()), d_explicit["scratch_kept"])

    def test_ac_r_02_per_unit_window_overrides_smaller_min_age(self) -> None:
        """AC-R-02 — per_unit_window_s=120 with min_age_s=60 → eff=120.

        A scratch dir aged 90s is OLDER than min_age_s=60 but YOUNGER
        than per_unit_window_s=120. The effective threshold is the max
        (120), so this dir must be KEPT.
        A second dir aged 150s exceeds both thresholds → REMOVED.
        """
        young = self._make_scratch("sa-collector-young", age_s=90.0)
        old = self._make_scratch("sa-collector-old", age_s=150.0)

        d = recover_orphan_worktrees(
            self.repo,
            min_age_s=60.0,
            per_unit_window_s=120.0,
        )
        # young (90s) is under the effective threshold (120s) → kept.
        self.assertIn(str(young.resolve()), d["scratch_kept"])
        self.assertNotIn(str(young.resolve()), d["scratch_removed"])
        self.assertTrue(young.exists())
        # old (150s) is over the effective threshold (120s) → removed.
        self.assertIn(str(old.resolve()), d["scratch_removed"])
        self.assertFalse(old.exists())

    def test_ac_r_03_per_unit_window_does_not_lower_min_age(self) -> None:
        """AC-R-03 — per_unit_window_s=10 with min_age_s=3600 → eff=3600.

        per_unit_window_s NEVER lowers the threshold below min_age_s.
        A scratch dir aged 1200s is older than per_unit_window_s=10
        but younger than min_age_s=3600 → must be KEPT.
        """
        recent = self._make_scratch("sa-collector-recent", age_s=1200.0)

        d = recover_orphan_worktrees(
            self.repo,
            min_age_s=3600.0,
            per_unit_window_s=10.0,
        )
        self.assertEqual(d["scratch_removed"], [])
        self.assertIn(str(recent.resolve()), d["scratch_kept"])
        self.assertTrue(recent.exists())


if __name__ == "__main__":
    unittest.main()
