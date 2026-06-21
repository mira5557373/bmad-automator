"""Docs-category evidence collectors (§6.2).

PASS rule: docs site builds; API docs generated; runbook present.
Collectors: api-docs-docs, doc-presence-docs, docusaurus-docs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_REQUIRED_DOC_FILES = [
    "docs/operations/gate-troubleshooting.md",
]

_REQUIRED_API_DOC_FILES = [
    "docs/api/index.md",
]


def _doc_presence_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(_REQUIRED_DOC_FILES),
    ]


def _api_docs_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(_REQUIRED_API_DOC_FILES),
    ]


def _docusaurus_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "docusaurus", "build"]


API_DOCS = CollectorConfig(
    collector_id="api-docs-docs",
    tool="python3",
    category="docs",
    build_cmd=_api_docs_cmd,
    file_patterns=frozenset({"*.md", "*.html"}),
)

DOC_PRESENCE = CollectorConfig(
    collector_id="doc-presence-docs",
    tool="python3",
    category="docs",
    build_cmd=_doc_presence_cmd,
    file_patterns=frozenset({"*.md", "*.mdx"}),
)

DOCUSAURUS = CollectorConfig(
    collector_id="docusaurus-docs",
    tool="docusaurus",
    category="docs",
    build_cmd=_docusaurus_cmd,
    tool_version_cmd=("npx", "docusaurus", "--version"),
    file_patterns=frozenset({"*.md", "*.mdx", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [API_DOCS, DOC_PRESENCE, DOCUSAURUS]
