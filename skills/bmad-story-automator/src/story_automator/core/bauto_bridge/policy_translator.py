"""Translate bmad-automator (bauto) policy TOML files to and from the
runtime's dict view.

Bauto ships its policy as a TOML file with a fixed set of top-level tables
(see ``KNOWN_BAUTO_TABLES``). The story-automator runtime consumes its
configuration as plain Python dictionaries. This module provides the two
directions of conversion plus a strict guardrail that rejects unknown
tables — bauto's table set is intentionally closed, and silently passing
unfamiliar tables through would let typos slip into production policy.

Read uses stdlib ``tomllib``. Write uses a minimal, dependency-free TOML
emitter that covers the subset bauto policy actually uses (scalars,
nested tables, and homogeneous arrays). We deliberately avoid pulling in
``tomlkit`` or any other third-party TOML writer to honor the runtime's
stdlib-only invariant.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

KNOWN_BAUTO_TABLES: tuple[str, ...] = (
    "scm",
    "review",
    "session",
    "ceilings",
    "drift",
    "policy",
    "trust",
    "calibration",
    "telemetry",
    "plugins",
    "test",
)

_KNOWN_SET = frozenset(KNOWN_BAUTO_TABLES)


class PolicyTranslationError(ValueError):
    """Raised when a bauto policy TOML cannot be translated to or from runtime."""


def policy_toml_to_runtime(toml_path: str | Path) -> dict[str, Any]:
    """Load a bauto policy TOML and return its runtime dict representation.

    Raises ``PolicyTranslationError`` on missing files, malformed TOML, or
    unknown top-level tables. Tables in ``KNOWN_BAUTO_TABLES`` that are absent
    from the source file are returned as empty dicts so downstream consumers
    can rely on the full key set.
    """
    path = Path(toml_path)
    if not path.is_file():
        raise PolicyTranslationError(f"policy TOML not found: {path}")
    try:
        with path.open("rb") as fh:
            parsed = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise PolicyTranslationError(f"invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise PolicyTranslationError(f"cannot read policy TOML {path}: {exc}") from exc

    _reject_unknown_tables(parsed)

    runtime: dict[str, Any] = {}
    for table in KNOWN_BAUTO_TABLES:
        value = parsed.get(table, {})
        if not isinstance(value, dict):
            raise PolicyTranslationError(
                f"table '{table}' must be a TOML table, got {type(value).__name__}"
            )
        runtime[table] = value
    return runtime


def runtime_to_policy_toml(runtime: dict[str, Any], out_path: str | Path) -> Path:
    """Serialize a runtime dict back to a bauto policy TOML file.

    Only the top-level tables listed in ``KNOWN_BAUTO_TABLES`` are permitted;
    anything else raises ``PolicyTranslationError`` so callers cannot smuggle
    out-of-band config through this bridge. Empty tables are skipped so the
    written file stays minimal.
    """
    if not isinstance(runtime, dict):
        raise PolicyTranslationError(
            f"runtime must be a dict, got {type(runtime).__name__}"
        )
    _reject_unknown_tables(runtime)

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    first = True
    for table in KNOWN_BAUTO_TABLES:
        if table not in runtime:
            continue
        value = runtime[table]
        if not isinstance(value, dict):
            raise PolicyTranslationError(
                f"table '{table}' must be a dict, got {type(value).__name__}"
            )
        if not value:
            continue
        if not first:
            lines.append("")
        first = False
        _emit_table(lines, [table], value)

    text = "\n".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _reject_unknown_tables(parsed: dict[str, Any]) -> None:
    unknown = sorted(k for k in parsed.keys() if k not in _KNOWN_SET)
    if unknown:
        raise PolicyTranslationError(
            "unknown bauto policy tables: " + ", ".join(unknown)
        )


def _emit_table(lines: list[str], path: list[str], table: dict[str, Any]) -> None:
    """Append TOML lines for ``table`` at the given header path.

    Scalars and arrays are emitted first under the current header, then nested
    sub-tables are emitted recursively. This matches the convention required
    by TOML so that following ``[a.b]`` headers do not silently reattach to a
    later parent table.
    """
    scalars: list[tuple[str, Any]] = []
    sub_tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in table.items():
        if isinstance(value, dict):
            sub_tables.append((key, value))
        else:
            scalars.append((key, value))

    lines.append("[" + ".".join(path) + "]")
    for key, value in scalars:
        lines.append(f"{_format_key(key)} = {_format_value(value)}")
    for key, sub in sub_tables:
        lines.append("")
        _emit_table(lines, path + [key], sub)


_BARE_KEY_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _format_key(key: str) -> str:
    if key and all(ch in _BARE_KEY_OK for ch in key):
        return key
    return _format_string(key)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            raise PolicyTranslationError("cannot encode NaN as TOML")
        if value in (float("inf"), float("-inf")):
            raise PolicyTranslationError("cannot encode infinity as TOML")
        return repr(value)
    if isinstance(value, str):
        return _format_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(v) for v in value) + "]"
    raise PolicyTranslationError(
        f"unsupported TOML value type: {type(value).__name__}"
    )


def _format_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"\"{escaped}\""
