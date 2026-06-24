"""C2 follow-up — cross-genre artifact lineage ledger (disk-persisted).

M54 (``ledger.py``) chains *NFR evidence records* inside a single gate
run.  C2 extends the same hash discipline to *artifacts* that cross
genre boundaries in the BMAD methodology pipeline:

    brainstorm -> braindump -> brief -> BRD -> PRD -> kernel -> story -> gate

Each :class:`LineageEntry` is a record-of-record for one artifact in the
pipeline; ``parent_root`` references the Merkle root of the lineage chain
up to (and including) the parent entry, so the resulting :class:`LineageChain`
constitutes a verifiable provenance trail: anyone holding the chain can
prove "this gate verdict descends from brief X via kernel Y" without
trusting the producer.

Hash discipline mirrors M54: canonical JSON (``sort_keys=True`` + compact
separators), sha256 over UTF-8 bytes, deterministic across machines.

C2 is intentionally a *sibling* of M54, not an extension.

Disk layout (C2 follow-up):
    _bmad/lineage/
        index.json            -- alpha-sorted "<genre>/<slug>" -> meta map
        .lineage.lock         -- filelock sidecar for concurrent persist
        <genre>/<slug>.json   -- one canonical-JSON file per entry

The lineage dir is independent of the K-5 cleanup root under
``_bmad/gate/cleanup/`` — no path collision.

Stdlib only plus filelock; soft-limit-compliant.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from filelock import FileLock

from story_automator.core.atomic_io import write_atomic_text

# Closed vocabulary, in canonical pipeline order.  Position matters: it
# is used by ``verify_lineage(expected_genres=LINEAGE_GENRES)`` to assert
# a full brainstorm -> gate chain.
LINEAGE_GENRES: tuple[str, ...] = (
    "brainstorm",
    "braindump",
    "brief",
    "BRD",
    "PRD",
    "kernel",
    "story",
    "gate",
)

_GENRES_SET = frozenset(LINEAGE_GENRES)

# Slug whitelist: alphanumerics plus ``_ . -``. Forbids path separators
# (``/``, ``\``), ``..`` segments, NUL bytes, and leading/trailing
# whitespace so a slug can never escape ``_bmad/lineage/<genre>/`` via
# the lexical ``_entry_disk_path`` composition. The closed character
# class is friendlier than a denylist (no surprise control characters,
# no Unicode normalisation gotchas) and matches the simple
# ``s0``/``missing-slug``-style identifiers already used in tests + CLI
# round-trip.  This is the C2-follow-up tightening flagged in
# :func:`make_lineage_entry`'s MVP docstring.
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class LineageError(ValueError):
    """Raised for any lineage validation failure (unknown genre, broken
    parent_root chain, tampering detected by ``verify_lineage``)."""


@dataclass(frozen=True)
class LineageEntry:
    """One artifact in the cross-genre lineage chain.

    Fields are deliberately scalar and JSON-friendly so canonical-JSON
    serialisation is byte-deterministic — the entire integrity story
    rests on stable bytes in, stable hash out.
    """

    genre: str
    slug: str
    payload_hash: str
    parent_root: str
    timestamp_iso: str


@dataclass(frozen=True)
class LineageChain:
    """A validated tuple of :class:`LineageEntry` plus their Merkle root.

    The root is computed over ``entries`` in order; reordering is a
    different chain even when the entries are otherwise identical.
    """

    entries: tuple[LineageEntry, ...]
    merkle_root: str


# ---------------------------------------------------------------------------
# Constructors + canonical-JSON serialisation.
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: LineageEntry) -> dict[str, str]:
    """Render ``entry`` as a plain dict suitable for canonical JSON.

    Kept private — callers should not rely on this shape outside the
    module.  All keys are strings, all values are strings, so
    ``json.dumps(..., sort_keys=True)`` is byte-deterministic.
    """
    return {
        "genre": entry.genre,
        "slug": entry.slug,
        "payload_hash": entry.payload_hash,
        "parent_root": entry.parent_root,
        "timestamp_iso": entry.timestamp_iso,
    }


def _canonical_json(obj: object) -> str:
    """Same shape as ``core.gate_schema.canonical_json`` — duplicated so
    this module has no internal call dependency on the gate schema."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_lineage_entry(
    *,
    genre: str,
    slug: str,
    payload_hash: str,
    parent_root: str,
    timestamp_iso: str,
) -> LineageEntry:
    """Construct a :class:`LineageEntry`, validating the genre vocabulary.

    All other fields are accepted as-is (the MVP does not enforce
    hash-length or ISO-8601 syntax — follow-ups can tighten these).
    """
    if genre not in _GENRES_SET:
        raise LineageError(
            f"unknown lineage genre {genre!r}; must be one of "
            f"{LINEAGE_GENRES}"
        )
    if not isinstance(slug, str) or not slug:
        raise LineageError("slug must be a non-empty string")
    # Reject path-traversal characters so a slug can never escape
    # ``_bmad/lineage/<genre>/`` via the lexical ``_entry_disk_path``
    # composition (``..`` segments, ``/`` / ``\`` separators, NUL,
    # leading/trailing whitespace).  Single-operator threat model bounds
    # the security impact, but the documented on-disk shape contract
    # ('one canonical-JSON file per entry under
    # ``_bmad/lineage/<genre>/<slug>.json``') would otherwise be silently
    # violated and the index would advertise non-portable ``..``-laden
    # ``path`` fields.
    if not _SLUG_RE.match(slug) or ".." in slug:
        raise LineageError(
            f"slug {slug!r} must match {_SLUG_RE.pattern!r} and contain no "
            f"'..' segments (no path separators, NUL bytes, or whitespace)"
        )
    if not isinstance(payload_hash, str):
        raise LineageError("payload_hash must be a string")
    if not isinstance(parent_root, str):
        raise LineageError("parent_root must be a string (empty for root)")
    if not isinstance(timestamp_iso, str) or not timestamp_iso:
        raise LineageError("timestamp_iso must be a non-empty string")
    return LineageEntry(
        genre=genre,
        slug=slug,
        payload_hash=payload_hash,
        parent_root=parent_root,
        timestamp_iso=timestamp_iso,
    )


