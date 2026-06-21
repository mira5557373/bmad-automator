"""Bridge risk_profile into the dev-story Dev Agent Record (DAR) section.

M46 — given a list of risk-profile entries for a target, compute the
per-category P0..P3 priority (and the worst-case overall priority) and
write them into the ``## Dev Agent Record`` section of a story file.

Writes are:
  * idempotent — guarded by HTML comment sentinels so repeated calls
    replace the block instead of appending.
  * edit-authorization-safe — only ``Dev Agent Record`` is modified,
    matching ``gate_remediation.EDITABLE_SECTIONS``.
  * atomic — go through ``utils.write_atomic``.

If the story file does not have a DAR section, one is inserted before
``## File List`` (or appended to EOF if neither is present), preserving
BMAD's canonical section order.

Public API:
    RiskToStoryError
    priorities_from_risk_profile(entries) -> dict[str, str]
    build_dar_block(entries, *, target_id) -> str
    write_priorities_to_dar(story_path, entries, *, target_id) -> None
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..gate_remediation import EDITABLE_SECTIONS, validate_edit_authorization
from ..risk_profile import (
    RiskProfileError,
    aggregate_risk_priority,
    risk_score_to_priority,
    validate_risk_profile,
)
from ..utils import write_atomic


class RiskToStoryError(ValueError):
    """Raised when risk-to-DAR write cannot proceed safely."""


# Sentinels — keep these stable; downstream parsers may depend on them.
_BLOCK_START = "<!-- risk-priorities target={target_id} -->"
_BLOCK_END = "<!-- /risk-priorities -->"
_BLOCK_START_RE = re.compile(
    r"<!--\s*risk-priorities\s+target=[^>]*-->", re.IGNORECASE
)
_BLOCK_END_LITERAL = "<!-- /risk-priorities -->"

_DAR_HEADING = "## Dev Agent Record"
_FILE_LIST_HEADING_RE = re.compile(r"^##\s+File List\s*$", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)


def priorities_from_risk_profile(
    entries: list[dict[str, Any]],
) -> dict[str, str]:
    """Return a {category: P0..P3} mapping plus the worst-case priority.

    The returned dict has one key per entry's category, mapped to the
    per-entry priority derived from ``risk_score_to_priority``. The
    aggregate worst-case priority is *not* included here — callers that
    need it should call ``aggregate_risk_priority`` directly or use
    ``build_dar_block`` which embeds it in the rendered block.
    """
    try:
        validate_risk_profile(entries)
    except RiskProfileError as exc:
        raise RiskToStoryError(str(exc)) from exc
    out: dict[str, str] = {}
    for entry in entries:
        out[entry["category"]] = risk_score_to_priority(entry["score"])
    return out


def build_dar_block(
    entries: list[dict[str, Any]],
    *,
    target_id: str,
) -> str:
    """Render the sentinel-wrapped block to embed in DAR.

    Layout::

        <!-- risk-priorities target=<id> -->
        Risk priorities for <id> (worst: <PX>):
        - CAT: PX
        - CAT: PX
        <!-- /risk-priorities -->
    """
    if not isinstance(target_id, str) or not target_id.strip():
        raise RiskToStoryError("target_id must be a non-empty string")
    priorities = priorities_from_risk_profile(entries)
    worst = aggregate_risk_priority(entries)
    lines = [
        _BLOCK_START.format(target_id=target_id),
        f"Risk priorities for {target_id} (worst: {worst}):",
    ]
    for cat in sorted(priorities):
        lines.append(f"- {cat}: {priorities[cat]}")
    lines.append(_BLOCK_END)
    return "\n".join(lines) + "\n"


def write_priorities_to_dar(
    story_path: str | Path,
    entries: list[dict[str, Any]],
    *,
    target_id: str,
) -> None:
    """Embed the priorities block inside ``## Dev Agent Record``.

    Idempotent: if a prior block exists (matched by sentinels), it is
    replaced. If no DAR section exists, one is created in canonical
    position (before ``## File List`` when present, else appended).
    """
    if not entries:
        raise RiskToStoryError("entries must be a non-empty list")
    # Edit-authorization invariant — only DAR is touched.
    validate_edit_authorization({"Dev Agent Record"})
    # Defensive cross-check against gate_remediation's authorization set.
    assert "Dev Agent Record" in EDITABLE_SECTIONS  # noqa: S101

    path = Path(story_path)
    if not path.is_file():
        raise RiskToStoryError(f"story file not found: {path}")

    content = path.read_text(encoding="utf-8")
    block = build_dar_block(entries, target_id=target_id)

    new_content = _replace_or_insert_block(content, block)
    if new_content == content:
        # No structural change required — still rewrite so atomic guarantees
        # match (e.g. ensures fsync) but skip churn when truly identical.
        return
    write_atomic(path, new_content)


# ---------------------------------------------------------------- helpers


def _replace_or_insert_block(content: str, block: str) -> str:
    """Return ``content`` with ``block`` placed inside ``## Dev Agent Record``."""
    # 1) If a prior block exists anywhere, replace it in place. This keeps
    # the operation idempotent even if the section name changed casing.
    replaced, did_replace = _replace_existing_block(content, block)
    if did_replace:
        return replaced

    # 2) DAR present — splice block inside DAR (just after the heading).
    dar_re = re.compile(r"^##\s+Dev Agent Record\s*$", re.MULTILINE)
    m = dar_re.search(content)
    if m:
        insert_at = _line_end(content, m.end())
        prefix = content[:insert_at]
        suffix = content[insert_at:]
        # Ensure a blank line between heading and block; trim leading newlines
        # from suffix to keep spacing tidy.
        sep_before = "\n\n" if not prefix.endswith("\n\n") else ""
        if not prefix.endswith("\n"):
            sep_before = "\n" + sep_before
        sep_after = "" if suffix.startswith("\n") else "\n"
        return prefix + sep_before + block + sep_after + suffix

    # 3) DAR missing — create one in canonical position.
    new_section = _DAR_HEADING + "\n\n" + block + "\n"
    file_list_match = _FILE_LIST_HEADING_RE.search(content)
    if file_list_match:
        insert_at = file_list_match.start()
        prefix = content[:insert_at]
        suffix = content[insert_at:]
        if not prefix.endswith("\n\n"):
            if prefix.endswith("\n"):
                prefix = prefix + "\n"
            else:
                prefix = prefix + "\n\n"
        return prefix + new_section + suffix

    if not content.endswith("\n"):
        content = content + "\n"
    return content + "\n" + new_section


def _replace_existing_block(content: str, block: str) -> tuple[str, bool]:
    start_match = _BLOCK_START_RE.search(content)
    if not start_match:
        return content, False
    end_idx = content.find(_BLOCK_END_LITERAL, start_match.end())
    if end_idx == -1:
        # Malformed prior block — refuse to silently fix; treat as no match
        # so the caller falls through to append, avoiding data loss.
        return content, False
    end_idx_after = end_idx + len(_BLOCK_END_LITERAL)
    # Consume a trailing newline so we don't accumulate blank lines on
    # repeated rewrites.
    if end_idx_after < len(content) and content[end_idx_after] == "\n":
        end_idx_after += 1
    return content[:start_match.start()] + block + content[end_idx_after:], True


def _line_end(content: str, idx: int) -> int:
    nl = content.find("\n", idx)
    return len(content) if nl == -1 else nl + 1
