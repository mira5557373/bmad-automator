"""M54 merkle-nfr-ledger — hash-chained NFR evidence with Merkle proofs.

Layers an append-only JSONL ledger and a Merkle tree over the existing
``EvidenceRecord`` schema.  Both primitives are additive: nothing in
``evidence_io`` or ``gate_schema`` changes shape, so historical evidence
bundles stay byte-stable.

Design notes:
* Leaf hash = SHA-256 of ``canonical_json(record)`` — order-independent,
  matches ``compute_evidence_bundle_hash``'s sort key.
* Internal nodes pair siblings; an odd leaf at any level is duplicated
  (Bitcoin convention) to keep the tree balanced.
* Proofs are a list of ``{position, sibling}`` steps from leaf to root
  and verify in O(log n) without re-hashing the bundle.
* Ledger rows carry ``prev_hash`` linking back to the prior row, so a
  single mutation breaks the chain even before Merkle verification.

Stdlib only.  ~400 LOC budget.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..gate_schema import (
    GateSchemaError,
    canonical_json,
    validate_evidence_record,
)
from ..utils import ensure_dir

GENESIS_PREV_HASH = "0" * 64
LEDGER_SCHEMA_VERSION = 1


class MerkleLedgerError(ValueError):
    """Raised for any malformed input or chain integrity failure."""


# ----------------------------------------------------------------------------
# Leaf + root primitives.
# ----------------------------------------------------------------------------


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_merkle_leaf(record: dict[str, Any]) -> str:
    """Return the leaf hash (64-hex SHA-256) for an evidence record.

    Uses ``canonical_json`` so equivalent records always hash identically.
    """
    if not isinstance(record, dict):
        raise MerkleLedgerError(
            "merkle leaf requires a dict evidence record, got "
            f"{type(record).__name__}"
        )
    payload = canonical_json(record).encode("utf-8")
    return _sha256_hex(payload)


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order records by (category, collector, tool) — matches bundle hash."""
    return sorted(
        records,
        key=lambda r: (
            r.get("category", ""),
            r.get("collector", ""),
            r.get("tool", ""),
        ),
    )


def _pair_hash(left: str, right: str) -> str:
    """Concatenate sibling hashes and SHA-256 the bytes."""
    return _sha256_hex((left + right).encode("utf-8"))


def _build_levels(leaves: list[str]) -> list[list[str]]:
    """Build the Merkle tree bottom-up; duplicate odd-out siblings.

    Returns the list of levels (level 0 = leaves, last level = [root]).
    """
    if not leaves:
        raise MerkleLedgerError("cannot build Merkle tree over zero leaves")
    levels: list[list[str]] = [list(leaves)]
    current = list(leaves)
    while len(current) > 1:
        nxt: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            nxt.append(_pair_hash(left, right))
        levels.append(nxt)
        current = nxt
    return levels


def compute_merkle_root(records: list[dict[str, Any]]) -> str:
    """Return the Merkle root (64-hex) over an evidence record list.

    Records are sorted deterministically; the same set always yields
    the same root regardless of input order.
    """
    if not records:
        raise MerkleLedgerError("cannot compute Merkle root over empty list")
    ordered = _sort_records(records)
    leaves = [make_merkle_leaf(r) for r in ordered]
    levels = _build_levels(leaves)
    return levels[-1][0]


def build_merkle_proof(
    records: list[dict[str, Any]],
    target: dict[str, Any],
) -> list[dict[str, str]]:
    """Return a proof path linking ``target`` to the Merkle root.

    Each step is ``{"position": "L"|"R", "sibling": <hex>}`` describing
    where the sibling sits relative to the running hash.  A tree with a
    single leaf returns ``[]`` — the leaf already equals the root.
    """
    if not isinstance(target, dict):
        raise MerkleLedgerError("target must be a dict evidence record")
    if not records:
        raise MerkleLedgerError("cannot build proof over empty record list")
    ordered = _sort_records(records)
    target_leaf = make_merkle_leaf(target)
    leaves = [make_merkle_leaf(r) for r in ordered]
    try:
        index = leaves.index(target_leaf)
    except ValueError as exc:
        raise MerkleLedgerError(
            "target record not present in record set"
        ) from exc

    levels = _build_levels(leaves)
    proof: list[dict[str, str]] = []
    idx = index
    for level in levels[:-1]:
        if idx % 2 == 0:
            sibling_idx = idx + 1 if idx + 1 < len(level) else idx
            position = "R"
        else:
            sibling_idx = idx - 1
            position = "L"
        proof.append({"position": position, "sibling": level[sibling_idx]})
        idx //= 2
    return proof


