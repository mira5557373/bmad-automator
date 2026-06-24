"""C2 follow-up — disk-persistence helpers for the lineage ledger.

This module is split out of ``lineage_ledger.py`` to keep the canonical
chain-primitives module under the CLAUDE.md 500-LOC soft limit. Mirrors
the ``spec_drift_watcher`` / ``spec_drift_persistence`` split pattern
already established in this directory.

``lineage_ledger.py`` re-exports every public symbol defined here so
existing call sites (and ``mock.patch`` strings targeting
``lineage_ledger.load_lineage_root`` etc.) continue to work. Internal
``write_atomic_text`` / ``_write_index`` references inside
``persist_lineage_entry`` resolve against THIS module's namespace, so
crash-safety regression tests patch the symbols at
``lineage_persistence.<name>`` rather than the historical
``lineage_ledger.<name>`` location.

Disk layout (unchanged from the original ``lineage_ledger`` design):
    _bmad/lineage/
        index.json            -- alpha-sorted "<genre>/<slug>" -> meta map
        .lineage.lock         -- filelock sidecar for concurrent persist
        <genre>/<slug>.json   -- one canonical-JSON file per entry

Stdlib only plus filelock; soft-limit-compliant.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock

from story_automator.core.atomic_io import write_atomic_text

if TYPE_CHECKING:
    from story_automator.core.innovation.lineage_ledger import (
        LineageChain,
        LineageEntry,
    )

# 60s lock timeout matches M05 conventions: long enough for a pathological
# NFS contention case, short enough that a wedged peer surfaces as a typed
# failure rather than an indefinite hang.
_LINEAGE_LOCK_TIMEOUT_S: float = 60.0


def get_lineage_root_dir(project_root: str | Path) -> Path:
    """Return ``<project_root>/_bmad/lineage/``, creating it on first call."""
    root = Path(project_root) / "_bmad" / "lineage"
    root.mkdir(parents=True, exist_ok=True)
    return root


def lineage_index_path(project_root: str | Path) -> Path:
    """Return the canonical path to the lineage index JSON."""
    return get_lineage_root_dir(project_root) / "index.json"


def get_lineage_lock(project_root: str | Path) -> FileLock:
    """Return the FileLock guarding the persist + index-rewrite sequence."""
    return FileLock(str(get_lineage_root_dir(project_root) / ".lineage.lock"))


def _entry_disk_path(
    project_root: str | Path, genre: str, slug: str,
) -> Path:
    """``_bmad/lineage/<genre>/<slug>.json`` — sharded by genre dir."""
    return get_lineage_root_dir(project_root) / genre / f"{slug}.json"


def _read_index(project_root: str | Path) -> dict[str, dict[str, str | int]]:
    """Parse index.json. Empty dict on absence; LineageError on corruption.

    The inner-dict value variant is ``str | int`` because the ``seq`` key
    is written as a Python ``int`` (insertion order, see
    :func:`persist_lineage_entry`) while ``path``, ``merkle_root``, and
    ``timestamp_iso`` are strings. Consumers must coerce ``seq`` via
    ``int(...)`` before arithmetic.

    Silent rebuild would mask provenance gaps that the operator must
    consciously acknowledge (audit-chain analog from M04).
    """
    # Local import avoids the circular at module-load time.
    from story_automator.core.innovation.lineage_ledger import LineageError

    idx_path = lineage_index_path(project_root)
    if not idx_path.is_file():
        return {}
    try:
        parsed = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise LineageError(f"corrupt lineage index at {idx_path}: {err}") from err
    if not isinstance(parsed, dict):
        raise LineageError(
            f"corrupt lineage index at {idx_path}: top-level not an object"
        )
    entries = parsed.get("entries", {})
    if not isinstance(entries, dict):
        raise LineageError(
            f"corrupt lineage index at {idx_path}: entries not an object"
        )
    return entries


def _write_index(
    project_root: str | Path, entries: dict[str, dict[str, str | int]],
) -> None:
    """Atomically rewrite index.json with alpha-sorted keys for determinism.

    Logical chain order is preserved via per-entry ``seq``; readers
    reconstruct via ``seq`` sort (see :func:`load_lineage_chain`).
    """
    sorted_entries = {k: entries[k] for k in sorted(entries.keys())}
    rendered = json.dumps(
        {"entries": sorted_entries}, sort_keys=True, separators=(",", ":"),
    )
    write_atomic_text(lineage_index_path(project_root), rendered)


def persist_lineage_entry(
    project_root: str | Path, entry: "LineageEntry",
) -> Path:
    """Atomically persist ``entry`` and update the index. Returns its path.

    Concurrency: write-entry + rewrite-index runs under
    :func:`get_lineage_lock`; parallel persists on distinct (genre, slug)
    both end up in the index; re-persist of the same entry is idempotent.

    Crash safety: entry JSON via :func:`atomic_io.write_atomic_text`. If
    the entry write raises, the index is NOT updated — a partial write
    can never leave the index advertising a missing payload. Symmetrically,
    if the index write raises after the entry write succeeded, the
    just-written entry file is best-effort rolled back so the on-disk
    state matches the (untouched) index — an orphan payload can never
    silently sit outside the index advertising provenance the chain
    cannot prove.

    Re-validates ``entry.genre`` and ``entry.slug`` against the closed
    vocabulary even though :func:`make_lineage_entry` already enforces
    them at construction. :class:`LineageEntry` is a frozen dataclass
    with no ``__post_init__``, so ``dataclasses.replace(good, slug=...)``
    (or direct ``LineageEntry(...)`` construction) routes around every
    constructor guard. Re-validating at the persist boundary keeps
    :func:`_entry_disk_path` from composing a sandbox-escaping path
    before the mkdir + atomic-write fire — symmetric with the read-path
    validation in :func:`load_lineage_chain`.
    """
    # Local imports avoid the circular at module-load time. Chain
    # primitives (validation + canonical-JSON + compute_lineage_root)
    # live in lineage_ledger; persistence is the sibling layer.
    from story_automator.core.innovation.lineage_ledger import (
        _canonical_json,
        _entry_to_dict,
        _validate_genre_and_slug,
        compute_lineage_root,
    )

    _validate_genre_and_slug(entry.genre, entry.slug)
    target_path = _entry_disk_path(project_root, entry.genre, entry.slug)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    rendered = _canonical_json(_entry_to_dict(entry))
    composite_key = f"{entry.genre}/{entry.slug}"

    lock = get_lineage_lock(project_root)
    lock.acquire(timeout=_LINEAGE_LOCK_TIMEOUT_S)
    try:
        # Read index BEFORE entry write so a corrupt index aborts up-front.
        entries = _read_index(project_root)
        # Capture pre-write state so a downstream index-write failure can
        # roll back to the pre-call on-disk shape. For a brand-new entry
        # the rollback is "delete the just-written file"; for an idempotent
        # re-persist of an already-indexed entry the file existed before
        # and is left in place (the index still advertises it).
        entry_pre_existed = composite_key in entries
        # Entry write first; on failure the index stays untouched.
        write_atomic_text(target_path, rendered)
        # Insertion order tracked via ``seq`` so :func:`load_lineage_chain`
        # can reconstruct the chain even though disk keys are alpha-sorted
        # for byte determinism. Re-persist reuses the existing ``seq`` to
        # keep idempotence.
        if composite_key in entries:
            seq = entries[composite_key].get("seq", len(entries))
        else:
            seq = len(entries)
        entries[composite_key] = {
            "path": str(target_path.relative_to(Path(project_root))),
            "merkle_root": compute_lineage_root([entry]),
            "timestamp_iso": entry.timestamp_iso,
            "seq": seq,
        }
        try:
            _write_index(project_root, entries)
        except BaseException:
            # Symmetric crash safety: roll back the orphan entry file so
            # the on-disk state matches the untouched index. Only delete
            # files this call created; an already-indexed re-persist must
            # leave its prior advertised payload behind (the index still
            # references it). Cleanup is best-effort so it cannot mask
            # the original failure.
            if not entry_pre_existed:
                try:
                    os.unlink(str(target_path))
                except FileNotFoundError:
                    pass
                except OSError:
                    # Do not mask the original index-write error.
                    pass
            raise
    finally:
        lock.release()

    return target_path


def load_lineage_entry(
    project_root: str | Path, genre: str, slug: str,
) -> "LineageEntry":
    """Load a single :class:`LineageEntry` from disk.

    Raises :class:`LineageError` if the entry file is missing or its
    JSON does not match the canonical-JSON shape.
    """
    from story_automator.core.innovation.lineage_ledger import (
        LineageError,
        make_lineage_entry,
    )

    target_path = _entry_disk_path(project_root, genre, slug)
    if not target_path.is_file():
        raise LineageError(f"no lineage entry at {target_path} ({genre}/{slug})")
    try:
        parsed = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise LineageError(f"corrupt lineage entry at {target_path}: {err}") from err
    if not isinstance(parsed, dict):
        raise LineageError(f"corrupt lineage entry at {target_path}: not an object")
    try:
        return make_lineage_entry(
            genre=parsed["genre"],
            slug=parsed["slug"],
            payload_hash=parsed["payload_hash"],
            parent_root=parsed["parent_root"],
            timestamp_iso=parsed["timestamp_iso"],
        )
    except KeyError as err:
        raise LineageError(
            f"corrupt lineage entry at {target_path}: missing field {err}"
        ) from err


def _index_sort_key(item: tuple[str, dict[str, str | int]]) -> tuple[int, str]:
    """Sort by ``seq`` (insertion order); alpha composite key as tie-break."""
    composite_key, meta = item
    try:
        seq_value = int(meta.get("seq", -1))
    except (TypeError, ValueError):
        seq_value = -1
    return (seq_value, composite_key)


def load_lineage_chain(project_root: str | Path) -> "LineageChain":
    """Build the on-disk :class:`LineageChain` via ``seq`` order.

    Empty index raises :class:`LineageError` — callers wanting the
    "no chain" sentinel should use :func:`load_lineage_root` instead.

    Symmetric read-path validation: ``make_lineage_entry`` rejects any
    slug containing path separators, ``..`` segments, NUL bytes, or
    leading/trailing whitespace at the write boundary (see
    ``lineage_ledger._validate_genre_and_slug``). The same containment
    contract holds on the read path: a tampered or hand-edited
    ``index.json`` containing a traversal composite_key
    (e.g. ``"../../escape"``) would otherwise feed a sandbox-escaping
    ``(genre, slug)`` pair to :func:`_entry_disk_path`, silently
    violating the documented ``_bmad/lineage/<genre>/<slug>.json`` shape
    contract. We validate ``genre`` against ``_GENRES_SET`` and
    ``slug`` against ``_SLUG_RE`` (plus ``..`` rejection) BEFORE
    composing the on-disk path, mirroring the constructor's whitelist.
    """
    from story_automator.core.innovation.lineage_ledger import (
        _GENRES_SET,
        _SLUG_RE,
        LINEAGE_GENRES,
        LineageError,
        build_lineage_chain,
    )

    entries_meta = _read_index(project_root)
    if not entries_meta:
        raise LineageError(
            f"no lineage entries under {get_lineage_root_dir(project_root)}"
        )
    entries = []
    for composite_key, _meta in sorted(entries_meta.items(), key=_index_sort_key):
        genre, sep, slug = composite_key.partition("/")
        if sep != "/" or not slug:
            raise LineageError(
                f"corrupt lineage index composite_key {composite_key!r}: "
                f"expected '<genre>/<slug>' shape"
            )
        if genre not in _GENRES_SET:
            raise LineageError(
                f"corrupt lineage index composite_key {composite_key!r}: "
                f"genre {genre!r} not in {LINEAGE_GENRES}"
            )
        if not _SLUG_RE.match(slug) or ".." in slug:
            raise LineageError(
                f"corrupt lineage index composite_key {composite_key!r}: "
                f"slug {slug!r} must match {_SLUG_RE.pattern!r} and contain "
                f"no '..' segments (no path separators, NUL bytes, or whitespace)"
            )
        entries.append(load_lineage_entry(project_root, genre, slug))
    return build_lineage_chain(entries)


def load_lineage_root(project_root: str | Path) -> str:
    """Return the disk-derived lineage root, or "" when no chain exists.

    Empty-string sentinel mirrors ``evidence_merkle_root`` — distinguishable
    from any real 64-hex root. Corrupt index re-raises :class:`LineageError`
    (provenance-gap loudness, audit-chain analog from M04).
    """
    if not _read_index(project_root):
        return ""
    return load_lineage_chain(project_root).merkle_root
