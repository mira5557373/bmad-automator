"""bmad_review_bridge — translate TEA gate verdicts to BMAD review rows.

The BMAD code-review skill emits adversarial review rows in a closed
markdown vocabulary defined by ``core.review_taxonomy``:

    [Review][<action>] <file>:<line> <finding>

where ``<action>`` is one of ``patch``, ``decision_needed``, ``defer``, or
``dismiss``. This module bridges the per-category verdicts produced by
the production-ready factory gate (``core.gate_schema.make_gate_file``)
into a list of those rows so the BMAD review surface stays the single
source of truth for human-visible review actions during the
review_continuation -> [AI-Review] loop (see ``gate_remediation.py``).

The bridge is intentionally pure:

* Inputs: a gate_file dict (the same shape produced by
  ``gate_schema.make_gate_file``) or the remediation task descriptors
  produced by ``gate_remediation.prepare_remediation_tasks``.
* Outputs: a list of canonical review row strings, formatted by
  ``review_taxonomy.format_review_row``.
* No I/O. No telemetry. No state mutation. Callers handle writeback.

Mapping rules (kept aligned with §6.3 verdict semantics):

* ``FAIL``     → ``patch``           — concrete, must-fix
* ``CONCERNS`` → ``decision_needed`` — human triage required
* ``PASS``     → suppressed          — no review row needed
* ``NA``       → suppressed          — category not in scope
* ``WAIVED``   → suppressed          — operator already accepted

When a FAIL category has no concrete ``findings`` list, the bridge falls
back to a single ``decision_needed`` row carrying the category rationale
(fail-closed: the human still sees something).
"""
from __future__ import annotations

import re
from typing import Any

from ..review_taxonomy import (
    ReviewActionError,
    format_review_row,
)


class BridgeError(ValueError):
    """Raised when a gate payload is malformed for review-row translation."""


# Closed per-verdict mapping. ``None`` means "suppress: no row".
# Keep aligned with ``gate_rules.aggregate_verdicts`` verdict vocabulary.
VERDICT_TO_ACTION: dict[str, str | None] = {
    "FAIL": "patch",
    "CONCERNS": "decision_needed",
    "PASS": None,
    "NA": None,
    "WAIVED": None,
}


# Heuristic: parse "<file>:<line> <message>" or "<file> <message>" out of
# a free-form finding string. Best-effort only — falls back to message-only
# rendering when the pattern does not match.
_FINDING_RE = re.compile(
    r"^(?P<file>\S+?\.[A-Za-z0-9_]+)(?::(?P<line>\d+))?\s+(?P<message>.+)$"
)


def _normalize_finding(finding: object) -> tuple[str, int | None, str]:
    """Return ``(file_ref, line, message)`` for a finding entry.

    Accepts either:
    * a string in ``"<file>:<line> <message>"`` shape (best-effort), or
    * a dict with optional ``file``/``line``/``message`` keys.

    Raises ``BridgeError`` on unsupported types.
    """
    if isinstance(finding, dict):
        raw_file = finding.get("file", "")
        raw_line = finding.get("line")
        raw_message = finding.get("message", "")
        if not isinstance(raw_file, str):
            raise BridgeError(
                f"finding.file must be a string, got {type(raw_file).__name__}"
            )
        if raw_line is not None and (
            not isinstance(raw_line, int) or isinstance(raw_line, bool)
        ):
            raise BridgeError(
                f"finding.line must be an int, got {type(raw_line).__name__}"
            )
        if not isinstance(raw_message, str):
            raise BridgeError(
                f"finding.message must be a string, "
                f"got {type(raw_message).__name__}"
            )
        message = raw_message.strip()
        if not message:
            # An empty message is unusable as a review row.
            raise BridgeError("finding.message must be non-empty")
        return raw_file.strip(), raw_line, message

    if isinstance(finding, str):
        text = finding.strip()
        if not text:
            raise BridgeError("finding string must be non-empty")
        match = _FINDING_RE.match(text)
        if match:
            file_ref = match.group("file") or ""
            line_group = match.group("line")
            line = int(line_group) if line_group is not None else None
            return file_ref, line, match.group("message").strip()
        return "", None, text

    raise BridgeError(
        f"finding must be a string or dict, got {type(finding).__name__}"
    )


def finding_to_review_row(
    *,
    action: str,
    category: str,
    finding: object,
) -> str:
    """Render a single review row for one ``finding`` under ``category``.

    ``action`` is forwarded to ``format_review_row`` (and therefore
    validated by ``canonicalize_action``). ``category`` is prepended to
    the message so reviewers can see which factory category surfaced the
    issue, e.g. ``[correctness] AssertionError``.
    """
    file_ref, line, message = _normalize_finding(finding)
    prefixed = f"[{category}] {message}" if category else message
    try:
        return format_review_row(
            action=action,
            finding=prefixed,
            file_ref=file_ref,
            line=line,
        )
    except (ReviewActionError, ValueError) as exc:
        raise BridgeError(str(exc)) from exc


