"""Null usage parser — always returns zero metrics.

Used when a profile selects ``cli_id = "none"`` (the operator is
running without an LLM CLI, e.g. in dry-run or when verifying a
non-LLM gate). The contract guarantees that this parser never raises,
never reads from disk, and always returns the same all-zero
:class:`UsageMetrics`, regardless of input.

Callers depend on this constancy: it is safe to feed the null parser
into the same plumbing as the real ones, e.g. to test the cost
attribution helpers without a transcript fixture.
"""

from __future__ import annotations

from .types import UsageMetrics


PARSER_ID: str = "none"


def parse_usage(text: str) -> UsageMetrics:  # noqa: ARG001 — input ignored by contract
    """Return zero metrics regardless of ``text``."""

    return UsageMetrics()
