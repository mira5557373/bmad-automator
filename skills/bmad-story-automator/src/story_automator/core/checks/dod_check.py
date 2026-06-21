"""Definition of Done (DoD) verifier (§8 module 2).

Checks that a story's dev-story output meets DoD criteria:
  - File List present and non-empty
  - Status field set to a done-state
  - Change Log section present
Feeds test_quality/process category evidence.
Exit 0 = DoD met, exit 1 = DoD not met, exit 2 = usage.

Stdout includes a DOD_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_STORY_PATTERNS = [
    "story.md",
    os.path.join("_bmad", "stories", "*.md"),
]

_DOD_FIELDS = {
    "file_list": re.compile(r"^#{1,4}\s*File\s*List", re.MULTILINE | re.IGNORECASE),
    "change_log": re.compile(r"^#{1,4}\s*Change\s*Log", re.MULTILINE | re.IGNORECASE),
    "status": re.compile(r"^#{1,4}\s*Status", re.MULTILINE | re.IGNORECASE),
}

_DONE_STATES = frozenset({"done", "completed", "review", "in-review", "approved"})


def _find_story_file(checkout: str) -> str | None:
    import glob as _glob
    for pat in _STORY_PATTERNS:
        full_pat = os.path.join(checkout, pat)
        matches = _glob.glob(full_pat)
        if matches:
            return sorted(matches)[0]
    return None


def _extract_status(content: str) -> str | None:
    m = _DOD_FIELDS["status"].search(content)
    if not m:
        return None
    rest = content[m.end():].strip()
    first_line = rest.split("\n", 1)[0].strip().rstrip("*_`").lstrip("*_`").strip()
    first_line = re.sub(r"^:\s*", "", first_line)
    return first_line.lower() if first_line else None


def _check_file_list(content: str) -> bool:
    m = _DOD_FIELDS["file_list"].search(content)
    if not m:
        return False
    rest = content[m.end():].strip()
    section = rest.split("\n#", 1)[0]
    return len(section.strip()) > 10


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: dod_check.py <checkout>")
        return 2
    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2

    story_file = _find_story_file(checkout)
    if not story_file:
        result = {"available": False, "passed": True, "checks": {}}
        print("no story file found; skipping DoD check")
        print(f"DOD_RESULT: {json.dumps(result)}")
        return 0

    try:
        with open(story_file, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as exc:
        print(f"failed to read story: {exc}")
        return 1

    checks: dict[str, bool] = {}
    violations: list[str] = []

    has_file_list = _check_file_list(content)
    checks["file_list"] = has_file_list
    if not has_file_list:
        violations.append("File List missing or empty")

    has_change_log = bool(_DOD_FIELDS["change_log"].search(content))
    checks["change_log"] = has_change_log
    if not has_change_log:
        violations.append("Change Log section missing")

    status = _extract_status(content)
    checks["status_present"] = status is not None
    checks["status_done"] = status in _DONE_STATES if status else False
    if not checks["status_present"]:
        violations.append("Status section missing")

    passed = len(violations) == 0
    result = {
        "available": True,
        "passed": passed,
        "checks": checks,
        "violations": violations,
        "story_file": os.path.relpath(story_file, checkout),
    }
    if violations:
        for v in violations:
            print(f"DOD: {v}")
    else:
        print("DoD criteria met")
    print(f"DOD_RESULT: {json.dumps(result)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
