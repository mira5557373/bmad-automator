"""G7 — tests for the unified sprint-status / Phase store surface.

Covers every behavioral case from
``docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md``
§6.2: clean reads, migration writes, conflict resolution via LWW with
mtime-tie tie-break, observe_only, slug-key reconciliation, lock
serialisation, and the read-repair self-cancellation guard.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from typing import List

from story_automator.core.integration import (
    UnifiedStateError,
    UnifiedStateFileMissingError,
    UnifiedStateRowMissingError,
    read_unified_state,
    unified_state_lock,
    write_unified_state,
)
from story_automator.core.integration.sprint_phase_map import (
    Phase,
    is_consistent,
    phase_for_sprint_status,
    phase_store_path,
    read_phase_store,
    write_phase,
)
from story_automator.core.sprint import sprint_status_get
from story_automator.core.story_keys import sprint_status_file


SPRINT_STATUS_FIXTURE = textwrap.dedent(
    """\
    development_status:
      1-1-host-feasibility-probe: in-progress
      1-2-docker-dev-test-environment: done
      2-1-users-schema: not_started
    """
)


def _materialise(root: str, body: str | None = SPRINT_STATUS_FIXTURE) -> Path:
    sprint_path = Path(sprint_status_file(root))
    sprint_path.parent.mkdir(parents=True, exist_ok=True)
    if body is not None:
        sprint_path.write_text(body, encoding="utf-8")
    Path(phase_store_path(root)).parent.mkdir(parents=True, exist_ok=True)
    return sprint_path


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        _materialise(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class CleanStateReadTests(_Base):
    """#1 — clean state two-store fixture, deterministic, no lock taken."""

    def test_clean_state_returns_pair_deterministic(self) -> None:
        # Seed a consistent pair under the canonical key.
        write_phase(self.root, "1.1", Phase.DEV_RUNNING)
        lock_path = Path(self.root) / "_bmad-output" / "implementation-artifacts" / ".unified-state.lock"
        mtime_before = lock_path.stat().st_mtime_ns if lock_path.exists() else None

        a = read_unified_state(self.root, "1.1")
        b = read_unified_state(self.root, "1.1")
        self.assertEqual(a, b)
        self.assertEqual(a, ("in-progress", "dev-running", False))

        if mtime_before is not None and lock_path.exists():
            self.assertEqual(lock_path.stat().st_mtime_ns, mtime_before)


class MissingPhaseMigrationTests(_Base):
    """#2 — phase store empty + known sprint-status row → materialise."""

    def test_missing_phase_materialises_derived_pair(self) -> None:
        result = read_unified_state(self.root, "1.1")
        self.assertEqual(result, ("in-progress", "dev-running", False))
        store = read_phase_store(self.root)
        self.assertEqual(store.get("1.1"), Phase.DEV_RUNNING)


class UnknownStatusReadTests(_Base):
    """#3 — unknown sprint-status string → (status, pending, True), no write."""

    def test_unknown_status_returns_pending_no_write(self) -> None:
        body = textwrap.dedent(
            """\
            development_status:
              1-1-host-feasibility-probe: weird-status
            """
        )
        _materialise(self.root, body)
        result = read_unified_state(self.root, "1.1")
        self.assertEqual(result, ("weird-status", "pending", True))
        # No write to the phase store on unknown status.
        self.assertEqual(read_phase_store(self.root), {})


