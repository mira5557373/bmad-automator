"""Shared types for the :mod:`story_automator.core.usage_parsers` package.

Kept in a separate module so all four parser implementations and the
package ``__init__`` can import the same dataclass + error class without
introducing a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass


class ParseError(ValueError):
    """Raised when :func:`get_parser` is asked for an unknown ``cli_id``.

    Individual parsers do *not* raise this for malformed transcript
    content — that path returns zero-valued :class:`UsageMetrics`. The
    error is reserved for registry-level lookup failures (a typo'd
    ``cli_id``, a profile pointing at a dialect we don't implement).
    """


@dataclass(frozen=True)
class UsageMetrics:
    """Token + cost + duration metrics extracted from one transcript.

    All fields are non-negative. ``total_cost_usd`` is the parser's best
    estimate at the time of parsing using the dialect's documented
    pricing constants; downstream code may re-compute cost from
    ``input_tokens`` / ``output_tokens`` if it has more accurate rates.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    tool_calls_count: int = 0
    duration_s: float = 0.0
