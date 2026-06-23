"""Gate remediation — [AI-Review] task generation and BMAD-native write-back.

Implements §9.2 remediator: on FAIL, writes [AI-Review] tasks to the
dev-story via review_continuation, honoring dev-story edit-authorization.
All writes are BMAD-native (sprint-status + story file) so bmad-help
stays consistent if a human takes over (§9.2 human-takeover).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import write_atomic


EDITABLE_SECTIONS: frozenset[str] = frozenset({
    "Tasks",
    "Subtasks",
    "Dev Agent Record",
    "File List",
    "Change Log",
    "Status",
    "baseline_commit",
})


class EditAuthorizationError(ValueError):
    """Raised when a write targets a section outside edit-authorization."""


def validate_edit_authorization(sections: set[str]) -> None:
    """Raise if any section is outside dev-story edit-authorization."""
    disallowed = sections - EDITABLE_SECTIONS
    if disallowed:
        raise EditAuthorizationError(
            f"edit-authorization violation: {', '.join(sorted(disallowed))}"
        )


def prepare_remediation_tasks(gate_file: dict[str, Any]) -> list[dict[str, Any]]:
    """Create [AI-Review] task entries from failing gate categories.

    Only categories with verdict FAIL produce tasks. PASS, CONCERNS,
    NA, and WAIVED do not.
    """
    gate_id = gate_file.get("gate_id", "")
    categories = gate_file.get("categories", {})
    tasks: list[dict[str, Any]] = []
    for cat, info in sorted(categories.items()):
        if not isinstance(info, dict):
            continue
        if info.get("verdict") != "FAIL":
            continue
        rationale = info.get("rationale", "")
        tasks.append({
            "title": f"[AI-Review] Fix {cat}: {rationale}" if rationale else f"[AI-Review] Fix {cat}",
            "category": cat,
            "gate_id": gate_id,
            "rationale": rationale,
        })
    return tasks


def write_remediation_to_story(
    story_path: str | Path,
    tasks: list[dict[str, Any]],
) -> None:
    """Append [AI-Review] tasks to the Tasks section of a dev-story.

    Respects edit-authorization: only the Tasks section is modified.

    If a ``## Tasks`` section already exists, new task bullets are inserted
    immediately after its heading. Otherwise a fresh ``## Tasks`` section
    is inserted **immediately before the first** ``##`` **heading of any
    kind** (matched by ``r"^##\\s+"``) — note this is "first ``##``", not
    "first non-editable ``##``", so if the story opens with ``## Status``
    the new Tasks section will land before ``## Status``. If the story has
    no ``##`` headings at all, the Tasks section is appended to the end.
    """
    if not tasks:
        return

    validate_edit_authorization({"Tasks"})

    path = Path(story_path)
    content = path.read_text(encoding="utf-8")

    task_lines = []
    for task in tasks:
        task_lines.append(f"- [ ] {task['title']}")

    insertion = "\n".join(task_lines) + "\n"

    tasks_match = re.search(r"^(##\s+Tasks)\s*\n", content, re.MULTILINE)
    if tasks_match:
        insert_pos = tasks_match.end()
        content = content[:insert_pos] + insertion + content[insert_pos:]
    else:
        section_match = re.search(r"^##\s+", content, re.MULTILINE)
        if section_match:
            content = (
                content[:section_match.start()]
                + "## Tasks\n"
                + insertion
                + "\n"
                + content[section_match.start():]
            )
        else:
            content = content.rstrip("\n") + "\n\n## Tasks\n" + insertion

    write_atomic(path, content)


def request_review_continuation(
    *,
    story_key: str,
    gate_id: str,
    cycle: int,
    failing_categories: list[str],
) -> dict[str, Any]:
    """Build a review_continuation descriptor for the orchestrator.

    The orchestrator uses this to drive a fresh dev-story cycle via
    the BMAD code-review -> review_continuation -> [AI-Review] loop.
    """
    return {
        "action": "review_continuation",
        "trigger": "gate-fail",
        "story_key": story_key,
        "gate_id": gate_id,
        "cycle": cycle,
        "failing_categories": list(failing_categories),
    }


def failing_categories_from_gate(gate_file: dict[str, Any]) -> list[str]:
    """Extract the list of FAIL verdict categories from a gate file."""
    categories = gate_file.get("categories", {})
    return [
        cat for cat, info in sorted(categories.items())
        if isinstance(info, dict) and info.get("verdict") == "FAIL"
    ]
