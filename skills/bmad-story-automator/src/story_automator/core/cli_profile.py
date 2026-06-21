"""Declarative CLI profile schema for the multi-CLI tmux runtime.

A :class:`CLIProfile` captures the surface differences between coding CLIs
(Claude Code, Codex, Gemini CLI) that share the tmux-injection + hook-signal
transport: the binary name, how the canonical prompt string is rendered, the
flags that bypass permission prompts, which hook dialect the CLI writes, the
canonical event-name map, and where in a project tree skills and MCP seeds
live.

This milestone (M32) intentionally only ships the schema, the TOML loader, and
a back-compat :func:`claude_default` for the existing tmux runtime. Refactoring
``tmux_runtime.py`` to consume profiles is deferred to M42.

Mirrors the contract in ``external/bmad-auto/src/automator/adapters/profile.py``
but uses the flatter dataclass shape requested by the integration spec.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

KNOWN_CLI_IDS: tuple[str, ...] = ("claude-code", "codex", "gemini-cli")
KNOWN_HOOK_DIALECTS: tuple[str, ...] = ("claude", "codex", "gemini", "none")

_REQUIRED_FIELDS: tuple[str, ...] = (
    "cli_id",
    "binary",
    "prompt_template",
    "hook_dialect",
    "skill_tree_dir",
)


class CLIProfileError(ValueError):
    """Raised when a CLI profile fails to load or validate."""


@dataclass(frozen=True)
class CLIProfile:
    """Schema describing one coding-CLI driver target.

    Field semantics:
      * ``cli_id`` — short identifier, one of :data:`KNOWN_CLI_IDS`.
      * ``binary`` — executable name to launch (e.g. ``"claude"``).
      * ``prompt_template`` — format string with ``{prompt}`` placeholder used
        to render the canonical ``"/skill args"`` prompt for this CLI.
      * ``bypass_flags`` — flags appended to bypass permission prompts.
      * ``hook_dialect`` — which hook config dialect the CLI uses, one of
        :data:`KNOWN_HOOK_DIALECTS` (``"none"`` for CLIs without hooks).
      * ``canonical_event_map`` — native-event -> canonical-event mapping; the
        canonical names are decided by the engine, not the CLI.
      * ``skill_tree_dir`` — project-relative directory where this CLI reads
        skills from (e.g. ``".claude/skills"`` / ``".agents/skills"`` /
        ``".gemini/skills"``).
      * ``mcp_seed_files`` — project-relative gitignored configs that a fresh
        ``git worktree`` checkout omits; the orchestrator copies them in so
        isolated sessions can reach the MCP server.
    """

    cli_id: str
    binary: str
    prompt_template: str
    bypass_flags: tuple[str, ...]
    hook_dialect: str
    canonical_event_map: Mapping[str, str]
    skill_tree_dir: str
    mcp_seed_files: tuple[str, ...] = field(default_factory=tuple)


def _fail(source: str, msg: str) -> CLIProfileError:
    return CLIProfileError(f"cli profile {source}: {msg}")


def _coerce_str_tuple(value: object, source: str, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _fail(source, f"{field_name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _fail(source, f"{field_name} entries must be strings")
        result.append(item)
    return tuple(result)


def _coerce_event_map(value: object, source: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _fail(source, "canonical_event_map must be a table")
    out: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise _fail(source, "canonical_event_map keys and values must be strings")
        out[key] = val
    return out


def _validate_relative(path_str: str, source: str, field_name: str) -> None:
    if not path_str:
        raise _fail(source, f"{field_name} must not be empty")
    if Path(path_str).is_absolute():
        raise _fail(source, f"{field_name} must be a project-relative path")


def _parse_profile(doc: dict[str, object], source: str) -> CLIProfile:
    for required in _REQUIRED_FIELDS:
        if required not in doc:
            raise _fail(source, f"missing required field {required!r}")

    cli_id = doc.get("cli_id")
    binary = doc.get("binary")
    prompt_template = doc.get("prompt_template")
    hook_dialect = doc.get("hook_dialect")
    skill_tree_dir = doc.get("skill_tree_dir")

    if not isinstance(cli_id, str) or not cli_id.strip():
        raise _fail(source, "cli_id must be a non-empty string")
    if cli_id not in KNOWN_CLI_IDS:
        raise _fail(
            source,
            f"cli_id must be one of {list(KNOWN_CLI_IDS)}: got {cli_id!r}",
        )
    if not isinstance(binary, str) or not binary.strip():
        raise _fail(source, "binary must be a non-empty string")
    if not isinstance(prompt_template, str) or not prompt_template:
        raise _fail(source, "prompt_template must be a non-empty string")
    if not isinstance(hook_dialect, str) or hook_dialect not in KNOWN_HOOK_DIALECTS:
        raise _fail(
            source,
            f"hook_dialect must be one of {list(KNOWN_HOOK_DIALECTS)}: got "
            f"{hook_dialect!r}",
        )
    if not isinstance(skill_tree_dir, str):
        raise _fail(source, "skill_tree_dir must be a string")
    _validate_relative(skill_tree_dir, source, "skill_tree_dir")

    bypass_flags = _coerce_str_tuple(doc.get("bypass_flags"), source, "bypass_flags")
    mcp_seed_files = _coerce_str_tuple(
        doc.get("mcp_seed_files"), source, "mcp_seed_files"
    )
    for seed in mcp_seed_files:
        _validate_relative(seed, source, "mcp_seed_files entry")

    event_map = _coerce_event_map(doc.get("canonical_event_map"), source)

    return CLIProfile(
        cli_id=cli_id,
        binary=binary,
        prompt_template=prompt_template,
        bypass_flags=bypass_flags,
        hook_dialect=hook_dialect,
        canonical_event_map=MappingProxyType(event_map),
        skill_tree_dir=skill_tree_dir,
        mcp_seed_files=mcp_seed_files,
    )


def load_cli_profile(path: str | Path) -> CLIProfile:
    """Load a :class:`CLIProfile` from a TOML file.

    Validation is strict — unknown ``cli_id`` or ``hook_dialect`` values are
    rejected, missing required fields raise, and absolute paths in
    ``skill_tree_dir`` / ``mcp_seed_files`` are rejected so a malicious profile
    can't escape the project root.
    """

    path_obj = Path(path)
    source = str(path_obj)
    try:
        raw = path_obj.read_bytes()
    except FileNotFoundError as exc:
        raise CLIProfileError(f"cli profile {source}: file not found") from exc
    except OSError as exc:
        raise CLIProfileError(f"cli profile {source}: cannot read: {exc}") from exc
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CLIProfileError(f"cli profile {source}: invalid TOML: {exc}") from exc
    return _parse_profile(doc, source)


def claude_default() -> CLIProfile:
    """Back-compat default profile for the existing Claude tmux runtime.

    Reproduces the hard-coded launch shape currently in
    :mod:`story_automator.core.tmux_runtime` so future callers can drop the
    inline string in favour of the profile without behaviour change. This is
    deliberately *not* called from ``tmux_runtime`` in this milestone — that
    integration is M42.
    """

    return CLIProfile(
        cli_id="claude-code",
        binary="claude",
        prompt_template="{prompt}",
        bypass_flags=("--dangerously-skip-permissions",),
        hook_dialect="claude",
        canonical_event_map=MappingProxyType(
            {
                "SessionStart": "session_start",
                "Stop": "stop",
                "SessionEnd": "session_end",
                "PreCompact": "pre_compact",
            }
        ),
        skill_tree_dir=".claude/skills",
        mcp_seed_files=(".claude/settings.json", ".mcp.json"),
    )
