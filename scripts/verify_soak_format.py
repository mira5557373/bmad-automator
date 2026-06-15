# scripts/verify_soak_format.py
from __future__ import annotations

import argparse
import json  # noqa: F401  # used by later tasks
import re  # noqa: F401  # used by later tasks
import sys
from datetime import date, datetime  # noqa: F401  # used by later tasks
from pathlib import Path

REQUIRED_FILES = ("telemetry.jsonl", "report.md", "config.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_soak_format.py",
        description="Validate the _bmad-output/soak/ archive layout.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="_bmad-output/soak/",
        help="Path to soak archive root (default: _bmad-output/soak/).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with 2 on usage error; preserve that.
        return int(exc.code) if isinstance(exc.code, int) else 2

    root = Path(args.path)
    if not root.exists():
        print(f"{root}: archive root does not exist", file=sys.stderr)
        return 1

    findings: list[str] = []
    # Future tasks populate findings via _validate_root(root).
    for line in sorted(findings):
        print(line, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
