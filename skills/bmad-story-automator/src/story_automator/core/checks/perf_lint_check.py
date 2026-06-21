"""Detect static N+1 and unbounded query patterns.

Standalone script invoked by the perf-lint-performance collector.
Scans source files for common performance anti-patterns.
Exit 0 = clean, exit 1 = findings, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_FOR_LOOP_RE = re.compile(r"^\s*for\s+\w+\s+in\s+", re.MULTILINE)
_LAZY_LOAD_RE = re.compile(r"\.\w+\.(all|filter|get)\s*\(")
_SELECT_STAR_RE = re.compile(
    r"""(?:execute|text)\s*\(\s*['"]SELECT\s+(?!\s*COUNT)\S+.*?FROM""",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_FIND_ALL_RE = re.compile(r"\.find_all\s*\(\s*\)")

_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx"]


def scan_for_n_plus_one(content: str, filename: str) -> list[str]:
    """Detect lazy-load attribute access inside for loops."""
    findings: list[str] = []
    lines = content.splitlines()
    in_for_loop = False
    for i, line in enumerate(lines, 1):
        if _FOR_LOOP_RE.match(line):
            in_for_loop = True
            continue
        if in_for_loop and line and not line[0].isspace():
            in_for_loop = False
        if in_for_loop and _LAZY_LOAD_RE.search(line):
            findings.append(f"N+1: {filename}:{i}: {line.strip()}")
    return findings


def scan_for_unbounded(content: str, filename: str) -> list[str]:
    """Detect SELECT without LIMIT and find_all() calls."""
    findings: list[str] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        if _SELECT_STAR_RE.search(line) and not _LIMIT_RE.search(line):
            findings.append(f"UNBOUNDED query: {filename}:{i}: {line.strip()}")
        if _FIND_ALL_RE.search(line):
            findings.append(f"UNBOUNDED find_all(): {filename}:{i}: {line.strip()}")
    return findings


def scan_directory(checkout: str, extensions: list[str]) -> list[str]:
    """Walk checkout and scan files matching extensions."""
    all_findings: list[str] = []
    for root, _dirs, files in os.walk(checkout):
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            rel = os.path.relpath(path, checkout)
            all_findings.extend(scan_for_n_plus_one(content, rel))
            all_findings.extend(scan_for_unbounded(content, rel))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: perf_lint_check.py <checkout> [extensions_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            extensions: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid extensions: {args[1]}")
            return 2
    else:
        extensions = _DEFAULT_EXTENSIONS
    findings = scan_directory(checkout, extensions)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} performance issue(s) found")
        return 1
    print("no performance issues found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
