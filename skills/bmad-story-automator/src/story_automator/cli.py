from __future__ import annotations

import difflib
import sys
from typing import Callable

from . import __version__
from .commands.agent_config_cmd import cmd_agent_config
from .commands.basic import (
    cmd_commit_story,
    cmd_derive_project_slug,
    cmd_ensure_marker_gitignore,
    cmd_ensure_stop_hook,
    cmd_list_sessions,
    cmd_reconcile_story,
    cmd_stop_hook,
)
from .commands.ceiling_check import cmd_ceiling_check
from .commands.doctor import cmd_doctor
from .commands.trust_verify import cmd_trust_verify
from .commands.telemetry_report import cmd_telemetry_report
from .commands.calibration_cmd import cmd_calibration
from .commands.drift_cmd import cmd_drift
from .commands.triage_cmd import cmd_triage
from .commands.audit_verify_cmd import cmd_audit_verify
from .commands.record_cost import cmd_record_cost
from .commands.orchestrator import cmd_orchestrator_helper
from .commands.state import (
    cmd_build_state_doc,
    cmd_sprint_compare,
    cmd_state_metrics,
    cmd_validate_state,
)
from .commands.tmux import (
    cmd_codex_status_check,
    cmd_heartbeat_check,
    cmd_monitor_session,
    cmd_tmux_status_check,
    cmd_tmux_wrapper,
)
from .commands.validate_story_creation import cmd_validate_story_creation
from .core.common import help_flag, print_json, safe_int
from .core.epic_parser import (
    epic_complete,
    parse_epic_file,
    parse_story,
    parse_story_range,
)


Command = Callable[[list[str]], int]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _usage(sys.stderr)
        return 1
    if help_flag(args[0]):
        _usage(sys.stdout)
        return 0
    if args[0] in {"--version", "-v"}:
        print_json({"ok": True, "version": __version__})
        return 0
    command = args[0]
    rest = args[1:]
    registry = _command_registry()
    handler = registry.get(command)
    if not handler:
        print(f"Unknown command: {command}", file=sys.stderr)
        matches = difflib.get_close_matches(command, list(registry), n=3)
        if matches:
            print(f"Did you mean: {', '.join(matches)}?", file=sys.stderr)
        # The trust-but-verify command is registered with an underscore, which
        # is easy to mistype as a hyphen; point there explicitly on a near miss.
        if command == "trust-verify":
            print("Note: the command is 'trust_verify' (underscore).", file=sys.stderr)
        _usage(sys.stderr)
        return 1
    try:
        return handler(rest)
    except Exception as exc:  # noqa: BLE001 - top-level JSON-contract backstop
        # Any handler that escapes with an unexpected exception would otherwise
        # leak a Python traceback to stderr and emit no JSON, silently breaking
        # the orchestrator step scripts that parse stdout. Preserve the uniform
        # machine-readable error contract instead.
        print_json(
            {
                "ok": False,
                "error": "internal_error",
                "command": command,
                "detail": str(exc),
            }
        )
        return 1


