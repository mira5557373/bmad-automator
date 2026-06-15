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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from story_automator.core.atomic_io import write_atomic_text

if TYPE_CHECKING:
    from story_automator.core.spec_compliance import ReqVerdict  # noqa: F401

__all__ = [
    "TestPlanEntry",
    "plan_feature_tests",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class ReqVerdictLike(Protocol):
    """Structural shape of a single REQ verdict.

    Preconditions: implementing object exposes `req_id` (str), `status`
        (str — typically Literal["implemented", "missing", "partial"]),
        `evidence` (str), and `confidence` (float) as readable attributes.
    Postconditions: this is a `runtime_checkable` Protocol so
        ``isinstance(obj, ReqVerdictLike)`` returns True for any object
        carrying those four attributes.
    Raises: nothing — Protocols are passive.

    This Protocol exists to keep `feature_tester` runtime-independent
    of `spec_compliance`: Layer 3 never imports `ReqVerdict` at runtime
    (only inside ``if TYPE_CHECKING:`` for type-checker assistance).
    """

    req_id: str
    status: str
    evidence: str
    confidence: float


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


_REQ_ID_RE: re.Pattern[str] = re.compile(r"REQ-\d+")


def _normalize_req_id(req_id: str) -> tuple[str, str]:
    """Return ``(req_id_lower_underscored, class_suffix)`` for a REQ id.

    Preconditions: `req_id` matches ``re.fullmatch(r"REQ-\\d+", req_id)``
        exactly — leading/trailing whitespace, lowercase prefixes, and
        missing dashes are all rejected.
    Postconditions: returns a 2-tuple of strings; the first replaces the
        dash with an underscore and lowercases the whole string (for
        method names and file names), the second only replaces the dash
        with an underscore (for class name suffixes).
    Raises: ValueError if the input does not match the required pattern.
    """
    if not _REQ_ID_RE.fullmatch(req_id):
        raise ValueError(f"req_id must match 'REQ-<digits>'; got {req_id!r}")
    return req_id.lower().replace("-", "_"), req_id.replace("-", "_")


_SKELETON_TEMPLATE: str = (
    '"""Feature test for {req_id}."""\n'
    "\n"
    "from __future__ import annotations\n"
    "\n"
    "import unittest\n"
    "\n"
    "\n"
    "class TestCompliance{class_suffix}(unittest.TestCase):\n"
    '    """{req_id}: skeleton — fill in once the feature is wired."""\n'
    "\n"
    "    def test_{req_id_lower_underscored}_skeleton(self) -> None:\n"
    '        self.fail("{req_id} not yet covered by feature test")\n'
)


def _render_skeleton(req_id: str) -> str:
    """Render the skeleton test file body for `req_id`.

    Preconditions: `req_id` matches ``REQ-\\d+``.
    Postconditions: returns a UTF-8 string with LF line endings;
        byte-equal to a frozen golden test for ``REQ-07``.
    Raises: ValueError when `req_id` is malformed
        (propagated from `_normalize_req_id`).
    """
    req_id_lower_underscored, class_suffix = _normalize_req_id(req_id)
    return _SKELETON_TEMPLATE.format(
        req_id=req_id,
        req_id_lower_underscored=req_id_lower_underscored,
        class_suffix=class_suffix,
    )


def _find_existing_test(tests_dir: Path, req_id: str) -> str | None:
    """Return the resolved absolute path of the first `test_compliance_*.py`
    file under `tests_dir` whose contents contain `req_id` as a whole token,
    or ``None`` when no such file exists.

    Preconditions: `req_id` matches ``REQ-\\d+``; `tests_dir` may or may
        not exist (a missing directory yields ``None``).
    Postconditions: scans files matching ``test_compliance_*.py`` in
        lexicographic order; returns the first whose UTF-8 contents
        contain `req_id` bounded by non-word characters (so ``REQ-07``
        does NOT match a file mentioning ``REQ-070``).
    Raises: nothing — file-read errors propagate naturally as ``OSError``.
    """
    if not tests_dir.exists():
        return None
    needle = re.compile(rf"(?<!\w){re.escape(req_id)}(?!\w)")
    for path in sorted(tests_dir.glob("test_compliance_*.py")):
        if needle.search(path.read_text(encoding="utf-8")):
            return str(path.resolve())
    return None


def _plan_for_verdict(
    verdict: ReqVerdictLike,
    *,
    tests_dir: Path,
    dry_run: bool,
) -> TestPlanEntry:
    """Plan a single verdict. Internal — `plan_feature_tests` is public."""
    req_id = verdict.req_id
    # Validate up front so a malformed id fails fast before any I/O.
    req_id_lower_underscored, _ = _normalize_req_id(req_id)

    existing = _find_existing_test(tests_dir, req_id)
    if existing is not None:
        return TestPlanEntry(
            req_id=req_id,
            existing_test_path=existing,
            created_test_path=None,
            action="found",
        )

    target = tests_dir / f"test_compliance_{req_id_lower_underscored}.py"

    if dry_run:
        return TestPlanEntry(
            req_id=req_id,
            existing_test_path=None,
            created_test_path=str(target.resolve()),
            action="skipped",
        )

    tests_dir.mkdir(parents=True, exist_ok=True)
    write_atomic_text(target, _render_skeleton(req_id))
    return TestPlanEntry(
        req_id=req_id,
        existing_test_path=None,
        created_test_path=str(target.resolve()),
        action="created",
    )


def plan_feature_tests(
    verdicts: list[ReqVerdictLike],
    *,
    tests_dir: Path,
    dry_run: bool = False,
) -> list[TestPlanEntry]:
    """Plan feature tests for each `implemented` REQ verdict.

    Preconditions: every `verdict.req_id` matches ``REQ-\\d+``;
        `tests_dir` is a `Path` (need not exist — created on write);
        `dry_run`, when True, suppresses all filesystem writes.
    Postconditions: returns one `TestPlanEntry` per verdict whose
        ``status == "implemented"`` (other statuses are silently dropped
        per REQ-13). When `dry_run=False` and no existing test is found
        for a REQ, a skeleton file is written via
        ``core.atomic_io.write_atomic_text`` and `action="created"`. When
        an existing test in ``tests_dir/test_compliance_*.py`` cites the
        REQ id as a whole token, `action="found"` and no file is
        written. When `dry_run=True` and no existing test is found,
        `action="skipped"` and `created_test_path` is set to the path
        that *would* have been written.
    Raises: `ValueError` if any verdict's `req_id` is malformed;
        ``OSError`` (and subclasses) propagated from the atomic-write
        path on filesystem failure.
    """
    plan: list[TestPlanEntry] = []
    for verdict in verdicts:
        if verdict.status != "implemented":
            continue
        plan.append(_plan_for_verdict(verdict, tests_dir=tests_dir, dry_run=dry_run))
    return plan
