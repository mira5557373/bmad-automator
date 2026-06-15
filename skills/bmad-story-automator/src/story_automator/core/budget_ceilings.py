"""Budget ceiling data types and config reader (M03 sub-milestone M1).

Ships the data substrate of M03 budget enforcement: the
``CeilingDecision`` enum (REQ-02), the ``BudgetCeiling`` dataclass
(REQ-03), and the tolerant ``parse_ceilings_config`` reader
(REQ-04 / REQ-05). The reader is intentionally forgiving — every
malformed shape (missing file, missing keys, malformed entry) returns
an empty list or skips the entry while appending a structured warning
to the module-private ``_PARSE_WARNINGS`` list (cleared on every
call). The list is not in ``__all__`` and is not part of the stable
public surface — it exists so test code and downstream callers can
inspect why ceilings were dropped.

Out of scope for this sub-milestone: ``evaluate_ceilings``,
``bypass_allowed``, the wire-up to ``sw cli ceiling-check``, the
ten-line BMAD step insertions, and the ledger-streaming summation.
Those land in M03-M2 (evaluator) and M03-M3 (BMAD wiring).
"""

from __future__ import annotations

import enum
import json
import math
from dataclasses import dataclass
from pathlib import Path

__all__ = ["BudgetCeiling", "CeilingDecision", "parse_ceilings_config"]


class CeilingDecision(enum.Enum):
    """Tri-state verdict returned by ceiling evaluation.

    Declaration order is load-bearing: callers may compare verdicts by
    member index when merging multi-ceiling results (REQ-10), so the
    sequence ALLOW < WARN < BLOCK must never be reordered.
    """

    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(kw_only=True)
class BudgetCeiling:
    """Single configured spending ceiling read from ``workflow.json``.

    ``window`` is one of ``"per_run"``, ``"24h"``, ``"7d"``, ``"30d"``
    (REQ-03). ``warn_at`` is a fraction in ``(0.0, 1.0]`` multiplied
    against ``limit_usd`` to produce the WARN threshold. ``gate_names``
    enumerates which preflight gate names this ceiling applies to:
    elements are drawn from ``{"init", "story_start", "retry_start"}``
    per REQ-07, but this dataclass does not enforce that set — the
    evaluator (M03-M2) is the only consumer that filters on it.
    """

    name: str
    window: str
    limit_usd: float
    warn_at: float
    gate_names: tuple[str, ...]


_PARSE_WARNINGS: list[dict[str, str]] = []
"""Structured parse warnings, cleared at the start of each
``parse_ceilings_config`` call (REQ-05). Each entry is a dict with
``index`` (str repr of the position in the array), ``reason``
(short slug), and ``detail`` (free-form message). Intentionally
module-level, not part of the function return, so callers that care
about warnings can opt in without complicating the happy-path
signature."""

_VALID_WINDOWS: frozenset[str] = frozenset({"per_run", "24h", "7d", "30d"})
_REQUIRED_KEYS: tuple[str, ...] = (
    "name",
    "window",
    "limit_usd",
    "warn_at",
    "gate_names",
)


def _validate_ceiling_dict(index: int, raw: object) -> BudgetCeiling | None:
    """Validate one ceiling object; return ``None`` and record a warning
    if the entry is malformed (REQ-05).

    Validation covers: dict shape, presence of all five required keys,
    string type for ``name`` and ``window``, ``window`` membership in
    ``_VALID_WINDOWS``, numeric and strictly-positive ``limit_usd``,
    numeric ``warn_at`` in the half-open interval ``(0.0, 1.0]``, and
    ``gate_names`` being a list of strings.
    """
    if not isinstance(raw, dict):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "not_object", "detail": type(raw).__name__}
        )
        return None
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "missing_keys", "detail": ",".join(missing)}
        )
        return None
    name = raw["name"]
    window = raw["window"]
    limit_usd = raw["limit_usd"]
    warn_at = raw["warn_at"]
    gate_names = raw["gate_names"]
    if not isinstance(name, str) or not name:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_name", "detail": repr(name)[:40]}
        )
        return None
    if not isinstance(window, str) or window not in _VALID_WINDOWS:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_window", "detail": repr(window)[:40]}
        )
        return None
    if not isinstance(limit_usd, (int, float)) or isinstance(limit_usd, bool):
        _PARSE_WARNINGS.append(
            {
                "index": str(index),
                "reason": "bad_limit_usd_type",
                "detail": type(limit_usd).__name__,
            }
        )
        return None
    limit_usd_f = float(limit_usd)
    if not math.isfinite(limit_usd_f) or limit_usd_f <= 0.0:
        _PARSE_WARNINGS.append(
            {
                "index": str(index),
                "reason": "bad_limit_usd_value",
                "detail": repr(limit_usd)[:40],
            }
        )
        return None
    if not isinstance(warn_at, (int, float)) or isinstance(warn_at, bool):
        _PARSE_WARNINGS.append(
            {
                "index": str(index),
                "reason": "bad_warn_at_type",
                "detail": type(warn_at).__name__,
            }
        )
        return None
    warn_at_f = float(warn_at)
    if not (0.0 < warn_at_f <= 1.0):
        _PARSE_WARNINGS.append(
            {
                "index": str(index),
                "reason": "bad_warn_at_value",
                "detail": repr(warn_at)[:40],
            }
        )
        return None
    if not isinstance(gate_names, list) or not all(
        isinstance(g, str) for g in gate_names
    ):
        _PARSE_WARNINGS.append(
            {
                "index": str(index),
                "reason": "bad_gate_names",
                "detail": repr(gate_names)[:40],
            }
        )
        return None
    return BudgetCeiling(
        name=name,
        window=window,
        limit_usd=limit_usd_f,
        warn_at=warn_at_f,
        gate_names=tuple(gate_names),
    )


def parse_ceilings_config(workflow_json_path: str | Path) -> list[BudgetCeiling]:
    """Read ``policy.cost_ceilings`` from ``workflow.json`` (REQ-04, REQ-05).

    Tolerant by design: missing file, empty JSON, malformed JSON, missing
    ``policy`` key, missing ``cost_ceilings`` key, and ``cost_ceilings``
    not being a list all return an empty list. Individual malformed
    ceiling entries are skipped while a structured warning is appended
    to ``_PARSE_WARNINGS`` (cleared at the start of every call).
    """
    _PARSE_WARNINGS.clear()
    path = Path(workflow_json_path)
    if not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        return []
    raw_ceilings = policy.get("cost_ceilings")
    if not isinstance(raw_ceilings, list):
        return []
    parsed: list[BudgetCeiling] = []
    for index, raw in enumerate(raw_ceilings):
        ceiling = _validate_ceiling_dict(index, raw)
        if ceiling is not None:
            parsed.append(ceiling)
    return parsed
