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
