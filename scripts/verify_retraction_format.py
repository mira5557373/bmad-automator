"""Validate REQ-02 retraction bullet format across docs/changelog/*.md (REQ-10)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_DIR = REPO_ROOT / "docs" / "changelog"
# REQ-02: - [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <reason>
BULLET_RE = re.compile(
    r"^- \[(?P<date>\d{4}-\d{2}-\d{2})\] Retracted by "
    r"\[(?P<ref>\d{6})#(?P<anchor>[a-z0-9_-]+)\]"
    r"\(\./(?P<file>\d{6})\.md#(?P<anchor2>[a-z0-9_-]+)\): (?P<reason>\S.*)$"
)
RETRACTIONS_HEADING_RE = re.compile(r"^### Retractions\s*$")
ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
FENCE_RE = re.compile(r"^(```|~~~)")


def find_retraction_bullets(content: str) -> list[tuple[int, str]]:
    """Return [(line_no, line)] for each bullet inside ### Retractions blocks."""
    bullets: list[tuple[int, str]] = []
    in_fence = False
    in_block = False
    for i, line in enumerate(content.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if RETRACTIONS_HEADING_RE.match(line):
            in_block = True
            continue
        if in_block and ANY_HEADING_RE.match(line):
            in_block = False
            continue
        if in_block and line.startswith("- "):
            bullets.append((i, line))
    return bullets


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    for lineno, line in find_retraction_bullets(path.read_text(encoding="utf-8")):
        match = BULLET_RE.match(line)
        if match is None:
            errors.append(f"{path}:{lineno}: malformed retraction bullet: {line!r}")
            continue
        if match.group("ref") != match.group("file"):
            errors.append(
                f"{path}:{lineno}: YYMMDD ref/file mismatch "
                f"({match.group('ref')} vs {match.group('file')})"
            )
        if match.group("anchor") != match.group("anchor2"):
            errors.append(
                f"{path}:{lineno}: anchor text/url mismatch "
                f"({match.group('anchor')!r} vs {match.group('anchor2')!r})"
            )
    return errors


def main(changelog_dir: Path | None = None) -> int:
    target = changelog_dir if changelog_dir is not None else CHANGELOG_DIR
    all_errors: list[str] = []
    for path in sorted(target.glob("*.md")):
        all_errors.extend(validate_file(path))
    for err in all_errors:
        print(err, file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
