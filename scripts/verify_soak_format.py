# scripts/verify_soak_format.py
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

REQUIRED_FILES = ("telemetry.jsonl", "report.md", "config.json")

ARM_SLUG_RE = re.compile(r"^[a-z0-9._-]+$")

REQUIRED_FRONTMATTER_KEYS = (
    "arm",
    "date",
    "run_id",
    "git_sha",
    "started_at",
    "ended_at",
)
_FRONTMATTER_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def _read_text_lf(path: Path) -> str:
    # NFR: treat CRLF and LF equivalently when reading.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    result: dict[str, str] = {}
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() == "---":
            return result
        match = _FRONTMATTER_LINE_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        # Strip optional surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return None  # closing --- not found


def _parse_iso_datetime(value: str) -> bool:
    # Normalize 'Z' suffix to '+00:00' so behavior is identical on 3.11+
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_report_md(arm_dir: Path) -> list[str]:
    path = arm_dir / "report.md"
    findings: list[str] = []
    try:
        text = _read_text_lf(path)
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    fm = _parse_frontmatter(text)
    if fm is None:
        return [f"{path}: missing or unterminated YAML frontmatter block"]
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm:
            findings.append(f"{path}: frontmatter missing required key {key!r}")
    started = fm.get("started_at")
    if started is not None and not _parse_iso_datetime(started):
        findings.append(
            f"{path}: frontmatter 'started_at' does not parse as ISO datetime: {started!r}"
        )
    ended = fm.get("ended_at")
    if ended is not None and not _parse_iso_datetime(ended):
        findings.append(
            f"{path}: frontmatter 'ended_at' does not parse as ISO datetime: {ended!r}"
        )
    return findings


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


CONFIG_SCHEMA: tuple[tuple[str, type], ...] = (
    ("arm", str),
    ("seed", int),
    ("model", str),
    ("concurrency", int),
    ("notes", str),
)


def _validate_config_json(arm_dir: Path) -> list[str]:
    path = arm_dir / "config.json"
    findings: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc.msg}"]
    if not isinstance(data, dict):
        return [f"{path}: top-level value must be a JSON object"]
    for key, expected_type in CONFIG_SCHEMA:
        if key not in data:
            findings.append(f"{path}: missing required key {key!r}")
            continue
        value = data[key]
        # Reject bool for int (bool is subclass of int in Python).
        if expected_type is int and isinstance(value, bool):
            findings.append(f"{path}: key {key!r} must be int, got bool")
        elif not isinstance(value, expected_type):
            findings.append(
                f"{path}: key {key!r} must be {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
    arm_value = data.get("arm")
    if isinstance(arm_value, str) and arm_value != arm_dir.name:
        findings.append(
            f"{path}: config 'arm' = {arm_value!r} does not match directory name {arm_dir.name!r}"
        )
    return findings


def _validate_telemetry_jsonl(arm_dir: Path) -> list[str]:
    path = arm_dir / "telemetry.jsonl"
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    # NFR: normalize CRLF to LF before splitting so behavior matches
    # across OSes.
    for idx, raw_line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"{path}:{idx}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(obj, dict):
            findings.append(f"{path}:{idx}: line is not a JSON object")
            continue
        if not isinstance(obj.get("event_type"), str):
            findings.append(f"{path}:{idx}: missing string field 'event_type'")
        if not isinstance(obj.get("ts"), str):
            findings.append(f"{path}:{idx}: missing string field 'ts'")
    return findings


def _validate_arm_dir(arm_dir: Path) -> list[str]:
    findings: list[str] = []
    for name in REQUIRED_FILES:
        if not (arm_dir / name).is_file():
            findings.append(f"{arm_dir / name}: required file missing")
    if (arm_dir / "report.md").is_file():
        findings.extend(_validate_report_md(arm_dir))
    if (arm_dir / "config.json").is_file():
        findings.extend(_validate_config_json(arm_dir))
    if (arm_dir / "telemetry.jsonl").is_file():
        findings.extend(_validate_telemetry_jsonl(arm_dir))
    return findings


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
            findings.extend(_validate_arm_dir(arm_dir))
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
