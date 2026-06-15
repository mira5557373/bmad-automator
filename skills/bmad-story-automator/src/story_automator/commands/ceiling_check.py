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


_VALID_GATES = ("init", "story_start", "retry_start")


def _flag_map(args: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and index + 1 < len(args):
            output[token[2:]] = args[index + 1]
            index += 2
            continue
        index += 1
    return output


def cmd_ceiling_check(args: list[str]) -> int:
    """Entry point for ``story-automator ceiling-check`` (REQ-13).

    Required flags:
        --gate {init,story_start,retry_start}
        --events <path-to-events.jsonl>
    """
    params = _flag_map(args)
    gate = params.get("gate", "")
    events_path = params.get("events", "")
    if not gate:
        print_json({"ok": False, "error": "missing_gate"})
        return 1
    if gate not in _VALID_GATES:
        print_json({"ok": False, "error": "invalid_gate", "gate": gate})
        return 1
    if not events_path:
        print_json({"ok": False, "error": "missing_events"})
        return 1
    print_json({"ok": False, "error": "not_implemented"})
    return 1