def _command_registry() -> dict[str, Command]:
    """Single source of truth for the command surface.

    Both ``main`` (dispatch) and ``_usage`` (help text) read this map so the
    two can never drift. Built lazily at call time so the module-level
    ``_cmd_*`` helpers defined later in this file resolve correctly.
    Insertion order is the help-listing order.
    """
    return {
        "version": _cmd_version,
        "doctor": cmd_doctor,
        "derive-project-slug": cmd_derive_project_slug,
        "ensure-marker-gitignore": cmd_ensure_marker_gitignore,
        "ensure-stop-hook": cmd_ensure_stop_hook,
        "stop-hook": cmd_stop_hook,
        "build-state-doc": cmd_build_state_doc,
        "commit-story": cmd_commit_story,
        "reconcile-story": cmd_reconcile_story,
        "parse-epic": _cmd_parse_epic,
        "parse-story": _cmd_parse_story,
        "parse-story-range": _cmd_parse_story_range,
        "epic-complete": _cmd_epic_complete,
        "sprint-compare": cmd_sprint_compare,
        "state-metrics": cmd_state_metrics,
        "validate-state": cmd_validate_state,
        "validate-story-creation": cmd_validate_story_creation,
        "list-sessions": cmd_list_sessions,
        "tmux-wrapper": cmd_tmux_wrapper,
        "heartbeat-check": cmd_heartbeat_check,
        "codex-status-check": cmd_codex_status_check,
        "tmux-status-check": cmd_tmux_status_check,
        "monitor-session": cmd_monitor_session,
        "orchestrator-helper": cmd_orchestrator_helper,
        "agent-config": cmd_agent_config,
        "ceiling-check": cmd_ceiling_check,
        # Capability-delivery commands (analysis enhancement 2026-06-16):
        # wire the previously dead-in-production core modules onto the CLI.
        "trust_verify": cmd_trust_verify,
        "telemetry-report": cmd_telemetry_report,
        "calibration": cmd_calibration,
        "drift": cmd_drift,
        "triage": cmd_triage,
        "audit-verify": cmd_audit_verify,
        "record-cost": cmd_record_cost,
    }


def _usage(stream: object) -> None:
    print("story-automator <command> [args]", file=stream)
    print("", file=stream)
    print("Commands:", file=stream)
    # Keep our programmatic iteration over _command_registry() — it
    # automatically picks up new commands (incl. the upstream-added
    # reconcile-story / test-counts) without duplicating the list.
    for name in _command_registry():
        print(f"  {name}", file=stream)


def _cmd_version(_args: list[str]) -> int:
    print_json({"ok": True, "version": __version__})
    return 0


def _cmd_parse_epic(args: list[str]) -> int:
    epic_file = _arg_value(args, "--file")
    if not epic_file:
        print_json({"ok": False, "error": "epic_file_not_found"})
        return 1
    try:
        print_json(parse_epic_file(epic_file))
        return 0
    except FileNotFoundError:
        print_json({"ok": False, "error": "epic_file_not_found"})
        return 1


def _cmd_parse_story(args: list[str]) -> int:
    epic = _arg_value(args, "--epic")
    story = _arg_value(args, "--story")
    rules = _arg_value(args, "--rules")
    if not epic or not story:
        print_json({"ok": False, "error": "missing_epic_or_story"})
        return 1
    if not rules:
        print_json({"ok": False, "error": "rules_file_not_found"})
        return 1
    try:
        print_json(parse_story(epic, story, rules))
        return 0
    except FileNotFoundError:
        print_json(
            {
                "ok": False,
                "error": "missing_epic_or_story" if epic else "rules_file_not_found",
            }
        )
        return 1
    except ValueError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 1


def _cmd_parse_story_range(args: list[str]) -> int:
    user_input = _arg_value(args, "--input")
    # safe_int funnels a non-numeric --total (e.g. an unexpanded shell var) to 0,
    # which parse_story_range rejects with ValueError -> the existing structured
    # error below, instead of an uncaught traceback that breaks the JSON contract.
    total = safe_int(_arg_value(args, "--total"), 0)
    ids = _arg_value(args, "--ids") or ""
    try:
        print_json(parse_story_range(user_input, total, ids))
        return 0
    except ValueError:
        print_json({"ok": False, "error": "missing_input_or_total"})
        return 1


def _cmd_epic_complete(args: list[str]) -> int:
    epic = _arg_value(args, "--epic")
    range_csv = _arg_value(args, "--range") or ""
    if not epic:
        print_json({"ok": False, "error": "epic_file_not_found"})
        return 1
    try:
        print_json(epic_complete(epic, range_csv))
        return 0
    except FileNotFoundError:
        print_json({"ok": False, "error": "epic_file_not_found"})
        return 1
    except ValueError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 1


def _arg_value(args: list[str], flag: str) -> str:
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return args[index + 1]
    return ""