class MissingRowReadTests(unittest.TestCase):
    """#4 — split into file-missing vs row-missing error subclasses."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        Path(phase_store_path(self.root)).parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file_raises_file_missing_error(self) -> None:
        # No sprint-status.yaml on disk at all.
        with self.assertRaises(UnifiedStateFileMissingError):
            read_unified_state(self.root, "1.1")

    def test_missing_row_raises_row_missing_error(self) -> None:
        # File exists but row absent.
        sprint_path = Path(sprint_status_file(self.root))
        sprint_path.parent.mkdir(parents=True, exist_ok=True)
        sprint_path.write_text(
            "development_status:\n  9-9-other: in-progress\n", encoding="utf-8"
        )
        with self.assertRaises(UnifiedStateRowMissingError):
            read_unified_state(self.root, "1.1")


class ConflictLwwTests(_Base):
    """#5/#6 — LWW resolution by mtime."""

    def _seed_conflict(self, phase_newer: bool) -> None:
        # sprint-status row says "in-progress" → derives to dev-running.
        # phase store has Phase.DONE → inconsistent.
        write_phase(self.root, "1.1", Phase.DONE)
        sprint_path = Path(sprint_status_file(self.root))
        phase_path = phase_store_path(self.root)
        # Bump mtimes to known integer-ns values to force the desired winner.
        base = 1_700_000_000_000_000_000  # arbitrary ns timestamp
        if phase_newer:
            os.utime(sprint_path, ns=(base, base))
            os.utime(phase_path, ns=(base + 1_000_000, base + 1_000_000))
        else:
            os.utime(phase_path, ns=(base, base))
            os.utime(sprint_path, ns=(base + 1_000_000, base + 1_000_000))

    def test_conflict_lww_phase_newer(self) -> None:
        self._seed_conflict(phase_newer=True)
        result = read_unified_state(self.root, "1.1")
        # Phase wins (Phase.DONE): sprint-status rewritten to "done".
        self.assertEqual(result, ("done", "done", False))
        after = sprint_status_get(self.root, "1.1")
        self.assertEqual(after.status, "done")

    def test_conflict_lww_sprint_newer(self) -> None:
        self._seed_conflict(phase_newer=False)
        result = read_unified_state(self.root, "1.1")
        # Sprint wins ("in-progress" → dev-running): phase store rewritten.
        self.assertEqual(result, ("in-progress", "dev-running", False))
        store = read_phase_store(self.root)
        self.assertEqual(store.get("1.1"), Phase.DEV_RUNNING)


class WriteAtomicTests(_Base):
    """#7/#8/#9 — atomic write + consistency validation + enum/string."""

    def test_write_unified_state_atomic_both_stores_present(self) -> None:
        write_unified_state(self.root, "1.1", "review-running", Phase.REVIEW_RUNNING)
        self.assertEqual(
            read_unified_state(self.root, "1.1"),
            ("review-running", "review-running", False),
        )
        self.assertEqual(read_phase_store(self.root).get("1.1"), Phase.REVIEW_RUNNING)

    def test_write_unified_state_inconsistent_pair_raises_before_write(self) -> None:
        sprint_path = Path(sprint_status_file(self.root))
        phase_path = phase_store_path(self.root)
        sprint_before = sprint_path.read_bytes()
        # Phase store may not exist yet — capture absence.
        phase_exists_before = phase_path.exists()
        phase_before = phase_path.read_bytes() if phase_exists_before else None

        with self.assertRaises(UnifiedStateError):
            write_unified_state(self.root, "1.1", "done", Phase.DEV_RUNNING)

        self.assertEqual(sprint_path.read_bytes(), sprint_before)
        self.assertEqual(phase_path.exists(), phase_exists_before)
        if phase_exists_before:
            self.assertEqual(phase_path.read_bytes(), phase_before)

    def test_write_unified_state_phase_accepts_enum_or_string(self) -> None:
        write_unified_state(self.root, "1.1", "dev-running", Phase.DEV_RUNNING)
        phase_path = phase_store_path(self.root)
        bytes_enum = phase_path.read_bytes()

        # Reset to a different value then back to dev-running via the string
        # form — the resulting phase-store bytes must match the enum form.
        write_unified_state(self.root, "1.1", "review-running", Phase.REVIEW_RUNNING)
        write_unified_state(self.root, "1.1", "dev-running", "dev-running")
        bytes_string = phase_path.read_bytes()
        self.assertEqual(bytes_enum, bytes_string)


class ConcurrentWritersTests(_Base):
    """#10 — concurrent writers serialize via the lock."""

    def test_concurrent_writers_serialize_via_lock(self) -> None:
        # Seed sprint-status with 4 rows that all currently say in-progress.
        body = textwrap.dedent(
            """\
            development_status:
              1-1-host-feasibility-probe: in-progress
              1-2-docker-dev-test-environment: in-progress
              2-1-users-schema: in-progress
              3-1-something: in-progress
            """
        )
        _materialise(self.root, body)
        targets = [
            ("1.1", "dev-running", Phase.DEV_RUNNING),
            ("1.2", "review-running", Phase.REVIEW_RUNNING),
            ("2.1", "committing", Phase.COMMITTING),
            ("3.1", "done", Phase.DONE),
        ]
        errors: List[Exception] = []

        def _writer(key: str, sprint: str, phase: Phase) -> None:
            try:
                write_unified_state(self.root, key, sprint, phase)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_writer, args=(k, s, p)) for k, s, p in targets
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"writer errors: {errors}")
        store = read_phase_store(self.root)
        for k, _s, p in targets:
            self.assertEqual(store.get(k), p, f"missing phase entry for {k}")
        # No torn lines — sprint-status YAML still parses cleanly.
        sprint_path = Path(sprint_status_file(self.root))
        for line in sprint_path.read_text(encoding="utf-8").splitlines():
            self.assertNotIn("\x00", line)


