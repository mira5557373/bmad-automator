"""Verify capacity-plan doc exists and declares sufficient headroom.

Standalone script invoked by the ``capacity-plan-scalability`` collector
(see ``core/collectors/scalability.py``).  Reads the capacity-plan
markdown file at the given checkout-relative path and verifies it
declares a ``headroom_pct`` value that meets or exceeds the
``--min-headroom-pct`` floor.

Headroom is parsed from a line of the form ``headroom_pct: <N>`` (case
insensitive, allows surrounding whitespace and an optional leading
``-`` / ``*`` bullet) anywhere in the document.

Exit 0 = headroom OK, exit 1 = missing doc / missing field / below
floor, exit 2 = usage error.  Stdlib only — no story_automator
imports (the script runs in the trust-boundary sandbox checkout).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HEADROOM_RE = re.compile(
    r"""^[\s\-\*>]*headroom_pct\s*[:=]\s*(\d+)""",
    re.IGNORECASE | re.MULTILINE,
)


def parse_headroom(content: str) -> int | None:
    """Return the first integer headroom_pct value found, or None."""
    match = _HEADROOM_RE.search(content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def evaluate(checkout: str, doc_path: str, min_headroom_pct: int) -> int:
    """Return process exit code per docstring contract."""
    doc = Path(checkout) / doc_path
    if not doc.is_file():
        print(f"MISSING-DOC: capacity plan not found at {doc_path}")
        return 1
    try:
        content = doc.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"UNREADABLE-DOC: {doc_path}: {exc}")
        return 1
    headroom = parse_headroom(content)
    if headroom is None:
        print(
            f"MISSING-FIELD: {doc_path} has no headroom_pct declaration"
        )
        return 1
    if headroom < min_headroom_pct:
        print(
            f"INSUFFICIENT-HEADROOM: {doc_path}: "
            f"declared={headroom}%, floor={min_headroom_pct}%"
        )
        return 1
    print(
        f"headroom_pct={headroom}% meets floor "
        f"{min_headroom_pct}% in {doc_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capacity_plan_check.py",
        description="Verify capacity-plan doc declares headroom_pct "
        ">= the configured floor.",
    )
    parser.add_argument("checkout")
    parser.add_argument("doc_path")
    parser.add_argument(
        "--min-headroom-pct",
        type=int,
        required=True,
        dest="min_headroom_pct",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse uses exit code 2 for usage errors which matches our
        # contract; surface it explicitly for clarity.
        return int(exc.code) if exc.code is not None else 2
    return evaluate(args.checkout, args.doc_path, args.min_headroom_pct)


if __name__ == "__main__":
    sys.exit(main())
