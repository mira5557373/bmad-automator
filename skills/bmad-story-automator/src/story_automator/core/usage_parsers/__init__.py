"""Usage parsers — CLI transcript parsers that extract token + cost metrics.

Each parser implements a uniform contract:

* a module-level ``PARSER_ID: str`` naming the dialect ("claude-jsonl",
  "codex-rollout", "gemini-chat", or "none");
* a function ``parse_usage(text: str) -> UsageMetrics`` that consumes a
  transcript blob and returns a :class:`UsageMetrics` instance. Parsers
  are tolerant — malformed lines are skipped, never raised — so a fully
  unparseable input reads as :class:`UsageMetrics` zeros, not an error.

The registry — :func:`get_parser` and :data:`KNOWN_PARSERS` — maps a
``cli_id`` (the same identifier used by ``cli_dispatcher`` and the
profile composer) to the parser callable for that dialect. Unknown
``cli_id`` values raise :class:`ParseError`.

This package is intentionally stdlib-only and has no dependency on the
gate orchestrator: callers wire parser output into cost attribution
(:mod:`story_automator.core.innovation.cost_attribution`) themselves.
"""

from __future__ import annotations

from collections.abc import Callable

from .claude_jsonl import (
    PARSER_ID as CLAUDE_JSONL_PARSER_ID,
    parse_usage as parse_claude_jsonl,
)
from .codex_rollout import (
    PARSER_ID as CODEX_ROLLOUT_PARSER_ID,
    parse_usage as parse_codex_rollout,
)
from .gemini_chat import (
    PARSER_ID as GEMINI_CHAT_PARSER_ID,
    parse_usage as parse_gemini_chat,
)
from .none import (
    PARSER_ID as NONE_PARSER_ID,
    parse_usage as parse_none,
)
from .types import ParseError, UsageMetrics


__all__ = [
    "UsageMetrics",
    "ParseError",
    "KNOWN_PARSERS",
    "get_parser",
    "parse_claude_jsonl",
    "parse_codex_rollout",
    "parse_gemini_chat",
    "parse_none",
]


# Closed registry: cli_id -> PARSER_ID. The set of keys is the
# authoritative list of recognized cli_id values across the project;
# anything else raises ParseError from :func:`get_parser`.
KNOWN_PARSERS: dict[str, str] = {
    "claude-code": CLAUDE_JSONL_PARSER_ID,
    "codex": CODEX_ROLLOUT_PARSER_ID,
    "gemini-cli": GEMINI_CHAT_PARSER_ID,
    "none": NONE_PARSER_ID,
}


_PARSER_DISPATCH: dict[str, Callable[[str], UsageMetrics]] = {
    "claude-code": parse_claude_jsonl,
    "codex": parse_codex_rollout,
    "gemini-cli": parse_gemini_chat,
    "none": parse_none,
}


def get_parser(cli_id: str) -> Callable[[str], UsageMetrics]:
    """Return the usage parser callable for ``cli_id``.

    Raises :class:`ParseError` if ``cli_id`` is not a recognized key in
    :data:`KNOWN_PARSERS`. The returned callable accepts a transcript
    string and returns a :class:`UsageMetrics`.
    """

    try:
        return _PARSER_DISPATCH[cli_id]
    except KeyError as exc:
        known = ", ".join(sorted(KNOWN_PARSERS))
        raise ParseError(
            f"unknown cli_id {cli_id!r}; known cli_ids: {known}"
        ) from exc
