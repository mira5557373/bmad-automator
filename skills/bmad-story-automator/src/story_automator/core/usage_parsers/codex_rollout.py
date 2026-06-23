"""Codex rollout transcript parser — stub.

OpenAI Codex CLI persists per-session rollouts under
``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``. A real implementation
should follow the convention documented in ``external/bmad-auto`` —
``token_count`` event payloads carry cumulative totals, so the last
event is the session total.

For now, this module is a deliberate stub: it returns zero-valued
:class:`UsageMetrics` so callers can wire the dispatch table without
crashing, while making explicit that Codex transcripts are not yet
attributed. A future milestone will replace the body with the real
parser.

The stub does not raise :class:`NotImplementedError`; it must compile,
import, and execute as a no-op so the dispatcher stays uniform.
"""

from __future__ import annotations

from .types import UsageMetrics


PARSER_ID: str = "codex-rollout"


def parse_usage(text: str) -> UsageMetrics:
    """Return zero metrics for ``text`` (stub).

    ``text`` is accepted but ignored. The signature matches the parser
    contract so callers can swap this for the real implementation
    without touching call sites.
    """

    del text  # explicit: stub ignores input
    return UsageMetrics()