class LockTimeoutTests(_Base):
    """#11 — lock-timeout raises UnifiedStateError, not filelock.Timeout."""

    def test_lock_timeout_raises_unified_state_error(self) -> None:
        # Pre-acquire the lock from this thread, then call writer with a
        # short timeout from another thread — it MUST raise UnifiedStateError.
        holder = unified_state_lock(self.root)
        holder.acquire(timeout=5.0)
        errors: List[Exception] = []

        def _writer() -> None:
            try:
                write_unified_state(
                    self.root, "1.1", "dev-running", Phase.DEV_RUNNING,
                    lock_timeout=0.1,
                )
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=_writer)
        t.start()
        t.join(timeout=5.0)
        try:
            self.assertEqual(len(errors), 1, f"errors: {errors}")
            exc = errors[0]
            self.assertIsInstance(exc, UnifiedStateError)
            self.assertIn("timeout", str(exc).lower())
        finally:
            holder.release()


class CallSiteCompatTests(_Base):
    """#12 — M48 call sites still work on state produced by G7."""

    def test_m48_call_sites_still_work(self) -> None:
        from story_automator.core.integration.sprint_phase_map import (
            compute_dual_state,
            validate_dual_store,
        )
        write_unified_state(self.root, "1.1", "in-progress", Phase.DEV_RUNNING)
        state = compute_dual_state(self.root, "1.1")
        self.assertTrue(state.consistent)
        self.assertEqual(validate_dual_store(self.root), [])


class ContextManagerTests(_Base):
    """#13 — `with unified_state_lock(root): ...` blocks sibling acquisition."""

    def test_lock_context_manager_round_trip(self) -> None:
        observed: List[bool] = []
        sibling_done = threading.Event()

        def _sibling() -> None:
            # While the main thread holds the lock, this acquisition must
            # block. Use a generous timeout to avoid flakes.
            try:
                write_unified_state(
                    self.root, "1.1", "dev-running", Phase.DEV_RUNNING,
                    lock_timeout=5.0,
                )
                observed.append(True)
            finally:
                sibling_done.set()

        with unified_state_lock(self.root):
            t = threading.Thread(target=_sibling)
            t.start()
            # Sibling should NOT complete while we hold the lock.
            sibling_done.wait(timeout=0.5)
            self.assertFalse(sibling_done.is_set(), "sibling completed under held lock")
        # After release, sibling completes.
        t.join(timeout=5.0)
        self.assertTrue(observed, "sibling never completed")


class LegacyPathLwwTests(_Base):
    """#14 — legacy sprint-status path + same-volume guard."""

    def test_legacy_path_same_volume_lww_resolves(self) -> None:
        # Sprint-status + phase store share the same volume by default in
        # /tmp on Linux CI. Force a conflict and confirm LWW fires.
        write_phase(self.root, "1.1", Phase.DONE)
        base = 1_700_000_000_000_000_000
        os.utime(Path(sprint_status_file(self.root)), ns=(base, base))
        os.utime(phase_store_path(self.root), ns=(base + 1, base + 1))
        result = read_unified_state(self.root, "1.1")
        # Phase newer → wins.
        self.assertEqual(result, ("done", "done", False))


class MtimeTieTerminalWinsTests(_Base):
    """#15 — mtime tie → terminal phase wins."""

    def test_mtime_tie_terminal_phase_wins(self) -> None:
        write_phase(self.root, "1.1", Phase.DONE)
        sprint_path = Path(sprint_status_file(self.root))
        phase_path = phase_store_path(self.root)
        base = 1_700_000_000_000_000_000
        os.utime(sprint_path, ns=(base, base))
        os.utime(phase_path, ns=(base, base))
        # Verify the tie really exists on this filesystem — if it doesn't,
        # the test cannot exercise the tie-break path.
        if sprint_path.stat().st_mtime_ns != phase_path.stat().st_mtime_ns:
            self.fail(
                "could not force mtime tie on this filesystem; "
                "tie-break test cannot run"
            )
        # Conflict: sprint "in-progress" (non-terminal) vs phase DONE (terminal).
        # Tie-break: terminal phase wins → result is ("done", "done").
        result = read_unified_state(self.root, "1.1")
        self.assertEqual(result, ("done", "done", False))


