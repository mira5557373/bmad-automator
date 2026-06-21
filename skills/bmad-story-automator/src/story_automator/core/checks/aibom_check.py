"""Validate AIBOM entries for agent tools.

Standalone script invoked by the aibom-diff-agentic collector.
Exit 0 = all covered, exit 1 = missing entries, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_AIBOM_DEFAULT = os.path.join("aibom", "aibom.json")
_TOOL_SUFFIX = ".tool.json"


def load_aibom(path: str) -> dict:
    """Load AIBOM JSON. Returns {} on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def find_tool_names(checkout: str) -> set[str]:
    """Find tool names from *.tool.json files."""
    tools_dir = os.path.join(checkout, "tools")
    if not os.path.isdir(tools_dir):
        return set()
    names: set[str] = set()
    for root, _dirs, files in os.walk(tools_dir):
        for fname in files:
            if not fname.endswith(_TOOL_SUFFIX):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("name"):
                    names.add(data["name"])
            except (OSError, json.JSONDecodeError):
                continue
    return names


def check_aibom_coverage(
    tools: set[str], aibom: dict,
) -> list[str]:
    """Check that all tool names have AIBOM entries."""
    if not tools:
        return []
    components = aibom.get("components") or []
    covered = {
        c.get("name") for c in components
        if isinstance(c, dict) and c.get("name")
    }
    issues: list[str] = []
    for tool_name in sorted(tools):
        if tool_name not in covered:
            issues.append(f"MISSING AIBOM entry: {tool_name}")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: aibom_check.py <checkout> [aibom_path]")
        return 2
    checkout = args[0]
    aibom_path = args[1] if len(args) > 1 else os.path.join(checkout, _AIBOM_DEFAULT)
    tools = find_tool_names(checkout)
    if not tools:
        print("no tool definitions found — AIBOM check N/A")
        return 0
    aibom = load_aibom(aibom_path)
    issues = check_aibom_coverage(tools, aibom)
    for issue in issues:
        print(issue)
    if issues:
        print(f"{len(issues)} tool(s) missing AIBOM entries")
        return 1
    print(f"all {len(tools)} tool(s) have AIBOM entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
