"""Check Alembic migrations for reversibility and advisory-lock usage.

Standalone script invoked by the migration-lint collector.
Scans migration files for missing downgrade functions and
data migrations without advisory locks.
Exit 0 = clean, exit 1 = issues, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_DOWNGRADE_RE = re.compile(r"^def\s+downgrade\s*\(", re.MULTILINE)
_DOWNGRADE_PASS_RE = re.compile(
    r"def\s+downgrade\s*\([^)]*\)\s*:\s*\n\s+pass\s*$", re.MULTILINE,
)
_DATA_DML_RE = re.compile(
    r"op\.execute\s*\(\s*['\"](?:UPDATE|DELETE|INSERT)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ADVISORY_LOCK_RE = re.compile(r"pg_advisory_lock", re.IGNORECASE)


def check_reversibility(content: str, filename: str) -> list[str]:
    """Check a migration has a non-empty downgrade function."""
    issues: list[str] = []
    if not _DOWNGRADE_RE.search(content):
        issues.append(f"MISSING downgrade: {filename}")
    elif _DOWNGRADE_PASS_RE.search(content):
        issues.append(f"EMPTY downgrade (pass only): {filename}")
    return issues


def check_advisory_lock(content: str, filename: str) -> list[str]:
    """Check data migrations use advisory locks."""
    issues: list[str] = []
    if _DATA_DML_RE.search(content) and not _ADVISORY_LOCK_RE.search(content):
        issues.append(
            f"DATA migration without advisory lock: {filename}"
        )
    return issues


def scan_migrations(checkout: str, migrations_dir: str) -> list[str]:
    """Scan all migration files and return issues."""
    mig_path = os.path.join(checkout, migrations_dir)
    if not os.path.isdir(mig_path):
        return []
    all_issues: list[str] = []
    for fname in sorted(os.listdir(mig_path)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        path = os.path.join(mig_path, fname)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        all_issues.extend(check_reversibility(content, fname))
        all_issues.extend(check_advisory_lock(content, fname))
    return all_issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: migration_check.py <checkout> [migrations_dir]")
        return 2
    checkout = args[0]
    migrations_dir = args[1] if len(args) > 1 else "alembic/versions"
    issues = scan_migrations(checkout, migrations_dir)
    for issue in issues:
        print(issue)
    if issues:
        print(f"{len(issues)} migration issue(s) found")
        return 1
    print("all migrations pass lint checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