# ---------------------------------------------------------------------------
# Root + chain primitives.
# ---------------------------------------------------------------------------


def compute_lineage_root(entries: Sequence[LineageEntry]) -> str:
    """Return the lineage root (64-hex sha256) over ``entries`` in order.

    Determinism: the root is sha256 of the canonical-JSON encoding of
    the entries list (``[{genre,...}, {genre,...}, ...]``) with all
    keys sorted alphabetically and no whitespace.  Same list, same
    order, same root — every time.  Reordering changes the root, which
    is exactly what we want for a lineage proof.
    """
    if not entries:
        raise LineageError("cannot compute lineage root over empty entries")
    rendered = [_entry_to_dict(e) for e in entries]
    payload = _canonical_json(rendered).encode("utf-8")
    return _sha256_hex(payload)


def build_lineage_chain(entries: Sequence[LineageEntry]) -> LineageChain:
    """Validate parent_root integrity and return a :class:`LineageChain`.

    The first entry must have ``parent_root == ""`` (it is the genesis
    of the chain).  Every subsequent entry must carry a ``parent_root``
    equal to ``compute_lineage_root(entries[:i])`` — i.e. the Merkle
    root of the chain up to (but not including) itself.  Any mismatch
    raises :class:`LineageError`.
    """
    if not entries:
        raise LineageError("cannot build lineage chain with no entries")

    entries_list = list(entries)
    if entries_list[0].parent_root != "":
        raise LineageError(
            "first lineage entry must have empty parent_root "
            f"(got {entries_list[0].parent_root!r})"
        )

    for idx in range(1, len(entries_list)):
        prefix = entries_list[:idx]
        expected_parent = compute_lineage_root(prefix)
        if entries_list[idx].parent_root != expected_parent:
            raise LineageError(
                f"lineage entry #{idx} ({entries_list[idx].genre}/"
                f"{entries_list[idx].slug}) has parent_root="
                f"{entries_list[idx].parent_root!r}; expected "
                f"{expected_parent!r} (root of entries[:{idx}])"
            )

    return LineageChain(
        entries=tuple(entries_list),
        merkle_root=compute_lineage_root(entries_list),
    )


