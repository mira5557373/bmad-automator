# scripts/seed_soak_dir.py
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:  # REQ-09: prefer story_automator helpers when available.
    from story_automator.core.common import (
        compact_json,
        ensure_dir,
        iso_now,
        write_atomic,
    )
except ImportError:  # Fallback: pure-stdlib equivalents.
    import datetime as _dt
    import os as _os
    import tempfile as _tempfile
    from typing import Any as _Any

    def iso_now() -> str:
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def compact_json(value: _Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    def ensure_dir(path: str | Path) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def write_atomic(path: str | Path, data: str | bytes) -> None:
        target = Path(path)
        ensure_dir(target.parent)
        fd, tmp_name = _tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with _os.fdopen(fd, "wb") as handle:
                payload = data.encode("utf-8") if isinstance(data, str) else data
                handle.write(payload)
                handle.flush()
                _os.fsync(handle.fileno())
            _os.replace(tmp_name, target)
        finally:
            try:
                _os.unlink(tmp_name)
            except FileNotFoundError:
                pass


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARM_SLUG_RE = re.compile(r"^[a-z0-9._-]+$")
DEFAULT_ROOT = "_bmad-output/soak/"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_soak_dir.py",
        description="Seed a soak-archive arm directory with stub files.",
    )
    parser.add_argument("--date", required=True, help="ISO calendar date YYYY-MM-DD.")
    parser.add_argument("--arm", required=True, help="Arm slug matching [a-z0-9._-]+.")
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"Soak archive root (default: {DEFAULT_ROOT}).",
    )
    return parser


def _config_defaults(arm: str) -> dict[str, object]:
    return {
        "arm": arm,
        "seed": 0,
        "model": "unset",
        "concurrency": 1,
        "notes": "",
    }


def _report_frontmatter(arm: str, date_str: str, started_at: str) -> str:
    # NFR: explicit \n joins so output is byte-identical on Windows and Linux.
    lines = (
        "---",
        f"arm: {arm}",
        f"date: {date_str}",
        "run_id: pending",
        "git_sha: pending",
        f"started_at: {started_at}",
        "ended_at: pending",
        "---",
        "",
    )
    return "\n".join(lines)


def _seed_if_absent(path: Path, contents: str) -> bool:
    # REQ-09: idempotent. Never clobber an existing non-empty file.
    if path.exists() and path.stat().st_size > 0:
        return False
    write_atomic(path, contents)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not DATE_RE.match(args.date):
        print(f"--date must be YYYY-MM-DD: {args.date!r}", file=sys.stderr)
        return 2
    if not ARM_SLUG_RE.match(args.arm):
        print(f"--arm must match [a-z0-9._-]+: {args.arm!r}", file=sys.stderr)
        return 2

    arm_dir = Path(args.root) / args.date / args.arm
    ensure_dir(arm_dir)

    started_at = iso_now()
    config_text = compact_json(_config_defaults(args.arm))
    report_text = _report_frontmatter(args.arm, args.date, started_at)

    _seed_if_absent(arm_dir / "telemetry.jsonl", "")
    _seed_if_absent(arm_dir / "config.json", config_text)
    _seed_if_absent(arm_dir / "report.md", report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
