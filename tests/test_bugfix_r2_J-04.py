"""Bug R2 / J-04 — load_session_state silently swallows corruption.

Reported defect (tmux_runtime.py lines 201, 216, 261):

``load_session_state`` returned ``{}`` for BOTH an absent file AND a corrupt
JSON file. Two cascading failures followed:

1. **State loss on corruption** — ``update_session_state`` called
   ``load_session_state`` first to merge updates on top of the existing dict.
   If the file existed but was corrupt, the loader returned ``{}`` and the
   updater happily wrote a fresh state containing ONLY the new fields. All
   prior session metadata (childPid, paneId, lifecycle, startedAt, ...) was
   permanently lost.

2. **Durable artifact leak** — ``cleanup_stale_terminal_artifacts`` treated a
   non-terminal state as "live and protected", so paired command/runner/output
   files were skipped from cleanup. A corrupt state file (parsed as ``{}``,
   ``_is_terminal_state({}) == False``) thus protected the session forever:
   the corrupt state file never aged out (it was added to protected_sessions
   above the mtime check, and the load_session_state path never deleted it).

Fix design (minimal, additive):

- ``load_session_state`` now distinguishes absent from corrupt. On corruption
  (OSError, JSONDecodeError, or non-dict JSON root) it renames the offending
  file to ``<path>.corrupted-<epoch>`` and logs a warning. From the caller's
  perspective the result is still ``{}`` — but the file is no longer present,
  so update_session_state writes a clean fresh state and the cleanup sweep
  is no longer wedged.
- ``update_session_state`` calls a strict loader that distinguishes the
  three states. If the underlying file was corrupt, refuse to write (raise
  ``CorruptSessionStateError``) — clobbering the renamed forensic file with
  partial updates would be the original bug all over again. Callers that
  want corruption-tolerant behavior call load_session_state then save.
- Renamed ``.corrupted-*`` artifacts are themselves cleaned by the existing
  cleanup-stale sweep once they age past the TTL (they are not state files
  and don't match the protected-state glob).
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from story_automator.core.tmux_runtime import (
    CorruptSessionStateError,
    cleanup_stale_terminal_artifacts,
    generate_session_name,
    load_session_state,
    session_paths,
    update_session_state,
)


class LoadSessionStateRenamesCorruptFile(unittest.TestCase):
    """Corrupt-JSON state file is renamed out of the way; loader returns {}."""

    def test_corrupt_json_is_renamed_aside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("{this is not json", encoding="utf-8")

            result = load_session_state(state_path)
            self.assertEqual(result, {})
            # Original path is now gone — file was moved aside.
            self.assertFalse(
                state_path.exists(),
                "corrupt state file should have been renamed aside",
            )
            # A sibling .corrupted-* artifact exists for forensics.
            siblings = list(Path(tmp).glob("state.json.corrupted-*"))
            self.assertEqual(
                len(siblings), 1,
                f"expected exactly one .corrupted-* artifact, got {siblings!r}",
            )
            # Content of the moved file is preserved (forensic value).
            self.assertEqual(
                siblings[0].read_text(encoding="utf-8"),
                "{this is not json",
            )

    def test_non_dict_root_is_treated_as_corrupt(self) -> None:
        # JSON parses fine but root is a list — meaningless as session state.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("[1, 2, 3]", encoding="utf-8")

            result = load_session_state(state_path)
            self.assertEqual(result, {})
            self.assertFalse(state_path.exists())
            self.assertEqual(
                len(list(Path(tmp).glob("state.json.corrupted-*"))), 1,
            )

    def test_absent_file_is_not_treated_as_corrupt(self) -> None:
        # Absent file → return {} silently, NO .corrupted-* sibling created.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "missing.json"
            result = load_session_state(state_path)
            self.assertEqual(result, {})
            self.assertEqual(
                list(Path(tmp).glob("missing.json.corrupted-*")), [],
            )


class UpdateSessionStateRefusesToWriteOverCorrupt(unittest.TestCase):
    """update_session_state must not clobber prior state when file is corrupt.

    Before the fix: load_session_state returned {}, update_session_state then
    wrote a fresh state containing only the updates, permanently destroying
    all the prior fields (lifecycle, childPid, paneId, ...).
    """

    def test_update_on_corrupt_state_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("not json at all", encoding="utf-8")

            with self.assertRaises(CorruptSessionStateError):
                update_session_state(state_path, lifecycle="running")


class CleanupAgesOutCorruptStateSessions(unittest.TestCase):
    """A session whose state file is corrupt must NOT be protected forever.

    Before the fix: load_session_state returned {} for the corrupt file,
    _is_terminal_state({}) was False, so the session joined protected_sessions
    and every paired command/runner/output file was preserved across every
    cleanup pass — durable artifact leak.

    After the fix: load_session_state renames the corrupt state file aside on
    first read, so the cleanup sweep no longer sees a state file at all for
    that session — paired artifacts age out normally on their own TTL.
    """

    def test_corrupt_state_does_not_protect_paired_artifacts_forever(self) -> None:
        # Build a real session-paths layout in $TMPDIR so the cleanup sweep
        # picks up the artifacts via its own globs.
        with tempfile.TemporaryDirectory() as project_root:
            session = generate_session_name("dev", "1", "1.0")
            paths = session_paths(session, project_root)
            # Write a corrupt state file. It is brand-new — without the fix
            # its non-terminal status would protect the artifacts even if we
            # made the paired files ancient.
            paths.state.write_text("{not json", encoding="utf-8")
            paths.command.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
            paths.runner.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
            paths.output.write_text("captured\n", encoding="utf-8")
            # Age the paired artifacts well past the TTL.
            ancient = time.time() - 48 * 3600
            for p in (paths.command, paths.runner, paths.output):
                os.utime(p, (ancient, ancient))
            # Age the corrupt state file too — even if we age it, the previous
            # implementation would (a) load it as {}, (b) add the session to
            # protected_sessions because {} is non-terminal, (c) skip cleanup
            # of the paired files. With the fix, load_session_state renames
            # the corrupt file aside on first read so it is no longer present
            # for the protection check.
            os.utime(paths.state, (ancient, ancient))

            cleanup_stale_terminal_artifacts(project_root)

            # Paired artifacts must have been cleaned (no longer "protected"
            # by a corrupt state file).
            self.assertFalse(paths.command.exists(), "command artifact leaked")
            self.assertFalse(paths.runner.exists(), "runner artifact leaked")
            self.assertFalse(paths.output.exists(), "output artifact leaked")


if __name__ == "__main__":
    unittest.main()
