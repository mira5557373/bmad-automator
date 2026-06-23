"""K-2: tests for the evidence-bundle memoization cache.

Validates that ``cached_load_evidence_bundle`` returns identical content
to ``load_evidence_bundle`` on miss, hits on subsequent reads of the same
(project_root, gate_id) pair, and is correctly invalidated when a new
record is persisted.
"""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
