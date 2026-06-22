"""M54 merkle-nfr-ledger — tests.

Verifies the Merkle hash-chain over NFR evidence rows and the additive
bundle-Merkle-root helper on top of evidence_io.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.evidence_io import (
    compute_evidence_bundle_merkle_root,
)
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.innovation.ledger import (
    MerkleLedgerError,
    NFRLedger,
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


class MerkleLeafTests(unittest.TestCase):
    def test_leaf_is_deterministic_for_equal_records(self) -> None:
        a = _ev("c1")
        b = _ev("c1")
        self.assertEqual(make_merkle_leaf(a), make_merkle_leaf(b))

    def test_leaf_differs_on_any_field_change(self) -> None:
        a = _ev("c1")
        b = _ev("c1", status="violation")
        self.assertNotEqual(make_merkle_leaf(a), make_merkle_leaf(b))

    def test_leaf_rejects_non_dict(self) -> None:
        with self.assertRaises(MerkleLedgerError):
            make_merkle_leaf("not a dict")  # type: ignore[arg-type]


class MerkleRootTests(unittest.TestCase):
    def test_root_of_single_leaf_equals_leaf(self) -> None:
        rec = _ev("only-one")
        root = compute_merkle_root([rec])
        self.assertEqual(root, make_merkle_leaf(rec))

    def test_root_order_independent(self) -> None:
        recs = [_ev("a"), _ev("b"), _ev("c")]
        r1 = compute_merkle_root(recs)
        r2 = compute_merkle_root(list(reversed(recs)))
        self.assertEqual(r1, r2)

    def test_root_changes_when_record_changes(self) -> None:
        recs1 = [_ev("a"), _ev("b"), _ev("c")]
        recs2 = [_ev("a"), _ev("b", status="violation"), _ev("c")]
        self.assertNotEqual(
            compute_merkle_root(recs1), compute_merkle_root(recs2)
        )

    def test_root_handles_odd_count_by_duplicating_last(self) -> None:
        # 3 leaves -> level 1: [pair(0,1), pair(2,2)] -> level 2: pair(...)
        # ensure deterministic 64-hex output
        recs = [_ev("a"), _ev("b"), _ev("c")]
        root = compute_merkle_root(recs)
        self.assertEqual(len(root), 64)
        int(root, 16)  # must be hex

    def test_root_empty_raises(self) -> None:
        with self.assertRaises(MerkleLedgerError):
            compute_merkle_root([])


class MerkleProofTests(unittest.TestCase):
    def test_proof_verifies_for_each_leaf(self) -> None:
        recs = [_ev(f"c{i}") for i in range(7)]
        root = compute_merkle_root(recs)
        for rec in recs:
            leaf = make_merkle_leaf(rec)
            proof = build_merkle_proof(recs, rec)
            self.assertTrue(verify_merkle_proof(leaf, proof, root))

    def test_proof_rejects_tampered_leaf(self) -> None:
        recs = [_ev(f"c{i}") for i in range(5)]
        root = compute_merkle_root(recs)
        proof = build_merkle_proof(recs, recs[2])
        tampered = hashlib.sha256(b"forged").hexdigest()
        self.assertFalse(verify_merkle_proof(tampered, proof, root))

    def test_proof_for_missing_record_raises(self) -> None:
        recs = [_ev("a"), _ev("b")]
        with self.assertRaises(MerkleLedgerError):
            build_merkle_proof(recs, _ev("not-in-set"))

    def test_proof_single_leaf_has_empty_steps(self) -> None:
        recs = [_ev("only")]
        proof = build_merkle_proof(recs, recs[0])
        self.assertEqual(proof, [])
        # Pass the record itself; the verifier applies the RFC 6962 leaf
        # domain prefix internally, which is the only safe way to handle
        # the empty-proof case (a raw-hash caller would be ambiguous with
        # an internal-node-as-leaf forgery).
        self.assertTrue(
            verify_merkle_proof(recs[0], proof, compute_merkle_root(recs))
        )


class NFRLedgerTests(unittest.TestCase):
    def test_append_creates_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = NFRLedger(Path(td) / "nfr.jsonl")
            ledger.append(_ev("perf-1", category="performance"))
            ledger.append(_ev("perf-2", category="performance"))
            rows = ledger.read_all()
            self.assertEqual(len(rows), 2)
            # genesis prev_hash is 64-zero
            self.assertEqual(rows[0]["prev_hash"], "0" * 64)
            self.assertEqual(rows[1]["prev_hash"], rows[0]["row_hash"])

    def test_verify_chain_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nfr.jsonl"
            ledger = NFRLedger(path)
            ledger.append(_ev("a"))
            ledger.append(_ev("b"))
            ledger.append(_ev("c"))
            self.assertTrue(ledger.verify_chain())
            # tamper a middle row
            lines = path.read_text(encoding="utf-8").splitlines()
            row = json.loads(lines[1])
            row["evidence"]["collector"] = "FORGED"
            lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(ledger.verify_chain())

    def test_merkle_root_matches_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = NFRLedger(Path(td) / "nfr.jsonl")
            recs = [
                _ev("x", category="performance"),
                _ev("y", category="scalability"),
                _ev("z", category="accessibility"),
            ]
            for r in recs:
                ledger.append(r)
            expected = compute_merkle_root(recs)
            self.assertEqual(ledger.merkle_root(), expected)

    def test_merkle_root_empty_ledger_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = NFRLedger(Path(td) / "nfr.jsonl")
            with self.assertRaises(MerkleLedgerError):
                ledger.merkle_root()

    def test_append_rejects_invalid_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = NFRLedger(Path(td) / "nfr.jsonl")
            with self.assertRaises(MerkleLedgerError):
                ledger.append({"not": "a-valid-evidence-record"})


class EvidenceIoBundleMerkleTests(unittest.TestCase):
    def test_bundle_merkle_root_matches_ledger(self) -> None:
        recs = [_ev("a"), _ev("b"), _ev("c"), _ev("d")]
        self.assertEqual(
            compute_evidence_bundle_merkle_root(recs),
            compute_merkle_root(recs),
        )

    def test_bundle_merkle_root_empty_raises(self) -> None:
        with self.assertRaises(MerkleLedgerError):
            compute_evidence_bundle_merkle_root([])


if __name__ == "__main__":
    unittest.main()
