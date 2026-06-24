"""K-2: evidence-bundle memoization with explicit invalidation.

``load_evidence_bundle`` scans a gate's evidence directory and re-parses
every JSON record on each call. The verdict engine and Merkle-root export
both hit it, so a single ``run_production_gate`` can pay that cost twice
or more for the same ``(project_root, gate_id)`` pair. This module wraps
``load_evidence_bundle`` with an in-process cache keyed by
``(str(project_root), gate_id)``.

Correctness boundary:

* ``persist_evidence_record`` (in :mod:`evidence_io`) calls
  :func:`invalidate_evidence_cache` before returning. That is the single
  source of cache invalidation — there is no TTL, no size cap, no
  background refresh. A persist is the only event that can mutate a
  bundle from this process; persists from other processes are out of
  scope (each process has its own cache).
* Reads return a deep-copied ``list[dict]`` so a caller that mutates the
  bundle (e.g. appends to it, edits a record in place) cannot poison
  subsequent cache hits.

This module is intentionally a sibling of :mod:`evidence_io` so that
``evidence_io.py`` stays under its current LOC and the cache lifecycle
is isolated for testing.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any


_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
_STATS: dict[str, int] = {"hits": 0, "misses": 0, "invalidations": 0}
# Per-key generation counter: incremented on every invalidation event so
# a cache-miss loader that releases the lock to read disk can detect
# whether a concurrent ``persist_evidence_record`` invalidated the key
# between its lock-drop and its lock re-acquire. Stored alongside the
# bundle in ``_CACHE`` would be more compact, but a sidecar dict keeps
# the on-cache-hit path unchanged and makes the generation visible even
# when the key has been popped (the post-invalidate counter persists).
_GEN: dict[tuple[str, str], int] = {}
_LOCK = threading.Lock()


def _key(project_root: str | Path, gate_id: str) -> tuple[str, str]:
    """Normalize cache keys so equivalent path forms collide.

    ``str(Path(x))`` alone collapses trailing slashes and ``/./`` segments
    but does NOT canonicalize relative-vs-absolute paths or follow
    symlinks. Without ``.resolve()``, the same physical project directory
    accessed via two surface forms (e.g. relative ``'project'`` vs
    absolute ``'/abs/project'``, or a symlink vs its target) hashes to
    DISTINCT cache keys. A persist via one form would then fail to
    invalidate a hit cached under the other form, so subsequent readers
    would be served stale bundles until another persist via the matching
    form fires. ``Path.resolve(strict=False)`` tolerates not-yet-created
    directories (the persist may precede the on-disk dir) while still
    collapsing surface-form divergence.
    """
    return (str(Path(project_root).resolve(strict=False)), gate_id)


def cached_load_evidence_bundle(
    project_root: str | Path,
    gate_id: str,
) -> list[dict[str, Any]]:
    """Cache-aware wrapper around :func:`evidence_io.load_evidence_bundle`.

    Returns a deep copy of the cached bundle so callers cannot poison the
    cache by mutating the returned list or its records.

    On a cache miss, delegates to ``load_evidence_bundle`` (which performs
    its own ``_validate_gate_id`` + per-record schema validation). The
    cached value is the canonical list returned by that function.
    """
    # Imported lazily to avoid a circular import: ``evidence_io`` calls
    # back into this module from ``persist_evidence_record`` for the
    # invalidation hook.
    from .evidence_io import load_evidence_bundle

    key = _key(project_root, gate_id)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _STATS["hits"] += 1
            return copy.deepcopy(cached)
        # Bump the miss counter NOW — under the lock that already saw
        # the absent key — so observability reflects every disk-attempt
        # regardless of whether ``load_evidence_bundle`` returns or
        # raises (e.g. ``GateSchemaError`` from corrupted JSON, OSError
        # from a disk failure). Bumping AFTER the load would make
        # error-path misses invisible to ``evidence_cache_stats()`` and
        # mask repeated-failure churn under load.
        _STATS["misses"] += 1
        # Snapshot the per-key generation BEFORE we release the lock.
        # If invalidate_evidence_cache fires between here and the
        # post-load re-acquire below, the generation will have advanced
        # and we must NOT trust our load (the disk snapshot it captured
        # via sorted(glob) may pre-date the concurrent persist's write).
        gen_at_entry = _GEN.get(key, 0)
    # Cache miss: load OUTSIDE the lock so a slow disk read does not
    # block concurrent readers of unrelated gate_ids. Two concurrent
    # misses on the same key may both call ``load_evidence_bundle`` —
    # the result is deterministic and idempotent, so the worst-case
    # cost is a duplicated read, never a corrupted cache.
    bundle = load_evidence_bundle(project_root, gate_id)
    with _LOCK:
        current_gen = _GEN.get(key, 0)
        if current_gen != gen_at_entry:
            # A concurrent persist_evidence_record invalidated this key
            # mid-load. Our bundle may be a pre-persist snapshot; storing
            # it would let stale data win the cache until the next
            # persist. Skip the store and return the freshly-loaded
            # value to the caller (still correct for THIS call, just
            # uncached for the next reader who will reload from disk).
            return copy.deepcopy(bundle)
        # Last-writer-wins on the rare double-miss path. The bundle is
        # by construction a sorted, validated list of records for the
        # same (project_root, gate_id) — two concurrent loaders that
        # observe the same generation read identical disk snapshots and
        # therefore produce equal values.
        _CACHE[key] = bundle
        return copy.deepcopy(bundle)


def invalidate_evidence_cache(
    project_root: str | Path,
    gate_id: str,
) -> None:
    """Drop the cached bundle for a single ``(project_root, gate_id)`` pair.

    Called from :func:`evidence_io.persist_evidence_record` after every
    successful write so the next read sees the new record. Idempotent —
    invalidating a key that was never cached is a no-op and still bumps
    the ``invalidations`` counter (observability over correctness here).

    Also advances the per-key generation counter so a concurrent
    cache-miss loader that released the lock to read disk before this
    invalidation fires will detect the change on re-acquire and refuse
    to store its (possibly stale) snapshot.
    """
    key = _key(project_root, gate_id)
    with _LOCK:
        _CACHE.pop(key, None)
        _GEN[key] = _GEN.get(key, 0) + 1
        _STATS["invalidations"] += 1


def invalidate_all_evidence_cache() -> None:
    """Drop every cached bundle. Intended for test isolation.

    Production code paths should prefer :func:`invalidate_evidence_cache`
    so unrelated gates retain their cached bundles. Does NOT bump the
    ``invalidations`` counter — bulk drops are tracked implicitly by the
    absence of subsequent hits.

    BUMPS every existing per-key generation counter by 1 instead of
    clearing ``_GEN``. This preserves the "gen-advance ⇒ refuse to
    cache" invariant from :func:`invalidate_evidence_cache` even when
    an in-flight miss-loader interleaves with a bulk-drop. Clearing
    ``_GEN`` outright would let a loader that snapshotted
    ``gen_at_entry == N`` after some earlier ``invalidate_evidence_cache``
    fire and then completed its disk read just before this bulk-drop
    silently observe ``current_gen == 0`` on re-acquire and store a
    pre-persist snapshot — see ``test_invalidate_all_does_not_unmask_stale_load``.
    Keys NEVER seen by ``_GEN`` are still safe: a cold-cache loader
    that observed ``gen_at_entry == 0`` for a never-tracked key cannot
    have raced with a real persist that bumped ``_GEN[key]``, because a
    real persist would have created the ``_GEN[key]`` entry that this
    bump-pass then advances.

    Also resets the ``_STATS`` hit/miss/invalidations counters to zero so
    that consecutive test methods see a fresh observability baseline.
    Without this reset, a test method querying
    :func:`evidence_cache_stats` after ``setUp`` would observe historical
    totals carried over from earlier methods, forcing every test to use
    delta-baseline assertions even when the cache is logically empty.
    """
    with _LOCK:
        _CACHE.clear()
        # Bump rather than clear: any prior in-flight miss-loader that
        # snapshotted a per-key generation will now see current_gen >
        # gen_at_entry and refuse to store its (potentially stale)
        # bundle. Clearing _GEN would erase that signal.
        for k in list(_GEN.keys()):
            _GEN[k] += 1
        _STATS["hits"] = 0
        _STATS["misses"] = 0
        _STATS["invalidations"] = 0


def evidence_cache_stats() -> dict[str, int]:
    """Return a snapshot of hit/miss/invalidation counters.

    The returned dict is a copy — mutating it does not affect the
    in-process counters.
    """
    with _LOCK:
        return dict(_STATS)
