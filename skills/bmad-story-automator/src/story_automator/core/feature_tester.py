"""Layer 3 of the M06a trust-but-verify stack: feature-test planning.

For each `implemented` REQ verdict produced by Layer 2
(`core/spec_compliance.py`), this module either locates an existing
feature test in `tests/test_compliance_*.py` whose docstring or
comments cite the REQ id, or writes a minimal failing-skeleton
`unittest.TestCase` file so the next TDD pass has somewhere to start.

Layer 3 is intentionally decoupled from Layer 1 (`gap_validator.py`)
and Layer 2 (`spec_compliance.py`): the only runtime cross-module
dependency is `core.atomic_io.write_atomic_text`. The shape of the
input verdict list is described by the structural `ReqVerdictLike`
Protocol; the concrete `ReqVerdict` from Layer 2 is referenced only
inside `if TYPE_CHECKING:` so importing this module never transitively
loads `spec_compliance.py`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from story_automator.core.spec_compliance import ReqVerdict  # noqa: F401

__all__ = [  # noqa: F822 — symbols added in subsequent tasks
    "TestPlanEntry",
    "plan_feature_tests",
]

logger = logging.getLogger(__name__)
