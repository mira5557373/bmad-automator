"""Detect hard waits in test files (time.sleep, setTimeout, etc.).

Standalone script invoked by the hard-wait-test_quality collector.
Exit 0 = no hard waits, exit 1 = hard waits found, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_HARD_WAIT_PATTERNS = [
    (re.compile(r"\btime\.sleep\s*\("), "time.sleep"),
    (re.compile(r"\basyncio\.sleep\s*\("), "asyncio.sleep"),
    (re.compile(r"\bsetTimeout\s*\("), "setTimeout"),
    (re.compile(r"\bcy\.wait\s*\(\s*\d"), "cy.wait"),
    (re.compile(r"\bThread\.sleep\s*\("), "Thread.sleep"),
    (re.compile(r"\bpage\.waitForTimeout\s*\("), "page.waitForTimeout"),
]

_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "e2e"}
_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx"]


def scan_for_hard_waits(content: str, filename: str) -> list[str]:
    """Scan content for hard-wait patterns. Returns findings."""
    findings: list[str] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, label in _HARD_WAIT_PATTERNS:
            if pattern.search(line):
                findings.append(
                    f"HARD_WAIT: {filename}:{i}: {label}: {line.strip()}"
                )
    return findings


def scan_test_files(
    checkout: str, extensions: list[str],
) -> list[str]:
    """Walk checkout for test directories, scan matching files."""
    all_findings: list[str] = []
    for root, dirs, files in os.walk(checkout):
        rel_root = os.path.relpath(root, checkout)
        parts = set(rel_root.replace("\\", "/").split("/"))
        if not parts & _TEST_DIR_NAMES:
            continue
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            rel = os.path.relpath(path, checkout)
            all_findings.extend(scan_for_hard_waits(content, rel))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: hard_wait_check.py <checkout> [extensions_json]")
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
    findings = scan_test_files(checkout, extensions)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} hard wait(s) found in test files")
        return 1
    print("no hard waits found in test files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
