"""C2 MVP — cross-genre artifact lineage ledger tests.

Mirrors the determinism + canonical-JSON discipline of M54
(``core/innovation/ledger.py``) but operates over *artifact* entries that
cross genre boundaries (brainstorm -> ... -> gate) rather than NFR
evidence records inside a single gate run.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from story_automator.core.innovation.lineage_ledger import (
    LINEAGE_GENRES,
    LineageChain,
    LineageEntry,
    LineageError,
    build_lineage_chain,
    compute_lineage_root,
    find_orphans,
    make_lineage_entry,
    verify_lineage,
)


def _h(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry(
    genre: str,
    slug: str,
    parent_root: str = "",
    body: str = "x",
    ts: str = "2026-06-22T00:00:00Z",
) -> LineageEntry:
    return make_lineage_entry(
        genre=genre,
        slug=slug,
        payload_hash=_h(body),
        parent_root=parent_root,
        timestamp_iso=ts,
    )


def _full_chain() -> list[LineageEntry]:
    """Build an 8-entry brainstorm -> gate chain, parents linked correctly."""
    entries: list[LineageEntry] = []
    parent_root = ""
    for idx, genre in enumerate(LINEAGE_GENRES):
        ent = _entry(genre, f"s{idx}", parent_root=parent_root, body=f"b{idx}")
        entries.append(ent)
        parent_root = compute_lineage_root(entries)
    return entries


class LineageGenreVocabularyTests(unittest.TestCase):
    def test_lineage_genres_closed_set(self) -> None:
        # Exactly the 8 documented genres, in canonical order.
        self.assertEqual(
            LINEAGE_GENRES,
            (
                "brainstorm",
                "braindump",
                "brief",
                "BRD",
                "PRD",
                "kernel",
                "story",
                "gate",
            ),
        )

    def test_make_entry_rejects_unknown_genre(self) -> None:
        with self.assertRaises(LineageError):
            make_lineage_entry(
                genre="manifesto",
                slug="x",
                payload_hash=_h("body"),
                parent_root="",
                timestamp_iso="2026-06-22T00:00:00Z",
            )


class LineageRootDeterminismTests(unittest.TestCase):
    def test_compute_root_is_deterministic(self) -> None:
        a = _entry("brainstorm", "s0", body="payload-a")
        b = _entry("braindump", "s1", parent_root="dead", body="payload-b")
        r1 = compute_lineage_root([a, b])
        r2 = compute_lineage_root([a, b])
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 64)

    def test_compute_root_changes_with_reordering(self) -> None:
        a = _entry("brainstorm", "s0", body="payload-a")
        b = _entry("braindump", "s1", parent_root="dead", body="payload-b")
        r1 = compute_lineage_root([a, b])
        r2 = compute_lineage_root([b, a])
        self.assertNotEqual(r1, r2)

    def test_canonical_json_alpha_key_order(self) -> None:
        # Same logical entry serialised twice must produce byte-identical
        # canonical JSON, regardless of field order at construction time.
        e1 = make_lineage_entry(
            genre="brainstorm",
            slug="s",
            payload_hash=_h("p"),
            parent_root="",
            timestamp_iso="2026-06-22T00:00:00Z",
        )
        e2 = make_lineage_entry(
            timestamp_iso="2026-06-22T00:00:00Z",
            parent_root="",
            payload_hash=_h("p"),
            slug="s",
            genre="brainstorm",
        )
        # Hashing both via compute_lineage_root yields equal roots.
        self.assertEqual(compute_lineage_root([e1]), compute_lineage_root([e2]))

        # And the canonical-JSON dict the module uses internally for hashing
        # has alphabetically sorted keys.
        from story_automator.core.innovation.lineage_ledger import (
            _entry_to_dict,
        )

        rendered = json.dumps(
            _entry_to_dict(e1), sort_keys=True, separators=(",", ":")
        )
        # Keys should appear in alphabetical order in the serialized form.
        keys_in_order = [
            "genre",
            "parent_root",
            "payload_hash",
            "slug",
            "timestamp_iso",
        ]
        # Each key occurs exactly once and in alphabetical order.
        positions = [rendered.index(f'"{k}":') for k in keys_in_order]
        self.assertEqual(positions, sorted(positions))


class LineageChainIntegrityTests(unittest.TestCase):
    def test_root_entry_has_empty_parent_root(self) -> None:
        root = _entry("brainstorm", "s0")
        self.assertEqual(root.parent_root, "")

    def test_build_chain_validates_parent_ref_integrity(self) -> None:
        entries = _full_chain()
        chain = build_lineage_chain(entries)
        self.assertIsInstance(chain, LineageChain)
        self.assertEqual(chain.merkle_root, compute_lineage_root(entries))
        self.assertEqual(chain.entries, tuple(entries))

    def test_build_chain_rejects_broken_parent_ref(self) -> None:
        # Tamper: second entry claims an unrelated parent_root.
        entries = _full_chain()
        bad_second = make_lineage_entry(
            genre=entries[1].genre,
            slug=entries[1].slug,
            payload_hash=entries[1].payload_hash,
            parent_root="f" * 64,  # wrong
            timestamp_iso=entries[1].timestamp_iso,
        )
        broken = [entries[0], bad_second, *entries[2:]]
        with self.assertRaises(LineageError):
            build_lineage_chain(broken)

    def test_build_chain_rejects_first_entry_with_nonempty_parent(
        self,
    ) -> None:
        bad_root = _entry("brainstorm", "s0", parent_root="ab" * 32)
        with self.assertRaises(LineageError):
            build_lineage_chain([bad_root])

    def test_build_chain_rejects_empty(self) -> None:
        with self.assertRaises(LineageError):
            build_lineage_chain([])


class VerifyLineageTests(unittest.TestCase):
    def test_verify_lineage_happy_path(self) -> None:
        chain = build_lineage_chain(_full_chain())
        self.assertTrue(verify_lineage(chain))

    def test_verify_lineage_detects_tampering(self) -> None:
        entries = _full_chain()
        chain = build_lineage_chain(entries)

        # Tamper: replace the payload_hash on entry #3 but keep the
        # advertised merkle_root from the *honest* chain.
        tampered_entries = list(chain.entries)
        original = tampered_entries[3]
        tampered_entries[3] = LineageEntry(
            genre=original.genre,
            slug=original.slug,
            payload_hash=_h("evil"),
            parent_root=original.parent_root,
            timestamp_iso=original.timestamp_iso,
        )
        forged = LineageChain(
            entries=tuple(tampered_entries),
            merkle_root=chain.merkle_root,
        )
        self.assertFalse(verify_lineage(forged))

    def test_verify_lineage_expected_genres_match(self) -> None:
        chain = build_lineage_chain(_full_chain())
        self.assertTrue(verify_lineage(chain, expected_genres=list(LINEAGE_GENRES)))

    def test_verify_lineage_expected_genres_mismatch(self) -> None:
        chain = build_lineage_chain(_full_chain())
        # Reverse order is not what the chain advertises.
        self.assertFalse(
            verify_lineage(chain, expected_genres=list(reversed(LINEAGE_GENRES)))
        )


class FindOrphansTests(unittest.TestCase):
    def test_find_orphans_returns_unreferenced_entries(self) -> None:
        a = _entry("brainstorm", "s0")
        root_after_a = compute_lineage_root([a])
        b = _entry("braindump", "s1", parent_root=root_after_a, body="bb")
        # c claims a parent that does NOT belong to any entry in the set.
        c = _entry(
            "brief",
            "s2",
            parent_root="9" * 64,
            body="cc",
        )
        orphans = find_orphans([a, b, c])
        self.assertEqual(orphans, [c])

    def test_find_orphans_empty_when_chain_clean(self) -> None:
        entries = _full_chain()
        self.assertEqual(find_orphans(entries), [])


class FullEightGenreRoundTripTests(unittest.TestCase):
    def test_full_8_genre_chain_round_trip(self) -> None:
        entries = _full_chain()
        chain = build_lineage_chain(entries)
        self.assertEqual(len(chain.entries), 8)
        self.assertEqual(
            [e.genre for e in chain.entries], list(LINEAGE_GENRES)
        )
        self.assertTrue(verify_lineage(chain))
        # Root is stable across recomputation.
        self.assertEqual(
            chain.merkle_root, compute_lineage_root(list(chain.entries))
        )


if __name__ == "__main__":
    unittest.main()
