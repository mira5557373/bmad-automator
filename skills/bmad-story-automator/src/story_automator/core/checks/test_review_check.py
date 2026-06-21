"""Check TEA test-review score against threshold.

Standalone script invoked by the test-review-test_quality collector.
Exit 0 = score met (or no review), exit 1 = below threshold, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_TEA_REVIEW_PATH = os.path.join("_bmad", "gate", "tea", "test-review.json")


def read_tea_review(path: str) -> dict:
    """Read TEA test-review JSON. Returns {} on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def check_score(
    review: dict, min_score: int,
) -> tuple[bool, list[str]]:
    """Check overall_score against min_score threshold."""
    if not review:
        return False, ["no test-review data available"]
    score = review.get("overall_score")
    if score is None:
        return False, ["test-review missing overall_score"]
    if not isinstance(score, (int, float)):
        return False, [f"test-review overall_score not numeric: {score!r}"]
    if score < min_score:
        return False, [
            f"test-review score {score} below threshold {min_score}"
        ]
    return True, []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: test_review_check.py <checkout> <min_score>")
        return 2
    checkout = args[0]
    try:
        min_score = int(args[1])
    except ValueError:
        print(f"invalid min_score: {args[1]}")
        return 2
    review_path = os.path.join(checkout, _TEA_REVIEW_PATH)
    review = read_tea_review(review_path)
    if not review:
        print("TEA test-review not found — graceful pass")
        return 0
    ok, issues = check_score(review, min_score)
    for issue in issues:
        print(issue)
    if not ok:
        return 1
    print(f"test-review score {review.get('overall_score')} >= {min_score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
