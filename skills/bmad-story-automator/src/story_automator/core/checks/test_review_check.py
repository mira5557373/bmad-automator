"""Read TEA test-review output and check score against threshold.

Standalone script invoked by the test-review-test-quality collector.
Gracefully degrades when TEA output is absent (exits 0, available=false).
Exit 0 = score meets threshold or TEA absent, exit 1 = below, exit 2 = usage.

Stdout includes a TEST_REVIEW_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    os.path.join(".tea", "test-review.json"),
    "test-review-summary.json",
    os.path.join("_bmad", "gate", "risk", "test-review.json"),
]


def _find_review_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def _extract_score(data: dict) -> float | None:
    score = data.get("score")
    if isinstance(score, (int, float)):
        return float(score)
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: test_review_check.py <checkout> <min_score>")
        return 2
    checkout = args[0]
    try:
        min_score = float(args[1])
    except ValueError:
        print(f"invalid min_score: {args[1]}")
        return 2

    review_file = _find_review_file(checkout)
    if not review_file:
        result = {"score": None, "threshold": min_score,
                  "available": False, "passed": True}
        print("TEA test-review not available; skipping")
        print(f"TEST_REVIEW_RESULT: {json.dumps(result)}")
        return 0

    try:
        with open(review_file, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read test-review data: {exc}")
        return 1

    score = _extract_score(data)
    if score is None:
        print(f"could not parse score from {os.path.basename(review_file)}")
        return 1

    passed = score >= min_score
    result = {"score": score, "threshold": min_score,
              "available": True, "passed": passed}
    print(f"test-review score: {score:.1f} (threshold: {min_score})")
    print(f"TEST_REVIEW_RESULT: {json.dumps(result)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
