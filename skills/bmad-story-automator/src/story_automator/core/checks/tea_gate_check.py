"""Compose TEA gate-decision.json as factory evidence (§12).

Reads TEA's gate-decision.json from standard locations and extracts
the overall verdict and per-category results as factory evidence.
Gracefully degrades when TEA output is absent.
Exit 0 = composed or absent, exit 1 = parse error, exit 2 = usage.

Stdout includes a TEA_GATE_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    os.path.join(".tea", "gate-decision.json"),
    os.path.join("_bmad", "gate", "tea-gate-decision.json"),
    "gate-decision.json",
]


def _find_gate_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def _extract_verdict(data: dict) -> dict:
    overall = data.get("overall", data.get("verdict"))
    categories = data.get("categories", {})
    evidence_hash = data.get("evidence_bundle_hash", "")
    return {
        "overall": overall,
        "categories": list(categories.keys()) if isinstance(categories, dict) else [],
        "evidence_hash": evidence_hash,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: tea_gate_check.py <checkout>")
        return 2
    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2

    gate_file = _find_gate_file(checkout)
    if not gate_file:
        result = {"available": False, "overall": None, "categories": []}
        print("TEA gate-decision not available; skipping")
        print(f"TEA_GATE_RESULT: {json.dumps(result)}")
        return 0

    try:
        with open(gate_file, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read TEA gate-decision: {exc}")
        return 1

    extracted = _extract_verdict(data)
    result = {"available": True, **extracted}
    print(f"TEA gate verdict: {extracted['overall']}")
    print(f"TEA_GATE_RESULT: {json.dumps(result)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
