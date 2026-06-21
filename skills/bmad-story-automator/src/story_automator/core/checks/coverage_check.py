"""Check that code coverage meets the required threshold.

Standalone script invoked by the coverage-correctness collector.
Looks for coverage data in common locations (pytest-cov, istanbul/vitest).
Exit 0 = threshold met, exit 1 = below threshold or no data, exit 2 = usage.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    "coverage.json",
    ".coverage.json",
    os.path.join("htmlcov", "status.json"),
    os.path.join("coverage", "coverage-summary.json"),
]


def _find_coverage_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def _extract_coverage_pct(data: dict) -> float | None:
    if "totals" in data:
        pct = data["totals"].get("percent_covered")
        if isinstance(pct, (int, float)):
            return float(pct)
    if "total" in data:
        lines = data.get("total", {}).get("lines", {})
        pct = lines.get("pct")
        if isinstance(pct, (int, float)):
            return float(pct)
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: coverage_check.py <checkout> <threshold_pct>")
        return 2
    checkout = args[0]
    try:
        threshold = int(args[1])
    except ValueError:
        print(f"invalid threshold: {args[1]}")
        return 2
    coverage_file = _find_coverage_file(checkout)
    if not coverage_file:
        print("no coverage data found")
        return 1
    try:
        with open(coverage_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read coverage data: {exc}")
        return 1
    pct = _extract_coverage_pct(data)
    if pct is None:
        print(f"could not parse coverage from {os.path.basename(coverage_file)}")
        return 1
    print(f"coverage: {pct:.1f}% (threshold: {threshold}%)")
    if pct < threshold:
        print(f"BELOW THRESHOLD: {pct:.1f}% < {threshold}%")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
