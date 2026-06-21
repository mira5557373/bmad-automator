"""Check that required files exist in a checkout directory.

Standalone script invoked by the doc-presence collector.
Exit 0 = all present, exit 1 = missing, exit 2 = usage error.
Prints MISSING: <path> for each absent file.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: presence_check.py <checkout> <json_file_list>")
        return 2
    checkout = args[0]
    try:
        required: list[str] = json.loads(args[1])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid file list: {args[1]}")
        return 2
    if not isinstance(required, list) or not all(
        isinstance(f, str) for f in required
    ):
        print("file list must be a JSON string array")
        return 2
    missing = [
        f for f in required
        if not os.path.isfile(os.path.join(checkout, f))
    ]
    for f in missing:
        print(f"MISSING: {f}")
    if missing:
        print(f"{len(missing)} required file(s) missing")
        return 1
    print(f"all {len(required)} required file(s) present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
