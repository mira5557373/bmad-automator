"""C2 MVP — cross-genre artifact lineage ledger (brainstorm -> gate).

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

Hash discipline mirrors M54:
    * Canonical JSON serialisation with ``sort_keys=True`` and the most
      compact separators (``","`` / ``":"``).
    * sha256 over those UTF-8 bytes.
    * Determinism is the entire safety story — entries in input order
      define the root; reordering changes it.

C2 is intentionally a *sibling* of M54, not an extension.  The two
ledgers solve different problems and we don't want either to depend on
the other's schema choices.

Stdlib only; under the 500-LOC soft budget.

Out of scope for this MVP (each its own follow-up milestone):
    * Disk persistence (artifacts stored to ``_bmad/lineage/``).
    * Wiring into the gate file (gate embeds ``lineage_root``).
    * Operator CLI to query the lineage of a specific gate.
    * Operator-facing visualization.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

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
        1. ``chain.merkle_root`` equals ``compute_lineage_root(chain.entries)``
           — detects tampering with any entry (payload_hash, parent_root,
           timestamp, genre, slug).
        2. Each entry's ``parent_root`` matches the running Merkle root of
           the preceding entries (delegated to ``build_lineage_chain``).
        3. If ``expected_genres`` is provided, the genres of ``chain.entries``
           match it position-for-position.

    Any failure returns False (not an exception) so callers can use this
    as a boolean predicate; ``build_lineage_chain`` is the right tool
    when you want a diagnostic exception instead.
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

    "Known roots" are the running Merkle roots of every non-empty prefix
    of ``entries`` (in input order), plus the empty string (which means
    "I am the genesis entry").  Any entry whose ``parent_root`` is not
    in that set is an orphan: its claimed parent does not appear in the
    set we were given, so we cannot prove its provenance from this data
    alone.
    """
    entries_list = list(entries)
    known_roots: set[str] = {""}
    for idx in range(1, len(entries_list) + 1):
        known_roots.add(compute_lineage_root(entries_list[:idx]))

    orphans: list[LineageEntry] = []
    for entry in entries_list:
        if entry.parent_root not in known_roots:
            orphans.append(entry)
    return orphans
