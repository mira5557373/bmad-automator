"""Layer 2 of the M06a trust-but-verify stack: spec compliance via `claude -p`.

This module exposes two frozen dataclasses (`ReqVerdict`,
`ComplianceReport`), one exception (`ComplianceError`), and one
entry-point function (`check_compliance`). `check_compliance` spawns
`claude -p` via `subprocess.run` (list args, never `shell=True`),
injects the spec text and diff text into the prompt as fenced code
blocks, and returns a `ComplianceReport` whose per-REQ verdict
classifies each requirement as `"implemented"`, `"missing"`, or
`"partial"`.

Layer 2 is intentionally decoupled from Layer 1 (`gap_validator.py`) and
Layer 3 (`feature_tester.py`): no cross-layer imports, no shared state,
no HTTP/MCP/API clients. The only external boundary is the single
subprocess invocation. The child process inherits a clean environment
overlay that pins `LANG=C.UTF-8` for deterministic locale.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

# Names below are populated by subsequent M06a-M2 tasks (T2-T7); ruff F822
# flags them as undefined here, but plain `import` works because `__all__` is
# only consulted by `from module import *`. Suppress the diagnostic with
# rationale until later tasks define the symbols.
__all__ = [  # noqa: F822
    "ComplianceError",
    "ComplianceReport",
    "ReqVerdict",
    "check_compliance",
]

logger = logging.getLogger(__name__)


class ComplianceError(Exception):
    """Raised when `check_compliance` cannot return a meaningful report.

    Preconditions: caller supplies a single human-readable message.
    Postconditions: instance is a plain `Exception` carrying the message.
    Raises: nothing — this is the exception type itself.

    Raised by `check_compliance` when:
      - the `claude -p` subprocess exits non-zero
      - the subprocess times out (TimeoutExpired)
      - the subprocess stdout cannot be parsed as the expected JSON envelope

    The function MUST NOT silently downgrade a parse failure into a
    `"missing"` verdict — REQ-10 forbids that.
    """


@dataclass(frozen=True, kw_only=True)
class ReqVerdict:
    """Verdict for one REQ from the spec compared against the diff.

    Preconditions: `req_id` is a non-empty string (e.g. "REQ-07");
        `status` is exactly one of "implemented", "missing", "partial";
        `evidence` is a human-readable string (may be empty);
        `confidence` lies in `[0.0, 1.0]`. The dataclass itself does not
        enforce these constraints — `_parse_envelope` (Task 7) does so
        before constructing instances.
    Postconditions: instance is frozen; all four fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    req_id: str
    status: Literal["implemented", "missing", "partial"]
    evidence: str
    confidence: float


@dataclass(frozen=True, kw_only=True)
class ComplianceReport:
    """Aggregate report from `check_compliance`.

    Preconditions: `verdicts` is a list (possibly empty); `spec_path` is
        the string form of the spec file path (typically the resolved
        absolute path); `diff_sha` is the SHA-256 hex digest of the diff
        text passed to `check_compliance`; `model_invocation_ms` is a
        non-negative integer reported by the subprocess.
    Postconditions: instance is frozen. Note: `frozen=True` does not
        deep-freeze `verdicts` — callers must treat it as read-only.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    verdicts: list[ReqVerdict]
    spec_path: str
    diff_sha: str
    model_invocation_ms: int


_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"\{\{([A-Z]{4})\}\}")


def _escape_placeholders(spec_text: str) -> str:
    """Replace four-letter uppercase `{{XXXX}}` tokens with `{{ESC:XXXX}}`.

    REQ-11: unresolved four-letter placeholder tokens in the spec must
    be escaped so the subprocess does not treat them as template
    directives intended for human authoring.
    """
    return _PLACEHOLDER_RE.sub(r"{{ESC:\1}}", spec_text)


_PROMPT_HEADER: str = (
    "You are verifying spec compliance. Compare the diff against the listed "
    "REQ-NN requirements in the spec. Output ONLY a single raw JSON object — "
    "no markdown fences, no preamble, no trailing prose — of shape: "
    '{"verdicts": [{"req_id": "...", "status": "implemented|missing|partial", '
    '"evidence": "...", "confidence": 0.0-1.0}], "model_invocation_ms": <int>}.'
)


def _render_prompt(*, spec_text: str, diff_text: str) -> str:
    """Render the `claude -p` prompt with fenced code blocks.

    Preconditions: `spec_text` and `diff_text` are strings (may be empty).
    Postconditions: returned string contains the prompt header, a fenced
        `## Spec` block holding `_escape_placeholders(spec_text)`, and a
        fenced `## Diff` block holding `diff_text` verbatim.
    Raises: nothing.
    """
    safe_spec = _escape_placeholders(spec_text)
    return (
        f"{_PROMPT_HEADER}\n\n"
        f"## Spec\n\n```text\n{safe_spec}\n```\n\n"
        f"## Diff\n\n```text\n{diff_text}\n```\n"
    )
