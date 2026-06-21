from __future__ import annotations

from pathlib import Path

"""Per-CLI install paths for the BMAD story-automator skill bundle.

Each supported CLI host installs skills and MCP server seeds into a
deterministic subdirectory of the project worktree. The maps below are
the single source of truth used by the installer, the worktree seeder
(:mod:`seed_files`), and any compatibility shims that need to know
"where does CLI X expect skill Y to live?".

Both maps share the same key set so a caller that has already validated a
``cli_id`` against one map may rely on the other map containing the same
key. Use :func:`install_path_for` / :func:`mcp_seed_path_for` for direct
lookup with a strict :class:`KeyError` on unknown ids.
"""

SKILL_TREE_DIRS: dict[str, str] = {
    "claude-code": ".claude/skills",
    "codex": ".agents/skills",
    "gemini-cli": ".gemini/skills",
}

MCP_SEED_DIRS: dict[str, str] = {
    "claude-code": ".claude/mcp_servers",
    "codex": ".agents/mcp_servers",
    "gemini-cli": ".gemini/mcp_servers",
}


def install_path_for(cli_id: str) -> Path:
    """Return the skill-tree directory (relative path) for ``cli_id``.

    Raises:
        KeyError: when ``cli_id`` is not a known CLI host.
    """

    return Path(SKILL_TREE_DIRS[cli_id])


def mcp_seed_path_for(cli_id: str) -> Path:
    """Return the MCP-seed directory (relative path) for ``cli_id``.

    Raises:
        KeyError: when ``cli_id`` is not a known CLI host.
    """

    return Path(MCP_SEED_DIRS[cli_id])