class ObserveOnlyTests(_Base):
    """#16 — observe_only=True NEVER writes to disk."""

    def test_observe_only_no_disk_writes_on_migration(self) -> None:
        sprint_path = Path(sprint_status_file(self.root))
        before = sprint_path.read_bytes()
        before_hash = hashlib.sha256(before).hexdigest()
        # Phase store empty, sprint row "in-progress" → derived phase
        # would be Phase.DEV_RUNNING. observe_only=True must NOT migrate.
        status, phase_value, needs_repair = read_unified_state(
            self.root, "1.1", observe_only=True
        )
        self.assertEqual(status, "in-progress")
        derived = phase_for_sprint_status("in-progress")
        self.assertIsNotNone(derived)
        self.assertEqual(phase_value, derived.value)
        self.assertTrue(needs_repair)
        # Phase store still empty.
        self.assertEqual(read_phase_store(self.root), {})
        # Sprint-status bytes byte-identical.
        self.assertEqual(sprint_path.read_bytes(), before)
        self.assertEqual(
            hashlib.sha256(sprint_path.read_bytes()).hexdigest(), before_hash
        )

    def test_observe_only_unknown_status_returns_pending(self) -> None:
        body = textwrap.dedent(
            """\
            development_status:
              1-1-host-feasibility-probe: bogus-status
            """
        )
        _materialise(self.root, body)
        status, phase_value, needs_repair = read_unified_state(
            self.root, "1.1", observe_only=True
        )
        self.assertEqual(status, "bogus-status")
        self.assertEqual(phase_value, "pending")
        self.assertTrue(needs_repair)


class SlugReconciliationTests(_Base):
    """#17 — slug-keyed phase entries reconciled to canonical id on write."""

    def test_slug_keyed_phase_entry_reconciled_on_write(self) -> None:
        # Seed via M48's write_phase under the slug key.
        from story_automator.core.integration.sprint_phase_map import write_phase as m48_write_phase  # noqa: F401

        m48_write_phase(self.root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)
        # Now write via G7 under the canonical "1.1" — should DELETE slug
        # entry and persist under "1.1".
        write_unified_state(self.root, "1.1", "in-progress", Phase.DEV_RUNNING)
        store = read_phase_store(self.root)
        self.assertEqual(store, {"1.1": Phase.DEV_RUNNING})


class ReadRepairRaceTests(_Base):
    """#17a — read-repair self-cancellation guard (gap D-R-09)."""

    def test_read_repair_self_cancellation_guard(self) -> None:
        # Conflicted fixture: phase=DONE, sprint=in-progress, phase mtime newer.
        write_phase(self.root, "1.1", Phase.DONE)
        base = 1_700_000_000_000_000_000
        os.utime(Path(sprint_status_file(self.root)), ns=(base, base))
        os.utime(phase_store_path(self.root), ns=(base + 1_000_000, base + 1_000_000))

        results: List[tuple] = []
        errors: List[Exception] = []

        def _reader() -> None:
            try:
                results.append(read_unified_state(self.root, "1.1"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_reader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        self.assertEqual(errors, [], f"errors: {errors}")
        # Both reads must return a coherent pair (one of them may have
        # observed the post-repair state).
        for status, phase_value, needs_repair in results:
            self.assertTrue(is_consistent(status, phase_value))
        # Final on-disk state must be internally consistent.
        final_sprint = sprint_status_get(self.root, "1.1").status
        final_phase = read_phase_store(self.root).get("1.1")
        self.assertIsNotNone(final_phase)
        self.assertTrue(is_consistent(final_sprint, final_phase))


class CommentPreservationTests(_Base):
    """D13/D22 — sprint-status writer preserves comments + indent."""

    def test_writer_preserves_comments_and_indent(self) -> None:
        body = "development_status:\n  1-1-foo: in-progress  # owner=alice\n  2-2-bar: in-progress\n"
        _materialise(self.root, body)
        write_unified_state(self.root, "1-1-foo", "done", Phase.DONE)
        after = Path(sprint_status_file(self.root)).read_text(encoding="utf-8")
        # Comment preserved on the target row.
        self.assertIn("# owner=alice", after)
        # Status mutated.
        self.assertIn("1-1-foo: done", after)
        # Untouched row preserved byte-exact.
        self.assertIn("  2-2-bar: in-progress\n", after)


if __name__ == "__main__":
    unittest.main()