def _category_verdict(cat: str, info: object) -> str:
    if not isinstance(info, dict):
        raise BridgeError(
            f"gate.categories[{cat!r}] must be a dict, "
            f"got {type(info).__name__}"
        )
    verdict = info.get("verdict")
    if not isinstance(verdict, str):
        raise BridgeError(
            f"gate.categories[{cat!r}].verdict must be a string"
        )
    if verdict not in VERDICT_TO_ACTION:
        raise BridgeError(
            f"unknown verdict {verdict!r} for category {cat!r} "
            f"(known: {sorted(VERDICT_TO_ACTION)})"
        )
    return verdict


def _category_findings(cat: str, info: dict[str, Any]) -> list[object]:
    findings = info.get("findings", []) or []
    if not isinstance(findings, list):
        raise BridgeError(
            f"gate.categories[{cat!r}].findings must be a list"
        )
    for entry in findings:
        if not isinstance(entry, (str, dict)):
            raise BridgeError(
                f"gate.categories[{cat!r}].findings entries must be "
                f"str or dict, got {type(entry).__name__}"
            )
    return findings


def bridge_gate_to_review_rows(gate_file: dict[str, Any]) -> list[str]:
    """Translate a gate file's per-category verdicts into review rows.

    Iteration is sorted by category name for deterministic output, which
    matches ``gate_remediation.prepare_remediation_tasks`` and keeps the
    review surface diff-friendly across runs.

    Suppressed verdicts (PASS / NA / WAIVED) produce zero rows. FAIL with
    no concrete findings falls back to a single ``decision_needed`` row
    carrying the category rationale so the human always sees something.
    """
    if not isinstance(gate_file, dict):
        raise BridgeError("gate_file must be a dict")
    categories = gate_file.get("categories")
    if not isinstance(categories, dict):
        raise BridgeError("gate_file.categories must be a dict")

    rows: list[str] = []
    for cat in sorted(categories):
        info = categories[cat]
        verdict = _category_verdict(cat, info)
        action = VERDICT_TO_ACTION[verdict]
        if action is None:
            continue

        findings = _category_findings(cat, info)
        if findings:
            for entry in findings:
                rows.append(
                    finding_to_review_row(
                        action=action,
                        category=cat,
                        finding=entry,
                    )
                )
            continue

        # No concrete findings: fail-closed to decision_needed with
        # rationale so reviewers still see the category surface.
        rationale = info.get("rationale", "")
        if not isinstance(rationale, str):
            raise BridgeError(
                f"gate.categories[{cat!r}].rationale must be a string"
            )
        message = rationale.strip() or f"{verdict} with no rationale"
        rows.append(
            finding_to_review_row(
                action="decision_needed",
                category=cat,
                finding=message,
            )
        )

    return rows


def bridge_remediation_tasks_to_rows(
    tasks: list[dict[str, Any]],
) -> list[str]:
    """Translate ``gate_remediation`` task descriptors into review rows.

    Each task already represents a FAIL category that needs operator
    attention; the bridge surfaces it as a ``decision_needed`` row so a
    human can route the work (the actual code change is still produced by
    the BMAD review_continuation loop, not by the bridge).
    """
    if not isinstance(tasks, list):
        raise BridgeError("tasks must be a list")

    rows: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise BridgeError(
                f"task must be a dict, got {type(task).__name__}"
            )
        category = task.get("category")
        if not isinstance(category, str) or not category.strip():
            raise BridgeError("task.category must be a non-empty string")
        rationale = task.get("rationale") or task.get("title") or ""
        if not isinstance(rationale, str):
            raise BridgeError("task.rationale must be a string")
        rows.append(
            finding_to_review_row(
                action="decision_needed",
                category=category.strip(),
                finding=rationale.strip() or category.strip(),
            )
        )
    return rows


def summarize_bridge_result(rows: list[str]) -> dict[str, int]:
    """Return action-count summary for a list of bridge-produced rows.

    Keys include each action name found and a ``"total"`` aggregate. The
    summary is purely diagnostic — used by callers that want to log how
    many ``patch`` vs ``decision_needed`` rows surfaced for a given
    gate.
    """
    counts: dict[str, int] = {"total": 0}
    action_re = re.compile(r"^\[Review\]\[(?P<action>[A-Za-z_]+)\]")
    for row in rows:
        if not isinstance(row, str):
            continue
        counts["total"] += 1
        match = action_re.match(row)
        if not match:
            continue
        action = match.group("action")
        counts[action] = counts.get(action, 0) + 1
    return counts
