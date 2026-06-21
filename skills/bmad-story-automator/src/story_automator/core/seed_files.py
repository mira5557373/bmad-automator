from __future__ import annotations

from pathlib import Path
from typing import Any

from .install_paths import install_path_for, mcp_seed_path_for

"""Seed the per-CLI install directories inside a fresh worktree.

The orchestrator hands a freshly-checked-out worktree path plus a CLI
profile to :func:`seed_worktree`. This module is responsible for
materialising the empty per-CLI directory skeleton (skill tree + MCP
servers seed) so downstream installers and collectors have a stable
target. It performs **no** file copies — that is the installer's job;
this module only guarantees the directory contract.
"""


class SeedFilesError(IOError):
    """Raised when worktree seeding cannot complete.

    Inherits from :class:`IOError` so callers may treat seeding failure
    interchangeably with other filesystem errors when bubbling up to the
    operator.
    """


def _resolve_cli_id(cli_profile: Any) -> str:
    cli_id = getattr(cli_profile, "cli_id", None)
    if cli_id is None and isinstance(cli_profile, dict):
        cli_id = cli_profile.get("cli_id")
    if not isinstance(cli_id, str) or not cli_id:
        raise SeedFilesError(
            "cli_profile must expose a non-empty 'cli_id' attribute or key",
        )
    return cli_id


def seed_worktree(worktree_path: str | Path, cli_profile: Any) -> None:
    """Create the per-CLI install skeleton inside ``worktree_path``.

    Creates the skill-tree directory and the MCP-seed directory required by
    ``cli_profile.cli_id``. The call is idempotent: re-running against an
    already-seeded worktree is a no-op rather than an error.

    Raises:
        SeedFilesError: when ``worktree_path`` does not exist, when the
            CLI id is unknown, or when the underlying mkdir fails for any
            other OS-level reason.
    """

    cli_id = _resolve_cli_id(cli_profile)

    root = Path(worktree_path)
    if not root.exists():
        raise SeedFilesError(f"worktree path does not exist: {root}")
    if not root.is_dir():
        raise SeedFilesError(f"worktree path is not a directory: {root}")

    try:
        skill_rel = install_path_for(cli_id)
        mcp_rel = mcp_seed_path_for(cli_id)
    except KeyError as exc:
        raise SeedFilesError(f"unknown cli_id: {cli_id}") from exc

    for relative in (skill_rel, mcp_rel):
        target = root / relative
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive
            raise SeedFilesError(f"failed to create {target}: {exc}") from exc
