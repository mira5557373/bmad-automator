"""Gate CLI commands — status, resume, invalidate.

Each action returns an int exit code; output is structured JSON on stdout.
"""
from __future__ import annotations

import re
import sys
from typing import Any

from story_automator.core.evidence_io import read_gate_marker
from story_automator.core.gate_ops import (
    gate_doctor as _gate_doctor_fn,
    gate_summary as _gate_summary_fn,
    list_verdicts as _list_verdicts_fn,
)
from story_automator.core.gate_status import (
    invalidate_gates_for_target,
    list_parked,
    load_mitigation_debt,
    resume_story,
)
from story_automator.core.utils import get_project_root, print_json

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _project_root() -> str:
    return get_project_root()


def gate_status_action(args: list[str]) -> int:
    project_root = _project_root()
    state_filter = None
    for arg in args:
        if arg.startswith("--state="):
            state_filter = arg.split("=", 1)[1]

    parked = list_parked(project_root, state_filter=state_filter)
    marker = read_gate_marker(project_root)
    debt = load_mitigation_debt(project_root)

    result: dict[str, Any] = {
        "ok": True,
        "parked": parked,
        "parked_count": len(parked),
        "in_progress": marker is not None,
        "mitigation_debt": debt,
        "mitigation_debt_count": len(debt),
    }
    if marker is not None:
        result["in_progress_gate_id"] = marker.get("gate_id", "")
        result["in_progress_commit"] = marker.get("commit_sha", "")
    print_json(result)
    return 0


def gate_resume_action(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "gate_id required"})
        return 1
    gate_id = args[0]
    if not _SAFE_ID.match(gate_id):
        print_json({"ok": False, "error": "invalid gate_id format"})
        return 1
    project_root = _project_root()
    record = resume_story(project_root, gate_id)
    if record is None:
        print_json({"ok": False, "error": "parked story not found", "gate_id": gate_id})
        return 1
    print_json({
        "ok": True,
        "gate_id": gate_id,
        "story_key": record.get("story_key", ""),
        "reason": record.get("reason", ""),
        "resumed": True,
    })
    return 0


def gate_invalidate_action(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "target (story or epic id) required"})
        return 1
    target_id = args[0]
    if not _SAFE_ID.match(target_id):
        print_json({"ok": False, "error": "invalid target_id format"})
        return 1
    project_root = _project_root()
    invalidated = invalidate_gates_for_target(project_root, target_id)
    print_json({
        "ok": True,
        "target": target_id,
        "invalidated": invalidated,
        "invalidated_count": len(invalidated),
    })
    return 0


def gate_list_action(args: list[str]) -> int:
    project_root = _project_root()
    target_filter = None
    verdict_filter = None
    for arg in args:
        if arg.startswith("--target="):
            target_filter = arg.split("=", 1)[1]
        elif arg.startswith("--verdict="):
            verdict_filter = arg.split("=", 1)[1]
    verdicts = _list_verdicts_fn(
        project_root,
        target_filter=target_filter,
        verdict_filter=verdict_filter,
    )
    print_json({"ok": True, "verdicts": verdicts, "count": len(verdicts)})
    return 0


def gate_summary_action(args: list[str]) -> int:
    project_root = _project_root()
    summary = _gate_summary_fn(project_root)
    print_json(summary)
    return 0


def gate_doctor_action(args: list[str]) -> int:
    project_root = _project_root()
    result = _gate_doctor_fn(project_root)
    print_json(result)
    return 0 if result["healthy"] else 1


def gate_dispatch(args: list[str]) -> int:
    if not args:
        _gate_usage()
        return 1
    subcommand = args[0]
    dispatch = {
        "status": gate_status_action,
        "resume": gate_resume_action,
        "invalidate": gate_invalidate_action,
        "doctor": gate_doctor_action,
        "list": gate_list_action,
        "summary": gate_summary_action,
    }
    handler = dispatch.get(subcommand)
    if handler is None:
        _gate_usage()
        return 1
    return handler(args[1:])


def _gate_usage() -> None:
    print("Usage: orchestrator-helper gate <subcommand> [args]",
          file=sys.stderr)
    print("", file=sys.stderr)
    print("  gate status [--state=parked]", file=sys.stderr)
    print("  gate resume <gate_id>", file=sys.stderr)
    print("  gate invalidate <story|epic>", file=sys.stderr)
    print("  gate doctor", file=sys.stderr)
    print("  gate list [--target=<id>] [--verdict=<PASS|FAIL|...>]", file=sys.stderr)
    print("  gate summary", file=sys.stderr)
