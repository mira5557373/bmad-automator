"""K-2: tests for the evidence-bundle memoization cache.

Validates that ``cached_load_evidence_bundle`` returns identical content
to ``load_evidence_bundle`` on miss, hits on subsequent reads of the same
(project_root, gate_id) pair, and is correctly invalidated when a new
record is persisted.
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from story_automator.core.evidence_cache import (
    cached_load_evidence_bundle,
    evidence_cache_stats,
    invalidate_all_evidence_cache,
    invalidate_evidence_cache,
)
from story_automator.core.evidence_io import (
    load_evidence_bundle,
    persist_evidence_record,
)
from story_automator.core.gate_schema import make_evidence_record


def _seed_record(
    project_root: Path,
    gate_id: str,
    *,
    category: str = "correctness",
    collector: str = "ruff",
    tool: str = "ruff",
    status: str = "ok",
) -> None:
    """Persist a minimal evidence record for fixture setup."""
    record = make_evidence_record(
        category=category,
        collector=collector,
        tool=tool,
        status=status,
    )
    persist_evidence_record(project_root, gate_id, record)


class EvidenceCacheTests(unittest.TestCase):
    """K-2: per-(project_root, gate_id) bundle memoization."""

    def setUp(self) -> None:
        invalidate_all_evidence_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        invalidate_all_evidence_cache()

    def test_first_load_is_miss_second_is_hit(self) -> None:
        _seed_record(self.root, "g1")
        before = evidence_cache_stats()
        first = cached_load_evidence_bundle(self.root, "g1")
        mid = evidence_cache_stats()
        second = cached_load_evidence_bundle(self.root, "g1")
        after = evidence_cache_stats()
        self.assertEqual(first, second)
        self.assertEqual(mid["misses"], before["misses"] + 1)
        self.assertEqual(after["hits"], mid["hits"] + 1)
        # The cached bundle must match a direct read of disk.
        self.assertEqual(first, load_evidence_bundle(self.root, "g1"))

    def test_persist_invalidates_cache_for_same_gate_id(self) -> None:
        _seed_record(self.root, "g1", tool="ruff")
        first = cached_load_evidence_bundle(self.root, "g1")
        self.assertEqual(len(first), 1)
        # New persist must invalidate the cache so the next load sees it.
        _seed_record(self.root, "g1", tool="mypy", collector="mypy")
        second = cached_load_evidence_bundle(self.root, "g1")
        self.assertEqual(len(second), 2)

    def test_persist_does_not_invalidate_other_gate_ids(self) -> None:
        _seed_record(self.root, "g1")
        _seed_record(self.root, "g2")
        # Warm both caches.
        cached_load_evidence_bundle(self.root, "g1")
        cached_load_evidence_bundle(self.root, "g2")
        before = evidence_cache_stats()
        # Persist a NEW record for g1 — g2's cache must remain hot.
        _seed_record(self.root, "g1", tool="mypy", collector="mypy")
        cached_load_evidence_bundle(self.root, "g2")  # expect HIT
        after = evidence_cache_stats()
        self.assertEqual(after["hits"], before["hits"] + 1)
        # g1 should be a miss next time.
        before_g1 = evidence_cache_stats()
        cached_load_evidence_bundle(self.root, "g1")
        after_g1 = evidence_cache_stats()
        self.assertEqual(after_g1["misses"], before_g1["misses"] + 1)

    def test_multi_gate_isolation(self) -> None:
        _seed_record(self.root, "g1", tool="ruff")
        _seed_record(self.root, "g2", tool="mypy", collector="mypy")
        bundle_a = cached_load_evidence_bundle(self.root, "g1")
        bundle_b = cached_load_evidence_bundle(self.root, "g2")
        self.assertEqual(len(bundle_a), 1)
        self.assertEqual(len(bundle_b), 1)
        self.assertEqual(bundle_a[0]["tool"], "ruff")
        self.assertEqual(bundle_b[0]["tool"], "mypy")

    def test_thread_safety(self) -> None:
        _seed_record(self.root, "g1")
        results: list[list[dict]] = []
        lock = threading.Lock()

        def worker() -> None:
            bundle = cached_load_evidence_bundle(self.root, "g1")
            with lock:
                results.append(bundle)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 16)
        # All concurrent loads must agree on the same content.
        for bundle in results:
            self.assertEqual(bundle, results[0])

    def test_stats_returns_accurate_hits_misses_invalidations(self) -> None:
        invalidate_all_evidence_cache()
        _seed_record(self.root, "g1")
        baseline = evidence_cache_stats()
        cached_load_evidence_bundle(self.root, "g1")  # miss
        cached_load_evidence_bundle(self.root, "g1")  # hit
        cached_load_evidence_bundle(self.root, "g1")  # hit
        invalidate_evidence_cache(self.root, "g1")
        cached_load_evidence_bundle(self.root, "g1")  # miss
        final = evidence_cache_stats()
        self.assertEqual(final["misses"], baseline["misses"] + 2)
        self.assertEqual(final["hits"], baseline["hits"] + 2)
        self.assertEqual(
            final["invalidations"],
            baseline["invalidations"] + 1,
        )

    def test_invalidate_all_clears(self) -> None:
        _seed_record(self.root, "g1")
        _seed_record(self.root, "g2")
        cached_load_evidence_bundle(self.root, "g1")
        cached_load_evidence_bundle(self.root, "g2")
        invalidate_all_evidence_cache()
        before = evidence_cache_stats()
        # Both gate_ids should miss after invalidate_all.
        cached_load_evidence_bundle(self.root, "g1")
        cached_load_evidence_bundle(self.root, "g2")
        after = evidence_cache_stats()
        self.assertEqual(after["misses"], before["misses"] + 2)

    def test_invalidate_all_resets_stats_to_zero(self) -> None:
        """``invalidate_all_evidence_cache`` is a test-isolation API: it
        must zero the hit/miss/invalidations counters so consecutive test
        methods can make absolute (not just delta) assertions against
        :func:`evidence_cache_stats`. Without this, module-global
        ``_STATS`` accumulates indefinitely across the test run and any
        absolute-value assertion becomes ordering-sensitive.
        """
        _seed_record(self.root, "g1")
        # Generate some non-zero counter activity.
        cached_load_evidence_bundle(self.root, "g1")  # miss
        cached_load_evidence_bundle(self.root, "g1")  # hit
        invalidate_evidence_cache(self.root, "g1")
        warm = evidence_cache_stats()
        self.assertGreater(warm["hits"], 0)
        self.assertGreater(warm["misses"], 0)
        self.assertGreater(warm["invalidations"], 0)
        # Bulk-drop should also reset stats — test-isolation contract.
        invalidate_all_evidence_cache()
        cleared = evidence_cache_stats()
        self.assertEqual(cleared["hits"], 0)
        self.assertEqual(cleared["misses"], 0)
        self.assertEqual(cleared["invalidations"], 0)

    def test_cache_returns_copy_or_immutable(self) -> None:
        _seed_record(self.root, "g1")
        first = cached_load_evidence_bundle(self.root, "g1")
        # Try to poison the cache by mutating the returned list.
        first.append({"poisoned": True})
        # Also try to mutate a record dict.
        if len(first) > 1 and isinstance(first[0], dict):
            first[0]["status"] = "POISONED"
        second = cached_load_evidence_bundle(self.root, "g1")
        # Subsequent cached read must NOT reflect the mutation.
        self.assertFalse(any(r.get("poisoned") for r in second))
        # The second read should match a fresh load from disk.
        fresh = load_evidence_bundle(self.root, "g1")
        self.assertEqual(second, fresh)

    def test_persist_during_miss_load_does_not_cache_stale_bundle(self) -> None:
        """Regression: a persist that fires between a cache-miss loader's
        lock-drop and its lock re-acquire must NOT let the stale snapshot
        win the cache.

        Without the per-key generation counter, Thread A's miss-path stores
        a pre-persist bundle (1 record) into the cache even though
        ``persist_evidence_record`` (Thread B) wrote a second record and
        called ``invalidate_evidence_cache`` mid-load. Subsequent readers
        would see only 1 record until the next persist+invalidate.
        """
        from story_automator.core import evidence_cache, evidence_io

        # Seed an initial record so the gate evidence directory exists
        # and contains exactly 1 record. The cache starts empty.
        _seed_record(self.root, "g1", tool="ruff")
        invalidate_all_evidence_cache()

        # Coordinate the race deterministically via two events:
        # a_started_load: A has called load_evidence_bundle and is about
        #                 to return — held inside the wrapper.
        # a_can_finish_load: B has persisted V2 and invalidated; A may
        #                    return its (stale-at-this-point) bundle.
        a_started_load = threading.Event()
        a_can_finish_load = threading.Event()

        real_load = evidence_io.load_evidence_bundle

        def slow_load(project_root: object, gate_id: str) -> list[dict]:
            result = real_load(project_root, gate_id)
            a_started_load.set()
            # Wait for the driver to persist V2 + invalidate before we
            # let A return — this models a real disk/scheduler stall
            # between glob() return and the Python-side cache store.
            a_can_finish_load.wait(timeout=5.0)
            return result

        thread_a_result: list[list[dict]] = []
        thread_a_error: list[BaseException] = []

        def thread_a_worker() -> None:
            try:
                # Patch load_evidence_bundle on the evidence_io module
                # AND on the lazy-imported reference inside the cache
                # module's miss path. The cache imports it lazily inside
                # cached_load_evidence_bundle, so patching the source
                # module is sufficient.
                original = evidence_io.load_evidence_bundle
                evidence_io.load_evidence_bundle = slow_load
                try:
                    bundle = evidence_cache.cached_load_evidence_bundle(
                        self.root, "g1",
                    )
                    thread_a_result.append(bundle)
                finally:
                    evidence_io.load_evidence_bundle = original
            except BaseException as exc:  # noqa: BLE001
                thread_a_error.append(exc)

        thread_a = threading.Thread(target=thread_a_worker)
        thread_a.start()
        try:
            # Wait for Thread A to be parked inside slow_load — at this
            # point A has captured an empty cache, snapshotted gen=0,
            # released the lock, AND completed the disk read for the
            # 1-record state.
            self.assertTrue(
                a_started_load.wait(timeout=5.0),
                "Thread A never reached the slow-load checkpoint",
            )
            # Driver thread B: persist V2 (a new record) — this writes
            # the file AND calls invalidate_evidence_cache, which advances
            # the per-key generation counter from 0 to 1.
            _seed_record(self.root, "g1", tool="mypy", collector="mypy")
            # Disk now has 2 records; cache is empty; generation = 1.
            disk_after_persist = load_evidence_bundle(self.root, "g1")
            self.assertEqual(
                len(disk_after_persist), 2,
                "Driver persist did not actually land on disk",
            )
            # Release Thread A. It will re-acquire the lock and, with
            # the fix, observe the generation advance and refuse to
            # cache its 1-record snapshot.
            a_can_finish_load.set()
        finally:
            thread_a.join(timeout=5.0)
            self.assertFalse(thread_a.is_alive(), "Thread A hung")
        if thread_a_error:
            raise thread_a_error[0]
        self.assertEqual(len(thread_a_result), 1)
        # Thread A's own return value reflects whatever it read off
        # disk — could be 1 or 2 records depending on filesystem
        # snapshot timing; we don't assert on it. The contract we
        # MUST hold is: the NEXT reader sees the current disk state
        # (2 records), not the stale 1-record snapshot.
        next_read = cached_load_evidence_bundle(self.root, "g1")
        self.assertEqual(
            len(next_read), 2,
            f"Cache served stale bundle: got {len(next_read)} records, "
            f"disk has {len(disk_after_persist)}",
        )
        # And it must match a fresh disk read.
        self.assertEqual(next_read, load_evidence_bundle(self.root, "g1"))


    def test_persist_via_relative_path_invalidates_cache_for_absolute_form(
        self,
    ) -> None:
        """Regression: ``_key`` MUST canonicalize so equivalent surface forms
        of the same project_root (relative vs absolute, symlink vs target)
        collide on a single cache entry.

        Without ``.resolve()`` in ``_key``, a persist via the relative
        form would only invalidate the relative-form key, leaving an
        absolute-form cache entry stale after disk has advanced. The
        next absolute-form reader would be served the pre-persist
        bundle until another persist via the matching form fires.

        Reproducer: warm cache with absolute path → persist V2 via
        relative path from a different cwd → re-read with absolute
        path. Without the fix, the read serves a stale 1-record
        bundle; with the fix, both forms key the same canonical entry
        so the relative-form persist invalidates the absolute-form
        cache and the re-read sees the on-disk 2-record state.
        """
        # Seed initial record so the gate evidence directory exists
        # with exactly one record. Use absolute path everywhere first.
        _seed_record(self.root, "g1", tool="ruff")
        invalidate_all_evidence_cache()
        # Warm cache via the absolute form.
        first = cached_load_evidence_bundle(self.root, "g1")
        self.assertEqual(len(first), 1)
        # Persist V2 via the RELATIVE form of the same project_root,
        # from a different cwd. Build a relative path that points at
        # self.root from os.getcwd().
        cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(str(self.root)))
            rel_path = os.path.basename(str(self.root))
            self.assertNotEqual(
                str(Path(rel_path)),
                str(self.root),
                "relative and absolute string forms must differ",
            )
            _seed_record(Path(rel_path), "g1", tool="mypy", collector="mypy")
        finally:
            os.chdir(cwd)
        # Disk now has 2 records.
        disk_after = load_evidence_bundle(self.root, "g1")
        self.assertEqual(len(disk_after), 2)
        # The next absolute-form read MUST observe the new on-disk
        # state. With unfixed ``_key`` the relative-form persist
        # invalidated only the relative key, leaving the absolute
        # cache entry stale at 1 record.
        second = cached_load_evidence_bundle(self.root, "g1")
        self.assertEqual(
            len(second),
            2,
            "Cache served stale bundle after cross-form persist: "
            f"got {len(second)} records, disk has {len(disk_after)}",
        )
        self.assertEqual(second, disk_after)

    def test_symlink_and_target_share_cache_entry(self) -> None:
        """Regression: a symlink to the project_root and its target MUST
        collide on the same cache key. Without ``.resolve()`` in ``_key``,
        the two paths produce distinct str(Path(...)) values and the
        cache holds two divergent entries for the same physical evidence
        directory.
        """
        # Build a symlink that points at self.root inside another tmpdir.
        with tempfile.TemporaryDirectory() as link_parent:
            sym_path = Path(link_parent) / "link-to-root"
            os.symlink(str(self.root), str(sym_path))
            # Seed via the target path. Cache starts clean.
            _seed_record(self.root, "g1", tool="ruff")
            invalidate_all_evidence_cache()
            # Warm via the symlink form.
            via_sym = cached_load_evidence_bundle(sym_path, "g1")
            self.assertEqual(len(via_sym), 1)
            # Persist V2 via the TARGET form — this must invalidate the
            # symlink-form cache because both canonicalize to the same
            # real path under ``.resolve()``.
            _seed_record(self.root, "g1", tool="mypy", collector="mypy")
            disk_after = load_evidence_bundle(self.root, "g1")
            self.assertEqual(len(disk_after), 2)
            # Next read via the symlink form MUST see the new bundle.
            second = cached_load_evidence_bundle(sym_path, "g1")
            self.assertEqual(
                len(second),
                2,
                "Cache served stale bundle via symlink after target persist: "
                f"got {len(second)} records, disk has {len(disk_after)}",
            )
            self.assertEqual(second, disk_after)


if __name__ == "__main__":
    unittest.main()
