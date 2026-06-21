"""Risk-action band ladder for the Test/Engineering Assurance (TEA) gate.

This module exposes the closed, four-member action ladder that maps an
integer risk score in ``[1, 9]`` to the remediation action a story owner
must take before a release ships:

    1-3 -> DOCUMENT  — record context only
    4-5 -> MONITOR   — watch in subsequent reviews
    6-8 -> MITIGATE  — require a concrete plan before merge
    9   -> BLOCK     — hard-blocks release until the score is reduced

The band set is intentionally closed: anything outside ``[1, 9]`` is a bug
in the upstream collector, so :func:`risk_score_to_action` fails closed via
:class:`RiskProfileError` rather than silently widening the ladder.
Likewise, :func:`action_blocks_release` only treats the single literal
``"BLOCK"`` band as release-blocking — every other band is advisory and
never gates a release on its own.

The module is stdlib-only and is safe to import from any collector.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ACTION_BANDS",
    "RiskProfileError",
    "action_blocks_release",
    "risk_score_to_action",
]

#: Closed, ordered set of remediation actions. Ordering goes from least to
#: most severe so callers iterating the tuple see escalating severity.
ACTION_BANDS: tuple[str, str, str, str] = (
    "DOCUMENT",
    "MONITOR",
    "MITIGATE",
    "BLOCK",
)

# The single band that hard-blocks a release. Kept as a module-level constant
# (not duplicated as a string literal in ``action_blocks_release``) so the
# invariant "exactly one band blocks" stays auditable in one place.
_BLOCKING_BAND = "BLOCK"

_VALID_BANDS = frozenset(ACTION_BANDS)


class RiskProfileError(ValueError):
    """Raised when a risk-band input is malformed or out of range.

    Subclasses :class:`ValueError` so generic ``except ValueError`` blocks
    in upstream collectors still catch it, while still allowing precise
    handling via ``except RiskProfileError``.
    """


def risk_score_to_action(score: Any) -> str:
    """Map an integer risk score in ``[1, 9]`` to its action band.

    Boolean inputs are rejected explicitly even though ``bool`` is an
    ``int`` subclass in Python — silently mapping ``True`` to score ``1``
    would mask upstream bugs.

    Raises:
        RiskProfileError: if ``score`` is not a real ``int``, or if it is
        outside ``[1, 9]``.
    """
    if isinstance(score, bool) or not isinstance(score, int):
        raise RiskProfileError(
            f"risk score must be an int in [1, 9]; got {type(score).__name__}"
        )
    if score < 1 or score > 9:
        raise RiskProfileError(
            f"risk score must be in [1, 9]; got {score}"
        )
    if score <= 3:
        return "DOCUMENT"
    if score <= 5:
        return "MONITOR"
    if score <= 8:
        return "MITIGATE"
    return _BLOCKING_BAND


def action_blocks_release(action: Any) -> bool:
    """Return ``True`` iff ``action`` hard-blocks the release.

    Only the exact literal ``"BLOCK"`` is release-blocking. ``DOCUMENT``,
    ``MONITOR``, and ``MITIGATE`` are advisory bands that do not, on their
    own, prevent shipping.

    Raises:
        RiskProfileError: if ``action`` is not a string, or is not one of
        the four bands in :data:`ACTION_BANDS`. Case and whitespace are
        significant — callers must canonicalize before calling.
    """
    if not isinstance(action, str):
        raise RiskProfileError(
            f"action band must be a string; got {type(action).__name__}"
        )
    if action not in _VALID_BANDS:
        raise RiskProfileError(
            f"unknown action band: {action!r}; expected one of {ACTION_BANDS}"
        )
    return action == _BLOCKING_BAND
