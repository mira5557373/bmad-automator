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
_LOCK = threading.Lock()


def _key(project_root: str | Path, gate_id: str) -> tuple[str, str]:
    """Normalize cache keys so ``Path`` and ``str`` inputs collide."""
    return (str(Path(project_root)), gate_id)


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
    # Cache miss: load OUTSIDE the lock so a slow disk read does not
    # block concurrent readers of unrelated gate_ids. Two concurrent
    # misses on the same key may both call ``load_evidence_bundle`` —
    # the result is deterministic and idempotent, so the worst-case
    # cost is a duplicated read, never a corrupted cache.
    bundle = load_evidence_bundle(project_root, gate_id)
    with _LOCK:
        # Last-writer-wins on the rare double-miss path. The bundle is
        # by construction a sorted, validated list of records for the
        # same (project_root, gate_id) — any concurrent loader produces
        # an equal value.
        _CACHE[key] = bundle
        _STATS["misses"] += 1
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
    """
    key = _key(project_root, gate_id)
    with _LOCK:
        _CACHE.pop(key, None)
        _STATS["invalidations"] += 1


def invalidate_all_evidence_cache() -> None:
    """Drop every cached bundle. Intended for test isolation.

    Production code paths should prefer :func:`invalidate_evidence_cache`
    so unrelated gates retain their cached bundles. Does NOT bump the
    per-key invalidation counter — bulk drops are tracked implicitly by
    the absence of subsequent hits.
    """
    with _LOCK:
        _CACHE.clear()


def evidence_cache_stats() -> dict[str, int]:
    """Return a snapshot of hit/miss/invalidation counters.

    The returned dict is a copy — mutating it does not affect the
    in-process counters.
    """
    with _LOCK:
        return dict(_STATS)
