"""Claude Code JSONL transcript parser.

Claude Code stores per-session transcripts as newline-delimited JSON
under ``~/.claude/projects/<munged-cwd>/<session-id>.jsonl``. Each entry
is a dict; assistant + result entries carry a ``usage`` block with the
API-level token counts:

    {"input_tokens": ..., "output_tokens": ...,
     "cache_creation_input_tokens": ..., "cache_read_input_tokens": ...}

This parser is tolerant: malformed lines, missing keys, and unexpected
shapes are silently skipped. A transcript that yields no usage blocks
reads as :class:`UsageMetrics` zeros — same as a fully blank input.

Cost is computed from ``input_tokens`` + ``output_tokens`` using the
public Sonnet pricing as a reasonable baseline. Operators that need
opus-grade or other-tier rates should re-compute cost downstream from
the raw token counts rather than hard-coding alternate constants here.

Pricing constants (as of late 2025; revisit when Anthropic publishes a
new tier):

* ``INPUT_USD_PER_TOKEN = 3e-6`` — $3 / 1M input tokens (Sonnet)
* ``OUTPUT_USD_PER_TOKEN = 15e-6`` — $15 / 1M output tokens (Sonnet)
"""

from __future__ import annotations

import json
from typing import Any

from .types import UsageMetrics


PARSER_ID: str = "claude-jsonl"

# Pricing constants — Sonnet baseline. See module docstring.
INPUT_USD_PER_TOKEN: float = 3e-6
OUTPUT_USD_PER_TOKEN: float = 15e-6


def _coerce_int(value: Any) -> int:
    """Convert ``value`` to a non-negative int, returning 0 on failure."""

    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, result)


def _coerce_float(value: Any) -> float:
    """Convert ``value`` to a non-negative float, returning 0.0 on failure."""

    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result < 0:  # NaN or negative
        return 0.0
    return result


def _usage_block(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return the usage dict from a top-level or nested ``message`` entry."""

    message = entry.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    usage = entry.get("usage")
    if isinstance(usage, dict):
        return usage
    return None


def _is_tool_use_entry(entry: dict[str, Any]) -> bool:
    """Best-effort detection of a tool_use entry for the tool-call tally."""

    if entry.get("type") == "tool_use":
        return True
    message = entry.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_use":
                    return True
    return False


def parse_usage(text: str) -> UsageMetrics:
    """Parse a Claude Code JSONL transcript blob into :class:`UsageMetrics`.

    Returns zero-valued metrics for empty input, malformed JSON, or
    transcripts that carry no usage blocks. Multiple result/assistant
    entries with usage blocks are summed.
    """

    if not text:
        return UsageMetrics()

    input_tokens = 0
    output_tokens = 0
    tool_calls = 0
    duration_s = 0.0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        usage = _usage_block(entry)
        if usage is not None:
            input_tokens += _coerce_int(usage.get("input_tokens"))
            output_tokens += _coerce_int(usage.get("output_tokens"))

        if _is_tool_use_entry(entry):
            tool_calls += 1

        # Result entries occasionally carry a duration_ms field at the
        # top level. Use the largest seen as the session duration; we
        # don't sum because the field is cumulative, not per-event.
        candidate_ms = _coerce_float(entry.get("duration_ms"))
        if candidate_ms > 0:
            candidate_s = candidate_ms / 1000.0
            if candidate_s > duration_s:
                duration_s = candidate_s

    total_cost = (
        input_tokens * INPUT_USD_PER_TOKEN + output_tokens * OUTPUT_USD_PER_TOKEN
    )

    return UsageMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost_usd=total_cost,
        tool_calls_count=tool_calls,
        duration_s=duration_s,
    )
