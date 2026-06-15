# scripts/verify_soak_format.py
from __future__ import annotations

import argparse
import json  # noqa: F401  # used by later tasks
import re
import sys
from datetime import date, datetime  # noqa: F401  # used by later tasks
from pathlib import Path

REQUIRED_FILES = ("telemetry.jsonl", "report.md", "config.json")

ARM_SLUG_RE = re.compile(r"^[a-z0-9._-]+$")


def _validate_date_dir(name: str) -> str | None:
    try:
        date.fromisoformat(name)
    except ValueError:
        return f"date directory name does not parse as ISO date: {name!r}"
    return None


def _validate_arm_slug(name: str) -> str | None:
    if not ARM_SLUG_RE.match(name):
        return f"arm directory name is not a valid slug [a-z0-9._-]+: {name!r}"
    return None


def _validate_root(root: Path) -> list[str]:
    findings: list[str] = []
    for date_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        date_err = _validate_date_dir(date_dir.name)
        if date_err is not None:
            findings.append(f"{date_dir}: {date_err}")
            continue
        for arm_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            arm_err = _validate_arm_slug(arm_dir.name)
            if arm_err is not None:
                findings.append(f"{arm_dir}: {arm_err}")
                continue
    return findings


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

    findings = _validate_root(root)
    for line in sorted(findings):
        print(line, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
