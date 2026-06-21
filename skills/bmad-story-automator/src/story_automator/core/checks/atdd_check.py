"""Verify TEA ATDD RED phase was observed (§8 module 2).

Reads TEA's ATDD output to confirm that acceptance tests were written
before implementation (RED phase: tests fail). Gracefully degrades
when TEA ATDD output is absent.
Exit 0 = RED verified or TEA absent, exit 1 = RED not verified, exit 2 = usage.

Stdout includes an ATDD_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    os.path.join(".tea", "atdd-result.json"),
    os.path.join("_bmad", "gate", "risk", "atdd-result.json"),
    "atdd-result.json",
]


def _find_atdd_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: atdd_check.py <checkout>")
        return 2
    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2

    atdd_file = _find_atdd_file(checkout)
    if not atdd_file:
        result = {"available": False, "red_verified": None, "passed": True}
        print("TEA ATDD output not available; skipping")
        print(f"ATDD_RESULT: {json.dumps(result)}")
        return 0

    try:
        with open(atdd_file, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read ATDD data: {exc}")
        return 1

    red_verified = data.get("red_verified", data.get("red_phase", False))
    if isinstance(red_verified, str):
        red_verified = red_verified.lower() in ("true", "yes", "pass")

    result = {
        "available": True,
        "red_verified": bool(red_verified),
        "tests_written": int(data.get("tests_written", 0)),
        "tests_failing": int(data.get("tests_failing", 0)),
        "passed": bool(red_verified),
    }
    status = "verified" if red_verified else "NOT verified"
    print(f"ATDD RED phase: {status}")
    print(f"ATDD_RESULT: {json.dumps(result)}")
    return 0 if red_verified else 1


if __name__ == "__main__":
    sys.exit(main())
