from __future__ import annotations

VALID_COVERAGE_STATUSES: frozenset[str] = frozenset(
    {"FULL", "PARTIAL", "UNIT-ONLY", "INTEGRATION-ONLY", "NONE"}
)

_P0_PASSING: frozenset[str] = frozenset({"FULL"})
_P1_PASSING: frozenset[str] = frozenset({"FULL", "PARTIAL"})


class CoverageStatusError(ValueError):
    """Raised when a coverage-status value or input is invalid."""


def _require_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise CoverageStatusError(
            f"{name} must be bool, got {type(value).__name__}"
        )
    return value


def classify_coverage(
    *,
    has_unit: bool,
    has_integration: bool,
    has_e2e: bool,
) -> str:
    """Classify test coverage into the closed five-status vocabulary.

    Mapping:
        (False, False, False)             -> NONE
        (True,  False, False)             -> UNIT-ONLY
        (False, True,  False) | (False, False, True) -> INTEGRATION-ONLY
        (True,  True,  False) | (True,  False, True) -> PARTIAL
        (True,  True,  True)              -> FULL

    Treats e2e coverage as a superset of integration coverage for
    classification purposes: a story with only e2e tests is reported as
    INTEGRATION-ONLY, and a story with unit + e2e is PARTIAL.

    Raises CoverageStatusError if any flag is not a bool.
    """
    has_unit = _require_bool("has_unit", has_unit)
    has_integration = _require_bool("has_integration", has_integration)
    has_e2e = _require_bool("has_e2e", has_e2e)

    has_integration_layer = has_integration or has_e2e

    if has_unit and has_integration and has_e2e:
        return "FULL"
    if has_unit and has_integration_layer:
        return "PARTIAL"
    if has_unit:
        return "UNIT-ONLY"
    if has_integration_layer:
        return "INTEGRATION-ONLY"
    return "NONE"


def _require_status(value: object) -> str:
    if not isinstance(value, str):
        raise CoverageStatusError(
            f"coverage status must be a string, got {type(value).__name__}"
        )
    if value not in VALID_COVERAGE_STATUSES:
        raise CoverageStatusError(
            f"unknown coverage status: {value!r} (valid: "
            f"{sorted(VALID_COVERAGE_STATUSES)})"
        )
    return value


def is_blocking_priority_p0(status: str) -> bool:
    """Return True iff ``status`` passes a priority-P0 coverage gate.

    Only FULL coverage clears the P0 bar. All other statuses block P0.
    Raises CoverageStatusError if ``status`` is not a member of
    VALID_COVERAGE_STATUSES.
    """
    return _require_status(status) in _P0_PASSING


def is_passing_priority_p1(status: str) -> bool:
    """Return True iff ``status`` passes a priority-P1 coverage gate.

    FULL and PARTIAL both clear the P1 bar. UNIT-ONLY, INTEGRATION-ONLY,
    and NONE all block P1. Raises CoverageStatusError if ``status`` is
    not a member of VALID_COVERAGE_STATUSES.
    """
    return _require_status(status) in _P1_PASSING
