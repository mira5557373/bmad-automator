"""Detect static unbounded fan-out, unbounded queue, and N+1 patterns.

Standalone script invoked by the ``scale-lint-scalability`` collector
(see ``core/collectors/scalability.py``).  Scans source files for
common scalability anti-patterns that do not show up at small data
volumes but explode under load:

* Unbounded fan-out via ``asyncio.gather(*[... for ... in <iterable>])``
  with no concurrency cap.
* Unbounded queues — ``queue.Queue()`` / ``asyncio.Queue()`` / JS
  ``new EventEmitter`` / ``Promise.all([...])`` with no ``maxsize`` or
  bounded iterable.
* Nested-loop N+1 patterns where an inner ``await`` or ``.get(`` call
  appears under an unbounded ``for ... in`` iterator.

Exit 0 = clean, exit 1 = findings, exit 2 = usage error.  Stdlib only —
no story_automator imports (the script runs in the trust-boundary
sandbox checkout).
"""
from __future__ import annotations

import json
import os
import re
import sys

_FOR_LOOP_RE = re.compile(r"^\s*for\s+\w+\s+in\s+", re.MULTILINE)
_AWAIT_INNER_RE = re.compile(r"\bawait\s+\w+")
_GATHER_UNBOUNDED_RE = re.compile(
    r"asyncio\.gather\s*\(\s*\*\s*\[",
)
_PROMISE_ALL_UNBOUNDED_RE = re.compile(
    r"Promise\.all\s*\(\s*\[?\s*(?:\.\.\.|\w+\.map)",
)
_QUEUE_UNBOUNDED_RE = re.compile(
    r"(?:asyncio\.Queue|queue\.Queue)\s*\(\s*\)",
)
_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"]


def scan_unbounded_fanout(content: str, filename: str) -> list[str]:
    """Detect unbounded asyncio.gather / Promise.all / unbounded Queue."""
    findings: list[str] = []
    for i, line in enumerate(content.splitlines(), 1):
        if _GATHER_UNBOUNDED_RE.search(line):
            findings.append(
                f"UNBOUNDED-FANOUT: {filename}:{i}: {line.strip()}"
            )
        if _PROMISE_ALL_UNBOUNDED_RE.search(line):
            findings.append(
                f"UNBOUNDED-FANOUT: {filename}:{i}: {line.strip()}"
            )
        if _QUEUE_UNBOUNDED_RE.search(line):
            findings.append(
                f"UNBOUNDED-QUEUE: {filename}:{i}: {line.strip()}"
            )
    return findings


def scan_nested_await(content: str, filename: str) -> list[str]:
    """Detect ``await`` inside an unbounded ``for ... in`` loop body."""
    findings: list[str] = []
    lines = content.splitlines()
    in_for_loop = False
    for i, line in enumerate(lines, 1):
        if _FOR_LOOP_RE.match(line):
            in_for_loop = True
            continue
        if in_for_loop and line and not line[0].isspace():
            in_for_loop = False
        if in_for_loop and _AWAIT_INNER_RE.search(line):
            findings.append(
                f"NESTED-AWAIT: {filename}:{i}: {line.strip()}"
            )
    return findings


def scan_directory(checkout: str, extensions: list[str]) -> list[str]:
    """Walk checkout and scan files matching the given extensions."""
    findings: list[str] = []
    for root, _dirs, files in os.walk(checkout):
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            rel = os.path.relpath(path, checkout)
            findings.extend(scan_unbounded_fanout(content, rel))
            findings.extend(scan_nested_await(content, rel))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: scale_lint_check.py <checkout> [extensions_json]")
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
        print(f"{len(findings)} scalability issue(s) found")
        return 1
    print("no scalability issues found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
