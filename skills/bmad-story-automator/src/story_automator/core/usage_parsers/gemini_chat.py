"""Gemini chat transcript parser — stub.

Gemini CLI writes per-session chat logs under
``~/.gemini/tmp/<project>/chats/session-*.jsonl`` as a JSONL patch
stream. A real implementation should follow the convention in
``external/bmad-auto/src/automator/tokens.py``: bare message entries
and messages inside ``$set`` patches carry a per-API-call ``tokens``
block; the last occurrence per message id wins.

For now, this module is a deliberate stub: it returns zero-valued
:class:`UsageMetrics` so the dispatcher can be wired uniformly even
though Gemini transcripts are not yet attributed. A future milestone
will replace the body with the real parser.

The stub does not raise :class:`NotImplementedError`; it must compile,
import, and execute as a no-op so the dispatcher stays uniform.
"""

from __future__ import annotations

from .types import UsageMetrics


PARSER_ID: str = "gemini-chat"


def parse_usage(text: str) -> UsageMetrics:
    """Return zero metrics for ``text`` (stub).

    ``text`` is accepted but ignored. The signature matches the parser
    contract so callers can swap this for the real implementation
    without touching call sites.
    """

    del text  # explicit: stub ignores input
    return UsageMetrics()
