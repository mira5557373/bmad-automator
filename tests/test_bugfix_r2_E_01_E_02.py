"""Bug R2 E-01+E-02 — Merkle tree CVE-2012-2459 + internal-node-as-leaf forgery.

Two related Merkle vulnerabilities that share a single fix (RFC 6962 domain
separation):

E-01 (CVE-2012-2459): Duplicating the last leaf when a level has odd cardinality
allows an attacker to construct an alternate record set with the same Merkle
root. Specifically, given leaves ``[A, B, C]`` the tree duplicates C and hashes
``pair(A, B), pair(C, C)`` then ``pair(pair(A, B), pair(C, C))``. A forger can
present a "real" four-leaf set ``[A, B, C, C]`` that produces the identical
root, undermining the tamper-detection guarantee.

E-02 (second-preimage): Because leaves and internal nodes are hashed by the
same primitive ``sha256(left || right)``, an attacker who knows two adjacent
leaf hashes ``H(L), H(R)`` can claim a *leaf* whose hash equals
``H(H(L) || H(R))`` — i.e. an internal node hash. The proof for that bogus
leaf is the empty proof from the internal node's level upward, and it
verifies against the same root.

Fix: RFC 6962 domain separation — prefix ``0x00`` for leaves, ``0x01`` for
internal nodes. On odd-out levels, promote the unpaired sibling unchanged
instead of duplicating.

These tests will fail against the vulnerable implementation and pass after
the fix.
"""
from __future__ import annotations

import hashlib
import unittest

from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.innovation.ledger import (
    build_merkle_proof,
    compute_merkle_root,
    make_merkle_leaf,
    verify_merkle_proof,
)


def _ev(collector: str, status: str = "ok", category: str = "correctness") -> dict:
    return make_evidence_record(
        collector=collector,
        tool=collector + "-tool",
        category=category,
        status=status,
    )


class CVE_2012_2459_DuplicateLeafTests(unittest.TestCase):
    """Three-leaf set must NOT share a root with the four-leaf duplicate set."""

    def test_three_leaf_root_differs_from_duplicated_four_leaf_root(self) -> None:
        recs3 = [_ev("alpha"), _ev("beta"), _ev("gamma")]
        # Force a sorted-order collision: build a four-leaf set whose sorted
        # leaves equal the three-leaf set with the last leaf duplicated.
        # Since sorting is by (category, collector, tool) and duplicates sort
        # identically, the attacker submits the same three records plus a
        # duplicate of the sorted-last record.
        from story_automator.core.innovation.ledger import _sort_records
        ordered = _sort_records(recs3)
        recs4_forged = list(ordered) + [dict(ordered[-1])]

        root3 = compute_merkle_root(recs3)
        root4 = compute_merkle_root(recs4_forged)
        self.assertNotEqual(
            root3,
            root4,
            "CVE-2012-2459: duplicating the odd-out leaf must not preserve "
            "the Merkle root",
        )


class SecondPreimageInternalNodeAsLeafTests(unittest.TestCase):
    """Internal-node hashes must not be valid leaf hashes."""

    def test_internal_node_hash_does_not_verify_as_leaf(self) -> None:
        # Build a two-leaf tree. The root equals pair(leafA, leafB) under the
        # vulnerable scheme. An attacker claims a "leaf" whose hash equals
        # the root and presents an empty proof — which should NOT verify
        # under a properly domain-separated tree.
        recA = _ev("a")
        recB = _ev("b")
        recs = [recA, recB]
        root = compute_merkle_root(recs)

        # The attacker's forged "leaf hash" is exactly the root. With no
        # domain separation between leaves and internal nodes, the empty
        # proof trivially passes (running == root).
        forged_leaf_hash = root
        empty_proof: list[dict[str, str]] = []
        self.assertFalse(
            verify_merkle_proof(forged_leaf_hash, empty_proof, root),
            "Second-preimage: an internal-node hash must not be accepted as "
            "a leaf hash",
        )

    def test_internal_node_constructed_from_known_leaves_rejected(self) -> None:
        # Stronger variant: attacker computes the internal-node hash from
        # publicly known leaf hashes (no domain separation in the
        # vulnerable code) and submits a forged "leaf" plus the empty
        # proof up from the internal level.
        recs = [_ev(f"r{i}") for i in range(4)]
        root = compute_merkle_root(recs)
        # Reconstruct the level-1 left internal node using the *vulnerable*
        # primitive — concatenation of two leaf hex strings, sha256.
        from story_automator.core.innovation.ledger import (
            _sort_records,
            make_merkle_leaf,
        )
        ordered = _sort_records(recs)
        leaves = [make_merkle_leaf(r) for r in ordered]
        bogus_internal_as_leaf = hashlib.sha256(
            (leaves[0] + leaves[1]).encode("utf-8")
        ).hexdigest()
        # The "proof" required to climb from this fake leaf to root is just
        # the right-half internal node.
        right_internal = hashlib.sha256(
            (leaves[2] + leaves[3]).encode("utf-8")
        ).hexdigest()
        forged_proof = [{"position": "R", "sibling": right_internal}]
        self.assertFalse(
            verify_merkle_proof(bogus_internal_as_leaf, forged_proof, root),
            "Second-preimage: must reject when a forged 'leaf' equals a "
            "known internal-node hash",
        )


class HonestProofsStillVerifyAfterFix(unittest.TestCase):
    """Regression guard: legitimate proofs continue to verify."""

    def test_all_honest_proofs_verify(self) -> None:
        recs = [_ev(f"c{i}") for i in range(7)]
        root = compute_merkle_root(recs)
        for rec in recs:
            leaf = make_merkle_leaf(rec)
            proof = build_merkle_proof(recs, rec)
            self.assertTrue(
                verify_merkle_proof(leaf, proof, root),
                f"honest proof for {rec.get('collector')} must verify",
            )

    def test_single_leaf_root_equals_leaf_hash(self) -> None:
        rec = _ev("only")
        root = compute_merkle_root([rec])
        # A 1-leaf tree's root is the leaf hash itself (under the post-fix
        # scheme this is still true because there are zero internal nodes).
        self.assertEqual(root, make_merkle_leaf(rec))


if __name__ == "__main__":
    unittest.main()
