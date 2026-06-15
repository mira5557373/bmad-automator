"""``sw ceiling-check`` CLI subcommand wrapping ``evaluate_ceilings``.

Thin shell-callable wrapper around ``core.budget_ceilings.evaluate_ceilings``
(M03 REQ-13). Prints a single compact JSON object to stdout describing
the verdict so BMAD step markdown can branch on ``ALLOW`` / ``WARN`` /
``BLOCK`` via ``jq``. Read-only by design — does not write the ledger,
does not call audit-log routines, and does not prompt for input
(REQ-11, REQ-12).
"""

from __future__ import annotations

from ..core.common import print_json


def cmd_ceiling_check(args: list[str]) -> int:
    """Entry point for ``story-automator ceiling-check`` (REQ-13).

    Required flags:
        --gate {init,story_start,retry_start}
        --events <path-to-events.jsonl>
    """
    print_json({"ok": False, "error": "not_implemented"})
    return 1