def verify_lineage(
    chain: LineageChain,
    expected_genres: list[str] | None = None,
) -> bool:
    """Return True iff ``chain`` is internally consistent.

    Checks:
        1. ``chain`` is a :class:`LineageChain` instance (defensive guard
           against forged values constructed via direct dataclass init).
        2. ``chain.entries`` is non-empty. An empty-entries chain is
           unreachable through any documented constructor
           (:func:`build_lineage_chain` and :func:`load_lineage_chain`
           both raise :class:`LineageError` on empty input), so reaching
           this guard means the value was hand-constructed with malformed
           inputs — return False as a defensive sanity rejection.
        3. ``chain.merkle_root`` equals ``compute_lineage_root(chain.entries)``
           — detects tampering with any entry (payload_hash, parent_root,
           timestamp, genre, slug).
        4. Each entry's ``parent_root`` matches the running Merkle root of
           the preceding entries (delegated to ``build_lineage_chain``).
        5. If ``expected_genres`` is provided, the genres of ``chain.entries``
           match it position-for-position.

    Any failure returns False (not an exception) so callers can use this
    as a boolean predicate; ``build_lineage_chain`` is the right tool
    when you want a diagnostic exception instead.

    Note on the empty-chain semantic asymmetry with the CLI surface:
    :func:`commands.lineage_cmd.verify_action` emits ``ok:true`` with
    ``merkle_root:""`` when ``_bmad/lineage/`` is empty, mirroring the
    :func:`load_lineage_root` ``""`` sentinel. That CLI path answers
    "is the on-disk store consistent?" (empty disk = trivially yes) and
    short-circuits BEFORE constructing a :class:`LineageChain`. This
    function answers a different question: "is this constructed
    :class:`LineageChain` value internally consistent?" — and since the
    only way to obtain ``LineageChain(entries=(), merkle_root='')`` is
    via direct dataclass instantiation with malformed inputs, rejection
    is the correct defensive behavior. Callers wanting the CLI's
    "trivially intact" interpretation on empty disk state should call
    :func:`load_lineage_root` and treat ``""`` as the empty-chain sentinel.
    """
    if not isinstance(chain, LineageChain):
        return False
    if not chain.entries:
        return False

    recomputed = compute_lineage_root(list(chain.entries))
    if recomputed != chain.merkle_root:
        return False

    try:
        build_lineage_chain(list(chain.entries))
    except LineageError:
        return False

    if expected_genres is not None:
        actual = [e.genre for e in chain.entries]
        if actual != list(expected_genres):
            return False

    return True


# ---------------------------------------------------------------------------
# Orphan detection.
# ---------------------------------------------------------------------------


