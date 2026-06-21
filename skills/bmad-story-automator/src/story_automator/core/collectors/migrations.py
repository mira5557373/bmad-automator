"""Migrations-category evidence collectors (§6.2).

PASS rule: Alembic/Marabunta dry-run clean + reversible + advisory-lock correct.
Collectors: alembic-migrations, migration-lint-migrations.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _alembic_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("migrations") or {}
    revision = rules.get("alembic_revision", "head")
    return ["alembic", "upgrade", revision, "--sql"]


def _migration_lint_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("migrations") or {}
    migrations_dir = rules.get("migrations_dir", "alembic/versions")
    return [
        sys.executable,
        str(_CHECKS_DIR / "migration_check.py"),
        checkout,
        migrations_dir,
    ]


ALEMBIC = CollectorConfig(
    collector_id="alembic-migrations",
    tool="alembic",
    category="migrations",
    build_cmd=_alembic_cmd,
    tool_version_cmd=("alembic", "--version"),
    file_patterns=frozenset({"*.py", "*.sql"}),
)

MIGRATION_LINT = CollectorConfig(
    collector_id="migration-lint-migrations",
    tool="python3",
    category="migrations",
    build_cmd=_migration_lint_cmd,
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [ALEMBIC, MIGRATION_LINT]
