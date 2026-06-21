"""Validate agent tool pack-schema v1.2 envelope fields.

Standalone script invoked by the pack-schema-agentic collector.
Exit 0 = all valid, exit 1 = missing/invalid fields, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_REQUIRED_FIELDS = ("risk_tier", "reversibility_class", "time_lock", "autonomy")
_TOOL_SUFFIX = ".tool.json"


def find_tool_definitions(
    checkout: str, tools_dir: str,
) -> list[dict]:
    """Find and load tool definition files."""
    path = os.path.join(checkout, tools_dir)
    if not os.path.isdir(path):
        return []
    defs: list[dict] = []
    for root, _dirs, files in os.walk(path):
        for fname in sorted(files):
            if not fname.endswith(_TOOL_SUFFIX):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data["_source_file"] = os.path.relpath(fpath, checkout)
                    defs.append(data)
            except (OSError, json.JSONDecodeError):
                continue
    return defs


def validate_pack_schema(tool_def: dict) -> list[str]:
    """Validate a tool definition has required pack-schema v1.2 fields."""
    issues: list[str] = []
    name = tool_def.get("name", tool_def.get("_source_file", "unknown"))
    for field in _REQUIRED_FIELDS:
        value = tool_def.get(field)
        if not value or not isinstance(value, str) or not value.strip():
            issues.append(f"{name}: missing or empty field '{field}'")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: pack_schema_check.py <checkout> [tools_dir]")
        return 2
    checkout = args[0]
    tools_dir = args[1] if len(args) > 1 else "tools"
    defs = find_tool_definitions(checkout, tools_dir)
    if not defs:
        print("no tool definitions found — pack-schema N/A")
        return 0
    all_issues: list[str] = []
    for tool_def in defs:
        all_issues.extend(validate_pack_schema(tool_def))
    for issue in all_issues:
        print(issue)
    if all_issues:
        print(f"{len(all_issues)} pack-schema violation(s)")
        return 1
    print(f"{len(defs)} tool definition(s) validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