def find_orphans(entries: Sequence[LineageEntry]) -> list[LineageEntry]:
    """Return entries whose ``parent_root`` does not match a known root.

    Order-independent: the chain order is reconstructed topologically by
    following ``parent_root`` pointers from the genesis entry. This means
    callers can pass entries in any order (alpha-sorted, persist-order,
    arbitrary) and ``find_orphans`` will produce the same result for any
    structurally valid chain. Concretely, the function:

    1. Identifies the genesis (the unique entry with ``parent_root == ""``).
       Multi-genesis corruption flags every extra genesis as an orphan
       (:func:`build_lineage_chain` would refuse such a chain at line 1).
    2. Iteratively extends the chain by finding the entry whose
       ``parent_root`` equals the running Merkle root.
    3. Any entry not reachable by this walk — because its claimed parent
       does not appear in the dataset — is an orphan.

    Topological reconstruction is what makes this robust against the
    lenient loader (``commands/lineage_cmd._load_entries_lenient``), which
    falls back to alphabetical ordering when the disk index has no usable
    ``seq`` field. Under input-order semantics, alpha-sorted entries would
    produce phantom orphans for structurally intact chains.
    """
    entries_list = list(entries)
    if not entries_list:
        return []

    # Phase 1: collect genesis claimants. Only the first parent_root=='' is
    # a legitimate genesis; every subsequent claimant is an orphan.
    genesis: LineageEntry | None = None
    extra_genesis: list[LineageEntry] = []
    non_genesis: list[LineageEntry] = []
    for entry in entries_list:
        if entry.parent_root == "":
            if genesis is None:
                genesis = entry
            else:
                extra_genesis.append(entry)
        else:
            non_genesis.append(entry)

    if genesis is None:
        # No genesis entry at all — every non-genesis entry's parent_root
        # is unreachable.
        return list(non_genesis)

    # Phase 2: topologically walk the chain by following parent_root
    # pointers. Group non-genesis entries by their parent_root so each
    # extension step is O(1) lookup.
    by_parent: dict[str, list[LineageEntry]] = {}
    for entry in non_genesis:
        by_parent.setdefault(entry.parent_root, []).append(entry)

    chain: list[LineageEntry] = [genesis]
    placed: set[int] = {id(genesis)}
    running_root = compute_lineage_root(chain)
    while running_root in by_parent:
        candidates = by_parent[running_root]
        # Multiple entries claiming the same parent_root means the chain
        # forks. The first candidate (input order) is the canonical next
        # link; the rest are fork-orphans whose parent_root points at a
        # real root but whose lineage was never extended into the chain.
        nxt = candidates[0]
        chain.append(nxt)
        placed.add(id(nxt))
        running_root = compute_lineage_root(chain)

    # Phase 3: every non-genesis entry not placed in the chain is an
    # orphan. Preserve input order so the output is deterministic.
    orphans: list[LineageEntry] = []
    for entry in non_genesis:
        if id(entry) not in placed:
            orphans.append(entry)
    orphans.extend(extra_genesis)
    # Sort by original input position so callers receive orphans in the
    # same order they were passed in (matches the prior input-order
    # output contract for the cases that did work).
    position = {id(e): idx for idx, e in enumerate(entries_list)}
    orphans.sort(key=lambda e: position[id(e)])
    return orphans


# ---------------------------------------------------------------------------
# Disk persistence (C2 follow-up).
# ---------------------------------------------------------------------------

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
    project_root: str | Path, entry: LineageEntry,
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
    """
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
) -> LineageEntry:
    """Load a single :class:`LineageEntry` from disk.

    Raises :class:`LineageError` if the entry file is missing or its
    JSON does not match the canonical-JSON shape.
    """
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


def load_lineage_chain(project_root: str | Path) -> LineageChain:
    """Build the on-disk :class:`LineageChain` via ``seq`` order.

    Empty index raises :class:`LineageError` — callers wanting the
    "no chain" sentinel should use :func:`load_lineage_root` instead.

    Symmetric read-path validation: ``make_lineage_entry`` rejects any
    slug containing path separators, ``..`` segments, NUL bytes, or
    leading/trailing whitespace at the write boundary (see lines 158-171).
    The same containment contract holds on the read path: a tampered or
    hand-edited ``index.json`` containing a traversal composite_key
    (e.g. ``"../../escape"``) would otherwise feed a sandbox-escaping
    ``(genre, slug)`` pair to :func:`_entry_disk_path`, silently
    violating the documented ``_bmad/lineage/<genre>/<slug>.json`` shape
    contract. We validate ``genre`` against :data:`_GENRES_SET` and
    ``slug`` against :data:`_SLUG_RE` (plus ``..`` rejection) BEFORE
    composing the on-disk path, mirroring the constructor's whitelist.
    """
    entries_meta = _read_index(project_root)
    if not entries_meta:
        raise LineageError(
            f"no lineage entries under {get_lineage_root_dir(project_root)}"
        )
    entries: list[LineageEntry] = []
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
