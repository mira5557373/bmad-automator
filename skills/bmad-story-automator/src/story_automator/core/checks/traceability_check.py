"""Check AC-to-test traceability coverage against thresholds.

Standalone script invoked by the trace-traceability collector.
Reads TEA e2e-trace-summary.json when present, falls back to
GWT title parse over story files. Validates per-priority coverage.
Exit 0 = thresholds met, exit 1 = violations, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_AC_RE = re.compile(
    r"^-\s+(\S+)\s+\[(\w+)\]:\s*(.*)", re.MULTILINE,
)
_GWT_RE = re.compile(
    r"def\s+test_given_\w+_when_\w+_then_\w+", re.MULTILINE,
)
_STORY_RELDIR = os.path.join("_bmad", "stories")
_TEA_DEFAULT = os.path.join("_bmad", "gate", "tea", "e2e-trace-summary.json")


def read_tea_trace(path: str) -> list[dict]:
    """Read TEA e2e-trace-summary.json. Returns [] on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    traces = data.get("traces")
    if not isinstance(traces, list):
        return []
    return [t for t in traces if isinstance(t, dict) and "ac_id" in t]


def gwt_fallback(checkout: str) -> list[dict]:
    """Parse stories for ACs, scan tests for GWT patterns, compute mapping."""
    story_dir = os.path.join(checkout, _STORY_RELDIR)
    if not os.path.isdir(story_dir):
        return []
    acs: list[dict] = []
    for fname in sorted(os.listdir(story_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(story_dir, fname)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        for match in _AC_RE.finditer(content):
            acs.append({
                "ac_id": match.group(1),
                "priority": match.group(2),
                "description": match.group(3).strip(),
                "status": "unmapped",
                "source": fname,
            })
    if not acs:
        return []
    test_tokens: list[set[str]] = []
    tests_dir = os.path.join(checkout, "tests")
    if os.path.isdir(tests_dir):
        for root, _dirs, files in os.walk(tests_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(root, fname)
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for match in _GWT_RE.finditer(content):
                    tokens = set(match.group(0).lower().replace("_", " ").split())
                    test_tokens.append(tokens)
    for ac in acs:
        ac_words = set(ac.get("description", "").lower().split())
        for tokens in test_tokens:
            if len(ac_words & tokens) >= 2:
                ac["status"] = "mapped"
                break
    return acs


def compute_coverage(
    traces: list[dict],
    thresholds: dict[str, int],
) -> tuple[bool, list[str]]:
    """Compute per-priority coverage. Returns (ok, issues)."""
    if not traces:
        return True, []
    by_priority: dict[str, list[dict]] = {}
    for t in traces:
        pri = t.get("priority", "")
        by_priority.setdefault(pri, []).append(t)
    issues: list[str] = []
    for pri, threshold in thresholds.items():
        group = by_priority.get(pri, [])
        if not group:
            continue
        mapped = sum(1 for t in group if t.get("status") == "mapped")
        total = len(group)
        pct = (mapped * 100) // total if total > 0 else 100
        if pct < threshold:
            issues.append(
                f"{pri}: {mapped}/{total} ({pct}%) mapped, "
                f"required {threshold}%"
            )
    return len(issues) == 0, issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: traceability_check.py <checkout> <thresholds_json> [tea_trace_path]")
        return 2
    checkout = args[0]
    try:
        thresholds: dict[str, int] = json.loads(args[1])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid thresholds: {args[1]}")
        return 2
    tea_path = args[2] if len(args) > 2 else os.path.join(checkout, _TEA_DEFAULT)
    traces = read_tea_trace(tea_path)
    if not traces:
        print("TEA trace not found, using GWT fallback")
        traces = gwt_fallback(checkout)
    if not traces:
        print("no ACs found — traceability N/A")
        return 0
    ok, issues = compute_coverage(traces, thresholds)
    for issue in issues:
        print(issue)
    if not ok:
        print(f"{len(issues)} traceability threshold(s) not met")
        return 1
    mapped = sum(1 for t in traces if t.get("status") == "mapped")
    print(f"{mapped}/{len(traces)} ACs mapped — all thresholds met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
