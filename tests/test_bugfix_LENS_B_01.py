"""Regression tests for LENS-B-01.

``_AppendLock`` formerly unlinked the lockfile on ``__exit__`` even after a
peer had stolen the lock. After a steal, the lockfile on disk belongs to the
*new* owner, so unlinking it lets a third process race with the new owner —
defeating the mutual-exclusion guarantee that protects the read-modify-write
inside :func:`append_entry`.

The fix is to write a per-instance nonce into the lockfile on creation, then
only unlink during ``__exit__`` if the lockfile still contains *our* nonce.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from story_automator.core.deferred_work import (
    _LOCK_STEAL_SECONDS,
    _AppendLock,
    _lock_path,
    append_entry,
)


class AppendLockNonceTests(unittest.TestCase):
    """The lockfile must identify which holder created it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lockfile = Path(self.tmp.name) / "ledger.md.lock"

    def test_lockfile_contains_nonzero_payload_after_enter(self) -> None:
        """After acquiring the lock the file must carry an identifying token."""
        lock = _AppendLock(self.lockfile)
        with lock:
            self.assertTrue(self.lockfile.exists())
            # The bug fix requires writing a token; an empty file means we
            # cannot tell ownership apart from a stolen lock.
            self.assertGreater(self.lockfile.stat().st_size, 0)

    def test_two_acquisitions_use_distinct_tokens(self) -> None:
        """Sequential acquisitions must produce distinct ownership tokens."""
        first = _AppendLock(self.lockfile)
        with first:
            token_a = self.lockfile.read_bytes()
        second = _AppendLock(self.lockfile)
        with second:
            token_b = self.lockfile.read_bytes()
        self.assertNotEqual(token_a, token_b)

    def test_exit_does_not_unlink_stolen_lock(self) -> None:
        """If a peer steals our lock, our __exit__ must NOT unlink theirs.

        This is the core LENS-B-01 regression: process A's lock goes stale,
        process B steals (creating its own lockfile), then A finally finishes
        and runs __exit__. Before the fix, A unconditionally unlinked the
        lockfile — destroying B's mutual exclusion. After the fix, A sees
        the token does not match and leaves the file alone.
        """
        # Step 1: process A acquires.
        lock_a = _AppendLock(self.lockfile)
        lock_a.__enter__()
        try:
            self.assertTrue(self.lockfile.exists())

            # Step 2: simulate A's lock going stale, then B steals.
            # We mimic a steal by overwriting the lockfile with B's payload.
            # This is exactly what the steal branch in __enter__ does in a
            # different instance (unlink + recreate).
            self.lockfile.unlink()
            with open(self.lockfile, "xb") as fh:
                fh.write(b"process-B-token")
            b_token = self.lockfile.read_bytes()

            # Step 3: A's __exit__ runs. With the bug, this unlinks the
            # lockfile that now belongs to B.
            lock_a.__exit__(None, None, None)

            # Step 4: assert B's lockfile survived.
            self.assertTrue(
                self.lockfile.exists(),
                "A.__exit__ deleted B's lockfile — mutual exclusion broken",
            )
            self.assertEqual(self.lockfile.read_bytes(), b_token)
        finally:
            if self.lockfile.exists():
                self.lockfile.unlink()

    def test_exit_unlinks_when_token_still_ours(self) -> None:
        """The normal happy-path cleanup must still remove the lockfile."""
        lock = _AppendLock(self.lockfile)
        with lock:
            self.assertTrue(self.lockfile.exists())
        self.assertFalse(
            self.lockfile.exists(),
            "happy-path __exit__ failed to remove our own lockfile",
        )

    def test_steal_then_normal_acquire_roundtrip(self) -> None:
        """End-to-end: A enters, A is stolen, B owns, A.__exit__ no-ops, B exits clean."""
        lock_a = _AppendLock(self.lockfile)
        lock_a.__enter__()

        # B steals manually (overwrites lockfile contents under A's nose).
        self.lockfile.unlink()
        lock_b = _AppendLock(self.lockfile)
        lock_b.__enter__()

        # A exits: must NOT remove B's lockfile.
        lock_a.__exit__(None, None, None)
        self.assertTrue(self.lockfile.exists())

        # B exits: must remove its own lockfile.
        lock_b.__exit__(None, None, None)
        self.assertFalse(self.lockfile.exists())


class AppendEntrySurvivesStealRaceTests(unittest.TestCase):
    """Integration-ish check that :func:`append_entry` still serializes.

    Even if a stale-lock steal races with the original holder, the append
    must produce a coherent ledger — the symptom of LENS-B-01 in the wild
    is lost entries because the steal-victim's __exit__ removed the lockfile
    while the new holder was still mid read-modify-write.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project_root = Path(self.tmp.name)

    def test_stale_steal_does_not_lose_subsequent_append(self) -> None:
        # Seed a stale lockfile that the steal logic will replace.
        target = self.project_root / "_bmad" / "bmm" / "deferred-work.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        stale_lock = _lock_path(target)
        stale_lock.write_bytes(b"orphaned-from-crashed-process")
        old = time.time() - (_LOCK_STEAL_SECONDS + 5)
        os.utime(stale_lock, (old, old))

        # An append must succeed and leave the ledger consistent.
        append_entry(
            self.project_root,
            title="entry-after-steal",
            reason="r",
            owner_story="s",
            severity="CRITICAL",
        )
        contents = target.read_text(encoding="utf-8")
        self.assertIn("entry-after-steal", contents)
        # And the lockfile must be cleaned up by the legitimate holder.
        self.assertFalse(stale_lock.exists())


if __name__ == "__main__":
    unittest.main()
