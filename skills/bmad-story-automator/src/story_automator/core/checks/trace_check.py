"""Check AC/task/test traceability and File List completeness.

Standalone script invoked by the trace-process collector.
Scans _bmad/stories/*.md for a "File List" heading section.
Exit 0 = all pass (or no story dir). Exit 1 = issues found.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_FILE_LIST_RE = re.compile(
    r"^#+\s+File\s+List", re.MULTILINE | re.IGNORECASE
)
_STORY_RELDIR = os.path.join("_bmad", "stories")


def _check_story_file(path: str) -> list[str]:
    issues: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    filename = os.path.basename(path)
    match = _FILE_LIST_RE.search(content)
    if not match:
        issues.append(f"MISSING File List: {filename}")
    else:
        after = content[match.end():]
        next_heading = re.search(r"^#+\s", after, re.MULTILINE)
        section = after[:next_heading.start()] if next_heading else after
        items = [ln for ln in section.strip().splitlines() if ln.strip().startswith("-")]
        if not items:
            issues.append(f"EMPTY File List: {filename}")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: trace_check.py <checkout>")
        return 2
    checkout = args[0]
    story_dir = os.path.join(checkout, _STORY_RELDIR)
    if not os.path.isdir(story_dir):
        print(f"no story directory: {_STORY_RELDIR}")
        return 0
    story_files = sorted(
        f for f in os.listdir(story_dir) if f.endswith(".md")
    )
    if not story_files:
        print("no story files found")
        return 0
    all_issues: list[str] = []
    for story_file in story_files:
        path = os.path.join(story_dir, story_file)
        all_issues.extend(_check_story_file(path))
    for issue in all_issues:
        print(issue)
    if all_issues:
        print(f"{len(all_issues)} traceability issue(s) found")
        return 1
    print(f"all {len(story_files)} story file(s) pass traceability checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
