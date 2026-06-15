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
