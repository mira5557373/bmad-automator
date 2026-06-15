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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from story_automator.core.spec_compliance import ReqVerdict  # noqa: F401

__all__ = [  # noqa: F822 — plan_feature_tests added in a subsequent task
    "TestPlanEntry",
    "plan_feature_tests",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TestPlanEntry:
    """One row of the feature-test plan: what to do for a single REQ.

    Preconditions: `req_id` is a non-empty string matching ``REQ-\\d+``
        (the regex is enforced by `plan_feature_tests`, not by this
        dataclass itself); `action` is exactly one of "found", "created",
        "skipped"; when `action == "found"`, `existing_test_path` is the
        absolute string path of the located test file and
        `created_test_path` is `None`; when `action == "created"`,
        `existing_test_path` is `None` and `created_test_path` is the
        absolute string path of the freshly written skeleton; when
        `action == "skipped"`, `existing_test_path` is `None` and
        `created_test_path` is the absolute string path that *would*
        have been written had `dry_run=False`.
    Postconditions: instance is frozen; all four fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    req_id: str
    existing_test_path: str | None
    created_test_path: str | None
    action: Literal["found", "created", "skipped"]
