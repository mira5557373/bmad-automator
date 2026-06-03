#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def yaml_scalar(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?([^\"'\n]+)[\"']?\s*$", text, re.M)
    if not match:
        raise ValueError(f"missing YAML scalar: {key}")
    return match.group(1)


def workflow_frontmatter_version(text: str) -> str:
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        raise ValueError("missing workflow frontmatter")
    return yaml_scalar(match.group(1), "version")


def python_version(text: str, path: str) -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError(f"missing Python __version__ assignment: {path}")
    return match.group(1)


def main() -> int:
    package = read_json("package.json")
    plugin = read_json(".claude-plugin/plugin.json")
    marketplace = read_json(".claude-plugin/marketplace.json")
    pyproject = tomllib.loads(read_text("skills/bmad-story-automator/pyproject.toml"))
    init_text = read_text("skills/bmad-story-automator/src/story_automator/__init__.py")

    surfaces = {
        "package.json": package["version"],
        ".claude-plugin/plugin.json": plugin["version"],
        ".claude-plugin/marketplace.json": marketplace["plugins"][0]["version"],
        "skills/module.yaml": yaml_scalar(read_text("skills/module.yaml"), "module_version"),
        "skills/bmad-story-automator/pyproject.toml": pyproject["project"]["version"],
        "skills/bmad-story-automator/src/story_automator/__init__.py": python_version(
            init_text,
            "skills/bmad-story-automator/src/story_automator/__init__.py",
        ),
        "skills/bmad-story-automator/workflow.md": workflow_frontmatter_version(
            read_text("skills/bmad-story-automator/workflow.md")
        ),
    }

    expected = package["version"]
    mismatches = {
        path: version for path, version in surfaces.items() if version != expected
    }
    if mismatches:
        print(f"version alignment failed; expected {expected}", file=sys.stderr)
        for path, version in mismatches.items():
            print(f"- {path}: {version}", file=sys.stderr)
        return 1

    print(f"version alignment ok: {expected}")
    for path in sorted(surfaces):
        print(f"- {path}: {surfaces[path]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"version alignment failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