def verify_merkle_proof(
    leaf_hash: str,
    proof: list[dict[str, str]],
    expected_root: str,
) -> bool:
    """Replay ``proof`` from ``leaf_hash`` and compare to ``expected_root``."""
    if not isinstance(leaf_hash, str) or len(leaf_hash) != 64:
        return False
    if not isinstance(expected_root, str) or len(expected_root) != 64:
        return False
    if not isinstance(proof, list):
        return False
    running = leaf_hash
    for step in proof:
        if not isinstance(step, dict):
            return False
        position = step.get("position")
        sibling = step.get("sibling")
        if (
            not isinstance(sibling, str)
            or len(sibling) != 64
            or position not in ("L", "R")
        ):
            return False
        if position == "R":
            running = _pair_hash(running, sibling)
        else:
            running = _pair_hash(sibling, running)
    return running == expected_root


# ----------------------------------------------------------------------------
# Append-only NFR ledger.
# ----------------------------------------------------------------------------


def _row_hash(prev_hash: str, evidence: dict[str, Any]) -> str:
    payload = canonical_json(
        {"prev_hash": prev_hash, "evidence": evidence}
    ).encode("utf-8")
    return _sha256_hex(payload)


class NFRLedger:
    """Append-only JSONL ledger of NFR evidence rows with hash chaining.

    Each row is::

        {
          "schema_version": 1,
          "seq": <int>,
          "prev_hash": <64-hex or 0*64>,
          "row_hash": <64-hex>,
          "evidence": <EvidenceRecord>
        }

    On disk: one JSON object per line, ``\\n`` terminated, UTF-8.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ---- writes ---------------------------------------------------------

    def append(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Validate ``evidence`` and append a hash-chained row.

        Returns the persisted row dict.  Raises ``MerkleLedgerError`` if
        the evidence record is malformed.
        """
        if not isinstance(evidence, dict):
            raise MerkleLedgerError(
                "evidence must be a dict EvidenceRecord, got "
                f"{type(evidence).__name__}"
            )
        try:
            validate_evidence_record(evidence)
        except GateSchemaError as exc:
            raise MerkleLedgerError(
                f"invalid evidence record: {exc}"
            ) from exc

        ensure_dir(self.path.parent)
        existing = self._read_lines()
        if existing:
            try:
                last = json.loads(existing[-1])
            except json.JSONDecodeError as exc:
                raise MerkleLedgerError(
                    f"ledger tail unreadable: {exc}"
                ) from exc
            prev_hash = last.get("row_hash")
            if not isinstance(prev_hash, str) or len(prev_hash) != 64:
                raise MerkleLedgerError("ledger tail missing valid row_hash")
            seq = int(last.get("seq", 0)) + 1
        else:
            prev_hash = GENESIS_PREV_HASH
            seq = 0

        row_hash = _row_hash(prev_hash, evidence)
        row: dict[str, Any] = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "seq": seq,
            "prev_hash": prev_hash,
            "row_hash": row_hash,
            "evidence": evidence,
        }
        encoded = canonical_json(row)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(encoded + "\n")
        return row

    # ---- reads ----------------------------------------------------------

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if line.strip()]

    def read_all(self) -> list[dict[str, Any]]:
        """Return all ledger rows as parsed dicts in append order."""
        rows: list[dict[str, Any]] = []
        for idx, line in enumerate(self._read_lines()):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MerkleLedgerError(
                    f"ledger row {idx} not valid JSON: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise MerkleLedgerError(
                    f"ledger row {idx} must be a JSON object"
                )
            rows.append(row)
        return rows

    # ---- integrity ------------------------------------------------------

    def verify_chain(self) -> bool:
        """Return True if every row's prev_hash/row_hash is internally consistent."""
        rows = self.read_all()
        expected_prev = GENESIS_PREV_HASH
        expected_seq = 0
        for row in rows:
            if row.get("seq") != expected_seq:
                return False
            if row.get("prev_hash") != expected_prev:
                return False
            evidence = row.get("evidence")
            if not isinstance(evidence, dict):
                return False
            recomputed = _row_hash(expected_prev, evidence)
            if recomputed != row.get("row_hash"):
                return False
            expected_prev = recomputed
            expected_seq += 1
        return True

    def merkle_root(self) -> str:
        """Return the Merkle root of the evidence records persisted so far."""
        rows = self.read_all()
        if not rows:
            raise MerkleLedgerError("ledger is empty")
        records = [row.get("evidence") for row in rows]
        # All rows have evidence dicts because append() validated them.
        return compute_merkle_root([r for r in records if isinstance(r, dict)])
