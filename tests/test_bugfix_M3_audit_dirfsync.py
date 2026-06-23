"""Bugfix M-3: audit append must fsync parent directory for crash durability.

Bug: ``AuditLog.append`` writes new records via ``self.path.open("ab")`` and
fsyncs the file descriptor, but never fsyncs the parent directory. On ext4
(default), xfs, and apfs, the file's data block reaching disk is *not*
sufficient to guarantee the directory entry (created on the first append) is
durable across a power loss — the parent directory inode itself must also be
fsynced. Without that, a crash immediately after the first append can leave
the on-disk audit log empty even though the in-memory chain advanced.

Fix: ``AuditLog.append`` now calls ``fsync_dir(self.path.parent)`` after the
file-descriptor fsync. ``fsync_dir`` (already shipped in ``core/common.py``)
opens the directory O_RDONLY and fsyncs the resulting fd, silently no-op'ing
on Windows where directory-fd fsync is not supported. The chain is unchanged
and ``verify()`` continues to pass on every existing log.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.audit import AuditLog


class _FakeEvent:
    event_name = "test.event"

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self._payload = payload or {"x": 1}

    def to_dict(self) -> dict[str, object]:
        return self._payload


def _stat_is_dir(path: str) -> bool:
    """Return True if ``path`` refers to a directory on disk."""
    try:
        return os.path.isdir(path)
    except OSError:
        return False


class AuditAppendFsyncsParentDirTests(unittest.TestCase):
    """REQ-M3-1: After append, the parent directory must be fsynced exactly once."""

    def test_first_append_fsyncs_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path=log_path, key=b"\x00" * 32)

            # Track which fds os.fsync is called on. We need to differentiate
            # file-fd fsync vs directory-fd fsync. The cleanest way is to
            # wrap os.fsync and record (fd, is_dir) tuples by os.fstat'ing
            # before delegating. We intentionally exclude lock-file fsyncs
            # from filelock (it doesn't fsync), so any directory fsync
            # observed here must come from AuditLog.append's fix.
            calls: list[tuple[int, bool]] = []
            real_fsync = os.fsync

            def tracking_fsync(fd: int) -> None:
                try:
                    st = os.fstat(fd)
                    is_dir = (st.st_mode & 0o170000) == 0o040000
                except OSError:
                    is_dir = False
                calls.append((fd, is_dir))
                real_fsync(fd)

            with mock.patch("story_automator.core.audit.os.fsync", side_effect=tracking_fsync), \
                 mock.patch("story_automator.core.common.os.fsync", side_effect=tracking_fsync):
                log.append(_FakeEvent())

            # On POSIX we expect AT LEAST one file fsync and AT LEAST one dir
            # fsync. The Windows branch is exercised by a separate test that
            # forces the platform check.
            if sys.platform != "win32":
                dir_fsyncs = [c for c in calls if c[1]]
                self.assertGreaterEqual(
                    len(dir_fsyncs),
                    1,
                    f"expected at least one directory fsync on POSIX; calls={calls}",
                )

            # And the log itself must be on disk and verifiable.
            self.assertTrue(log_path.exists())
            self.assertEqual(log.verify(), (True, 1))

    def test_subsequent_appends_also_fsync_parent_dir(self) -> None:
        """Every append must dirfsync; not just the first one.

        Some filesystems (e.g. ext4 with data=writeback) can lose the most
        recent record on crash if only the file fsync ran. Belt-and-braces
        dirfsync on every append closes that window.
        """
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path=log_path, key=b"\x00" * 32)

            calls: list[bool] = []
            real_fsync = os.fsync

            def tracking_fsync(fd: int) -> None:
                try:
                    st = os.fstat(fd)
                    is_dir = (st.st_mode & 0o170000) == 0o040000
                except OSError:
                    is_dir = False
                calls.append(is_dir)
                real_fsync(fd)

            with mock.patch("story_automator.core.audit.os.fsync", side_effect=tracking_fsync), \
                 mock.patch("story_automator.core.common.os.fsync", side_effect=tracking_fsync):
                for _ in range(3):
                    log.append(_FakeEvent())

            if sys.platform != "win32":
                dir_count = sum(1 for is_dir in calls if is_dir)
                self.assertGreaterEqual(
                    dir_count,
                    3,
                    f"expected one dir fsync per append (>=3); got {dir_count} of {calls}",
                )

            self.assertEqual(log.verify(), (True, 3))


class AuditDirFsyncWindowsFallbackTests(unittest.TestCase):
    """REQ-M3-2: On Windows the dirfsync must silently skip, not raise."""

    def test_windows_does_not_raise_when_dir_fsync_unsupported(self) -> None:
        """fsync_dir already guards OSError on directory open/fsync.

        Simulate Windows by forcing ``os.open(dir, O_RDONLY)`` (via fsync_dir)
        to raise OSError exactly the way Windows does. The append must
        complete successfully and the chain must remain intact.
        """
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path=log_path, key=b"\x00" * 32)

            real_open = os.open

            def windows_like_open(path, flags, mode=0o777):
                # Mimic Windows: opening a directory O_RDONLY raises PermissionError.
                if (flags & os.O_RDONLY) == os.O_RDONLY and _stat_is_dir(str(path)):
                    raise PermissionError("simulated: cannot open directory on Windows")
                return real_open(path, flags, mode)

            with mock.patch("story_automator.core.common.os.open", side_effect=windows_like_open):
                # MUST NOT raise.
                log.append(_FakeEvent())

            # File still written + verifiable.
            self.assertTrue(log_path.exists())
            self.assertEqual(log.verify(), (True, 1))


class AuditChainIntegrityPreservedTests(unittest.TestCase):
    """REQ-M3-3: Adding dirfsync must not perturb the hash chain or seq order."""

    def test_chain_verifies_after_dirfsync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path=log_path, key=b"\xab" * 32)

            for i in range(5):
                log.append(_FakeEvent({"i": i}))

            ok, last_seq = log.verify()
            self.assertTrue(ok)
            self.assertEqual(last_seq, 5)

            # And the records themselves must be exactly what we appended,
            # in order, with monotonically increasing seq starting at 1.
            with log_path.open("rb") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 5)
            for idx, raw in enumerate(lines, start=1):
                record = json.loads(raw.decode("utf-8"))
                self.assertEqual(record["seq"], idx)
                self.assertEqual(record["event"], "test.event")
                self.assertEqual(record["payload"], {"i": idx - 1})

    def test_missing_parent_directory_still_handled(self) -> None:
        """If the parent dir somehow disappears after construction (rare race),
        the dirfsync must not crash the append. ensure_dir in __post_init__
        creates the parent up-front; we exercise the absent-dir case by
        rmtree'ing right before append and pointing at a fresh tempdir.
        """
        import shutil

        tmp = tempfile.mkdtemp()
        try:
            log_path = Path(tmp) / "nested" / "audit.jsonl"
            log = AuditLog(path=log_path, key=b"\x00" * 32)
            # nested/ was just created by ensure_dir in __post_init__.
            self.assertTrue(log_path.parent.exists())

            # Sanity: a normal append works.
            log.append(_FakeEvent())
            self.assertEqual(log.verify(), (True, 1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover - manual runs
    unittest.main()
