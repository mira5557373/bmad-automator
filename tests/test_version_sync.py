"""R14: keep the six hand-maintained version surfaces in lock-step.

The release flow (docs/versioning.md) requires bumping six files by hand with
no automated guard, inviting silent drift. This test cross-checks them so a
forgotten file fails CI instead of shipping inconsistent reported versions.
"""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _json_version(rel: str, *keys: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in keys:
        if isinstance(data, list):
            data = data[key] if isinstance(key, int) else None
        elif isinstance(data, dict):
            data = data.get(key)
        if data is None:
            return None
    return data


def _regex_version(rel: str, pattern: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _toml_version(rel: str):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("version")


def _marketplace_version() -> str | None:
    path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if isinstance(plugins, list) and plugins and isinstance(plugins[0], dict):
        return plugins[0].get("version")
    return None


class VersionSyncTests(unittest.TestCase):
    def test_all_version_surfaces_agree(self) -> None:
        surfaces = {
            "package.json": _json_version("package.json", "version"),
            ".claude-plugin/plugin.json": _json_version(".claude-plugin/plugin.json", "version"),
            ".claude-plugin/marketplace.json": _marketplace_version(),
            "skills/module.yaml": _regex_version("skills/module.yaml", r'module_version:\s*"?([0-9][^"\s]*)"?'),
            "pyproject.toml": _toml_version("skills/bmad-story-automator/pyproject.toml"),
            "__init__.py": _regex_version(
                "skills/bmad-story-automator/src/story_automator/__init__.py",
                r'__version__\s*=\s*"([^"]+)"',
            ),
        }
        missing = [name for name, value in surfaces.items() if value is None]
        if missing:
            self.skipTest(f"version surfaces not found (not running from repo root?): {missing}")
        distinct = set(surfaces.values())
        self.assertEqual(
            len(distinct),
            1,
            f"version surfaces drifted: {json.dumps(surfaces, indent=2)}",
        )


if __name__ == "__main__":
    unittest.main()
