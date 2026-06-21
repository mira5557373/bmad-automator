"""Detect hard-coded waits in test files.

Standalone script invoked by the hard-wait-test-quality collector.
Scans test files for sleep/wait anti-patterns across Python and JS/TS.
Exit 0 = clean, exit 1 = findings, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_PYTHON_PATTERNS = [
    re.compile(r"time\.sleep\s*\("),
    re.compile(r"asyncio\.sleep\s*\("),
]

_JS_PATTERNS = [
    re.compile(r"setTimeout\s*\("),
    re.compile(r"\.waitForTimeout\s*\("),
    re.compile(r"cy\.wait\s*\("),
    re.compile(r"browser\.pause\s*\("),
    re.compile(r"await\s+sleep\s*\("),
]

_NOQA_RE = re.compile(r"#\s*noqa:\s*burn-in|//\s*noqa:\s*burn-in")

_TEST_FILE_PATTERNS = [
    re.compile(r"^test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r".*\.test\.[jt]sx?$"),
    re.compile(r".*\.spec\.[jt]sx?$"),
    re.compile(r"^test_.*\.[jt]sx?$"),
]

_PY_EXT = frozenset({".py"})
_JS_EXT = frozenset({".js", ".jsx", ".ts", ".tsx"})


def _is_test_file(filename: str) -> bool:
    return any(pat.match(filename) for pat in _TEST_FILE_PATTERNS)


def _get_patterns(ext: str) -> list[re.Pattern[str]]:
    if ext in _PY_EXT:
        return _PYTHON_PATTERNS
    if ext in _JS_EXT:
        return _JS_PATTERNS
    return []


def scan_file(filepath: str, checkout: str) -> list[str]:
    """Scan a single file for hard-wait patterns."""
    _, ext = os.path.splitext(filepath)
    patterns = _get_patterns(ext)
    if not patterns:
        return []
    findings: list[str] = []
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if _NOQA_RE.search(line):
                continue
            for pat in patterns:
                if pat.search(line):
                    rel = os.path.relpath(filepath, checkout)
                    findings.append(
                        f"HARD_WAIT: {rel}:{lineno}: {line.strip()}"
                    )
                    break
    return findings


def scan_directory(checkout: str) -> list[str]:
    """Walk checkout and scan test files for hard-wait patterns."""
    all_findings: list[str] = []
    for root, dirs, files in os.walk(checkout):
        dirs.sort()
        for fname in sorted(files):
            if not _is_test_file(fname):
                continue
            path = os.path.join(root, fname)
            all_findings.extend(scan_file(path, checkout))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: hard_wait_check.py <checkout>")
        return 2
    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2
    findings = scan_directory(checkout)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} hard-wait(s) found")
        return 1
    print("no hard-waits found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
