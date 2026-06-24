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

Disk-persistence helpers (``get_lineage_root_dir``, ``lineage_index_path``,
``get_lineage_lock``, ``persist_lineage_entry``, ``load_lineage_entry``,
``load_lineage_chain``, ``load_lineage_root`` plus the private
``_entry_disk_path`` / ``_read_index`` / ``_write_index`` /
``_index_sort_key`` helpers) live in the sibling
:mod:`lineage_persistence` module; this module re-exports them so
existing callers keep working while the file stays under the CLAUDE.md
500-LOC soft limit.

Stdlib only plus filelock; soft-limit-compliant.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

# Re-exports from the persistence sibling — see module docstring. The
# ``noqa: F401`` markers acknowledge that ruff sees these as "unused"
# locally; they are deliberately re-exported so existing callers
# (``commands.lineage_cmd``, ``system_gate``, the test suite,
# ``mock.patch`` strings against ``lineage_ledger.load_lineage_root``)
# keep their import path intact while the definitions live next door.
from story_automator.core.innovation.lineage_persistence import (  # noqa: F401
    _LINEAGE_LOCK_TIMEOUT_S,
    _entry_disk_path,
    _index_sort_key,
    _read_index,
    _write_index,
    get_lineage_lock,
    get_lineage_root_dir,
    lineage_index_path,
    load_lineage_chain,
    load_lineage_entry,
    load_lineage_root,
    persist_lineage_entry,
)

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


def _validate_genre_and_slug(genre: str, slug: str) -> None:
    """Enforce the closed genre vocabulary and slug whitelist.

    Shared by :func:`make_lineage_entry` (write-side trust boundary) AND
    :func:`persist_lineage_entry` (re-validation guard against forged
    entries constructed via ``dataclasses.replace`` on the frozen
    :class:`LineageEntry`). Both code paths must enforce the same closed
    vocabulary so the documented on-disk shape contract
    (``_bmad/lineage/<genre>/<slug>.json``) cannot be lexically escaped
    via path-traversal slugs (``..`` segments, ``/`` / ``\\`` separators,
    NUL, leading/trailing whitespace). Single-operator threat model
    bounds the security impact, but the doc contract would otherwise be
    silently violated and the index would advertise non-portable
    ``..``-laden ``path`` fields.
    """
    if genre not in _GENRES_SET:
        raise LineageError(
            f"unknown lineage genre {genre!r}; must be one of "
            f"{LINEAGE_GENRES}"
        )
    if not isinstance(slug, str) or not slug:
        raise LineageError("slug must be a non-empty string")
    if not _SLUG_RE.match(slug) or ".." in slug:
        raise LineageError(
            f"slug {slug!r} must match {_SLUG_RE.pattern!r} and contain no "
            f"'..' segments (no path separators, NUL bytes, or whitespace)"
        )


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
    _validate_genre_and_slug(genre, slug)
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


# Disk persistence (C2 follow-up) lives in :mod:`lineage_persistence`;
# the imports at the top of this module re-export every public symbol
# (and the private ``_read_index`` / ``_write_index`` / ``_index_sort_key``
# helpers consumed by tests and ``commands.lineage_cmd``) so existing
# call sites keep working while this module stays under the CLAUDE.md
# 500-LOC soft limit. ``mock.patch`` strings targeting internal
# ``write_atomic_text`` / ``_write_index`` references inside
# :func:`persist_lineage_entry` must target the persistence-module path
# (``lineage_persistence.<name>``), not this module — the moved function
# resolves those names against its own module's namespace.
