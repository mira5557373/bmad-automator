from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from story_automator.core.artifact_paths import implementation_artifacts_dir
from story_automator.core.frontmatter import (
    extract_last_action,
    extract_title,
    find_frontmatter_value,
    find_frontmatter_value_case,
    parse_simple_frontmatter,
)
from story_automator.core.runtime_policy import (
    PolicyError,
    crash_max_retries,
    load_runtime_policy,
    review_max_cycles,
    summarize_state_policy_fields,
)
from story_automator.core.review_verify import verify_code_review_completion
from story_automator.core.runtime_layout import (
    active_marker_path,
    active_marker_project_entry,
)
from story_automator.core.success_verifiers import (
    resolve_success_contract,
    run_success_verifier,
)
from story_automator.core.sprint import sprint_status_epic, sprint_status_get
from story_automator.core.story_keys import normalize_story_key, sprint_status_file
from story_automator.core.utils import (
    atomic_write,
    ensure_dir,
    file_exists,
    get_project_root,
    iso_now,
    print_json,
    read_text,
    run_cmd,
)
from .orchestrator_epic_agents import (
    agents_build_action,
    agents_resolve_action,
    check_blocking_action,
    check_epic_complete_action,
    get_epic_stories_action,
    retro_agent_action,
)
from .orchestrator_parse import parse_output_action
from story_automator.core.telemetry_emitter import (
    TelemetryEmitter,
    emitter_for_project_root,
)
from story_automator.core.telemetry_events import (
    EscalationRaised,
    ReviewCycle,
    StoryCompleted,
    StoryFailed,
    StoryStarted,
)
from story_automator.core.run_identity import current_run_id
from story_automator.core.run_liveness import run_is_live
from story_automator.core.common import safe_int
from story_automator.core.bauto_bridge.hookbus_shim import HookBusShim
from ._audit_hooks import _audit_path_for, _maybe_audit_event
from .state import audit_state_change


logger = logging.getLogger(__name__)


# Module-level HookBusShim singleton (Path B / N6.3). Default-empty so the
# wiring is a no-op until a plugin (N6.4+) registers against it; tests
# inject their own bus by monkey-patching ``orchestrator._HOOK_BUS``.
_HOOK_BUS: HookBusShim = HookBusShim()


def get_hook_bus() -> HookBusShim:
    """Return the orchestrator's HookBusShim singleton.

    A future declarative-plugin layer (N6.4) will resolve manifests and
    register callbacks on this instance. Today the bus is empty by default
    so the hook-emit calls in this module are no-ops.
    """
    return _HOOK_BUS


# Mapping of lifecycle stage name → which "verify-step" verifier triggers
# the post_dev_phase emit. Today only ``session_exit`` (end of a dev cycle)
# qualifies; the dict keeps the wiring extensible without touching the
# call site when new verifier names land.
_VERIFY_STEP_POST_DEV_PHASE: frozenset[str] = frozenset({"session_exit"})


def _emit_hook_or_veto(event: str, context: dict) -> bool:
    """Emit ``event`` through the shim and return True if a blocking veto
    fired.

    Behavior is deliberately additive — with no hooks registered (the
    default) this returns False immediately. The caller is responsible
    for short-circuiting when True is returned (mirrors
    ``route_gate_verdict``'s halt-on-veto semantics).
    """
    bus = _HOOK_BUS
    # has_blocking_veto invokes each blocking callback exactly once; the
    # non-blocking emit below then re-fires the full chain (including
    # blocking callbacks). Per the shim contract this is intentional —
    # callbacks are pure observers from the bus's perspective. If a
    # plugin needs at-most-once semantics it can latch internally.
    if bus.has_blocking_veto(event, context):
        return True
    bus.emit(event, context)
    return False


def _hook_context(*, story_key: str = "", phase: str = "", branch: str = "",
                  agents: list[str] | None = None) -> dict:
    """Build a HookContext-shaped dict for shim emits.

    Plugins authored against bmad-auto's HookBus expect a stable, small
    payload — story_key, phase, branch, agents — so the shape lives in one
    place rather than scattered across emit sites.
    """
    return {
        "story_key": story_key,
        "phase": phase,
        "branch": branch,
        "agents": list(agents) if agents else [],
    }


def _veto_response(stage: str) -> int:
    """Print a structured veto error and return a non-zero exit code.

    Used by every emit site so the wire format is consistent across the
    six lifecycle stages — plugin-driven halts look identical regardless
    of which transition they intercepted.
    """
    print_json({"ok": False, "error": "plugin_veto", "stage": stage})
    return 1


def _telemetry_emitter() -> TelemetryEmitter:
    return emitter_for_project_root(get_project_root())


def _emit_safe(event) -> None:
    """Emit a telemetry event as a best-effort side channel.

    The emitter does filelock + fsync I/O; a failure (full disk, fsync error,
    lock contention) must degrade observability, not crash the command and
    break the orchestrator's jq parse of stdout. Mirrors the guard in
    record_cost.py. The swallowed failure is logged so a chronically broken
    telemetry sink leaves an operator trail instead of vanishing silently.
    """
    try:
        _telemetry_emitter().emit(event)
    except OSError as exc:
        logger.warning("telemetry emit failed for %s: %s", type(event).__name__, exc)


def _coerce_int(value: object, default: int) -> int | None:
    """Parse an int from CLI input. Empty/None -> default; non-numeric -> None.

    Returning None lets the caller emit a structured error instead of crashing
    with an uncaught ValueError on corrupted/non-numeric marker input.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return None


def _scalar_or_empty(value: object) -> str:
    """Render a frontmatter scalar, mapping YAML/JSON null sentinels to "".

    currentStory/currentStep are persisted as JSON null when unset; the simple
    frontmatter parser surfaces that as the literal string "null", which would
    otherwise leak into the human-facing state summary.
    """
    if value is None or value in ("null", "~"):
        return ""
    return str(value)


def cmd_orchestrator_helper(args: list[str]) -> int:
    if not args:
        return _usage(1)
    if args[0] in {"--help", "-h"}:
        return _usage(0)
    action = args[0]
    dispatch = {
        "sprint-status": _sprint_status,
        "parse-output": parse_output_action,
        "marker": _marker,
        "state-list": _state_list,
        "state-latest": _state_latest,
        "state-latest-incomplete": _state_latest_incomplete,
        "state-summary": _state_summary,
        "state-update": _state_update,
        "escalate": _escalate,
        "commit-ready": _commit_ready,
        "normalize-key": _normalize_key,
        "story-file-status": _story_file_status,
        "verify-step": _verify_step,
        "verify-code-review": _verify_code_review,
        "check-epic-complete": check_epic_complete_action,
        "get-epic-stories": get_epic_stories_action,
        "check-blocking": check_blocking_action,
        "agents-build": agents_build_action,
        "agents-resolve": agents_resolve_action,
        "retro-agent": retro_agent_action,
        "gate": _gate,
        "lineage": _lineage,
    }
    handler = dispatch.get(action)
    if handler is None:
        return _usage(1)
    return handler(args[1:])


def _usage(code: int) -> int:
    target = __import__("sys").stderr if code else __import__("sys").stdout
    print("Usage: orchestrator-helper <action> [args]", file=target)
    print("", file=target)
    print("Actions:", file=target)
    print("  sprint-status get <story_key>", file=target)
    print("  sprint-status exists", file=target)
    print("  sprint-status check-epic <epic>", file=target)
    print("  parse-output <file> <step>", file=target)
    print("  marker path", file=target)
    print(
        "  marker create --epic E --story S --remaining N --state-file F", file=target
    )
    print("  marker remove", file=target)
    print("  marker check", file=target)
    print("  marker heartbeat", file=target)
    print("  state-list <folder>", file=target)
    print("  state-latest <folder> [status]", file=target)
    print("  state-latest-incomplete <folder>", file=target)
    print("  state-summary <file>", file=target)
    print("  state-update <file> --set k=v", file=target)
    print("  escalate <trigger> <context>", file=target)
    print("  commit-ready <story_id>", file=target)
    print("  normalize-key <input> [--to id|key|prefix|json]", file=target)
    print("  story-file-status <story>", file=target)
    print(
        "  verify-step <step> <story_or_epic> [--state-file path] [--output-file path]",
        file=target,
    )
    print("  verify-code-review <story>", file=target)
    print("  check-epic-complete <epic> <story> [--state-file path]", file=target)
    print("  get-epic-stories <epic> [--state-file path]", file=target)
    print("  check-blocking <story_id>", file=target)
    print(
        "  agents-build --state-file path --complexity-file path --output path --config-json '{}'",
        file=target,
    )
    print(
        "  agents-resolve (--state-file path | --agents-file path) --story ID --task create|dev|auto|review",
        file=target,
    )
    print("  retro-agent --state-file path", file=target)
    print("  gate status [--state=<reason>]", file=target)
    print("  gate resume <gate_id>", file=target)
    print("  gate invalidate <story|epic>", file=target)
    print(
        "  lineage <show|entry|stats|verify|orphans> --project-root=<path> [args]",
        file=target,
    )
    return code


def _gate(args: list[str]) -> int:
    from .gate_cmd import gate_dispatch

    ctx = _hook_context(phase="gate")
    if _emit_hook_or_veto("pre_gate", ctx):
        return _veto_response("pre_gate")
    rc = gate_dispatch(args)
    if _emit_hook_or_veto("post_gate", ctx):
        return _veto_response("post_gate")
    return rc


def _lineage(args: list[str]) -> int:
    """Route to the C2 query CLI (read-only lineage ledger inspector)."""
    from .lineage_cmd import lineage_dispatch

    return lineage_dispatch(args)


def _sprint_status(args: list[str]) -> int:
    if not args:
        print(
            "Usage: orchestrator-helper sprint-status <get|exists|check-epic> [args]",
            file=__import__("sys").stderr,
        )
        return 1
    project_root = get_project_root()
    try:
        if args[0] == "get":
            if len(args) < 2:
                print(
                    "Usage: orchestrator-helper sprint-status get <story_key>",
                    file=__import__("sys").stderr,
                )
                return 1
            status = sprint_status_get(project_root, args[1])
            if not status.found and status.reason:
                print_json(
                    {"found": False, "status": status.status, "reason": status.reason}
                )
                return 0
            if not status.found:
                print_json({"found": False, "story": args[1], "status": "not_found"})
                return 0
            print_json(
                {
                    "found": True,
                    "story": status.story,
                    "status": status.status,
                    "done": status.done,
                }
            )
            return 0
        if args[0] == "exists":
            # JSON (not a bare string) so the skill steps can parse it with
            # `jq -r '.exists'`, consistent with the error path below and every
            # other sprint-status subcommand.
            print_json({"exists": file_exists(sprint_status_file(project_root))})
            return 0
        if args[0] == "check-epic":
            if len(args) < 2:
                print(
                    "Usage: orchestrator-helper sprint-status check-epic <epic>",
                    file=__import__("sys").stderr,
                )
                return 1
            stories, done = sprint_status_epic(project_root, args[1])
            if not stories:
                print_json(
                    {
                        "ok": False,
                        "epic": args[1],
                        "allStoriesDone": False,
                        "reason": "no_stories_found",
                        "count": 0,
                    }
                )
                return 0
            print_json(
                {
                    "ok": True,
                    "epic": args[1],
                    "allStoriesDone": done == len(stories),
                    "total": len(stories),
                    "done": done,
                    "count": len(stories),
                    "stories": stories,
                }
            )
            return 0
    except (OSError, ValueError) as exc:
        if args[0] == "get":
            print_json(
                {
                    "found": False,
                    "story": args[1] if len(args) > 1 else "",
                    "status": "error",
                    "reason": str(exc),
                }
            )
        elif args[0] == "exists":
            print_json({"ok": False, "exists": False, "error": str(exc)})
        elif args[0] == "check-epic":
            print_json(
                {
                    "ok": False,
                    "epic": args[1] if len(args) > 1 else "",
                    "allStoriesDone": False,
                    "reason": str(exc),
                    "count": 0,
                }
            )
        else:
            print_json({"ok": False, "error": str(exc)})
        return 1
    print(
        "Usage: orchestrator-helper sprint-status <get|exists|check-epic> [args]",
        file=__import__("sys").stderr,
    )
    return 1


def _marker(args: list[str]) -> int:
    if not args:
        print(
            "Usage: orchestrator-helper marker <path|create|remove|check|heartbeat> [args]",
            file=__import__("sys").stderr,
        )
        return 1
    project_root = Path(get_project_root())
    marker_file = active_marker_path(project_root)
    if args[0] == "path":
        print_json(
            {
                "file": str(marker_file),
                "entry": active_marker_project_entry(project_root),
            }
        )
        return 0
    if args[0] == "create":
        options = {
            "epic": "",
            "story": "",
            "remaining": "0",
            "state-file": "",
            "project-slug": "",
            "pid": "0",
            "heartbeat": "",
        }
        idx = 1
        while idx < len(args):
            key = args[idx].lstrip("-")
            if idx + 1 < len(args):
                options[key] = args[idx + 1]
                idx += 2
            else:
                idx += 1
        # Refuse to clobber a live run's marker: if one already exists with a
        # provably-fresh heartbeat, a second orchestrator (or a re-run that
        # raced an in-flight one) would silently overwrite it and double-drive
        # the same project. A stale/corrupt/timestamp-less marker is treated as
        # abandoned and may be overwritten, so a crash never permanently blocks
        # a legitimate re-run.
        if marker_file.exists():
            try:
                existing = json.loads(marker_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if run_is_live(existing):
                print_json(
                    {
                        "ok": False,
                        "error": "run_already_active",
                        "marker": str(marker_file),
                    }
                )
                return 1
        ensure_dir(marker_file.parent)
        remaining = _coerce_int(options["remaining"], 0)
        pid = _coerce_int(options["pid"], 0)
        if remaining is None or pid is None:
            print_json({"ok": False, "error": "invalid_int"})
            return 1
        payload = {
            "epic": options["epic"],
            "currentStory": options["story"],
            "storiesRemaining": remaining,
            "stateFile": options["state-file"],
            "createdAt": iso_now(),
            "heartbeat": options["heartbeat"] or iso_now(),
            "pid": pid,
            "projectSlug": options["project-slug"],
        }
        atomic_write(marker_file, json.dumps(payload, indent=2) + "\n")
        _emit_safe(
            StoryStarted(
                timestamp=iso_now(),
                run_id=current_run_id(get_project_root()),
                epic=options["epic"],
                story_key=options["story"],
                agent="",
                model="",
                complexity="",
            )
        )
        print(f"Marker created: {marker_file}")
        return 0
    if args[0] == "remove":
        if marker_file.exists():
            marker_file.unlink()
        print("Marker removed")
        return 0
    if args[0] == "check":
        if marker_file.exists():
            try:
                content = marker_file.read_text(encoding="utf-8")
            except OSError:
                print_json(
                    {"exists": True, "file": str(marker_file), "error": "marker_unreadable"}
                )
                return 1
            # json.dumps escapes the path so a Windows backslash (or any quote)
            # in the marker path can't produce invalid JSON on the status line.
            print(json.dumps({"exists": True, "file": str(marker_file)}))
            print(content, end="")
            return 0
        print('{"exists":false}')
        return 0
    if args[0] == "heartbeat":
        if not marker_file.exists():
            print("No marker file to update")
            return 1
        # A truncated/corrupt marker (crash mid-write, partial sync) must not
        # crash the supervising orchestrator loop with an uncaught decode error;
        # degrade to a recoverable structured error like runtime_policy._read_json.
        try:
            payload = json.loads(marker_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print_json({"exists": True, "error": "marker_corrupt"})
            return 1
        if not isinstance(payload, dict):
            print_json({"exists": True, "error": "marker_corrupt"})
            return 1
        payload["heartbeat"] = iso_now()
        atomic_write(marker_file, json.dumps(payload, indent=2) + "\n")
        print(f"Heartbeat updated: {payload['heartbeat']}")
        return 0
    print(
        "Usage: orchestrator-helper marker <path|create|remove|check|heartbeat> [args]",
        file=__import__("sys").stderr,
    )
    return 1


def _state_list(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found", "files": []})
        return 1
    files = []
    for path in sorted(Path(args[0]).glob("orchestration-*.md")):
        files.append(
            {
                "path": str(path),
                "status": find_frontmatter_value(path, "status") or "unknown",
                "lastUpdated": find_frontmatter_value(path, "lastUpdated") or "unknown",
            }
        )
    print_json({"ok": True, "files": files})
    return 0


def _state_latest(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found"})
        return 1
    status_filter = args[1] if len(args) > 1 else ""
    matches = []
    for path in Path(args[0]).glob("orchestration-*.md"):
        status = find_frontmatter_value(path, "status")
        if status_filter and status != status_filter:
            continue
        matches.append((find_frontmatter_value(path, "lastUpdated"), str(path)))
    if not matches:
        print_json({"ok": False, "error": "no_match"})
        return 0
    updated, path = max(matches)
    print_json({"ok": True, "path": path, "lastUpdated": updated})
    return 0


def _state_latest_incomplete(args: list[str]) -> int:
    if not args or not Path(args[0]).is_dir():
        print_json({"ok": False, "error": "folder_not_found"})
        return 1
    matches = []
    for path in Path(args[0]).glob("orchestration-*.md"):
        status = find_frontmatter_value(path, "status")
        if status == "COMPLETE":
            continue
        matches.append((find_frontmatter_value(path, "lastUpdated"), status, str(path)))
    if not matches:
        print_json({"ok": False, "error": "no_incomplete_state"})
        return 0
    updated, status, path = max(matches)
    print_json({"ok": True, "path": path, "lastUpdated": updated, "status": status})
    return 0


def _state_summary(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    fields = parse_simple_frontmatter(read_text(args[0]))
    snapshot_file, snapshot_hash, policy_version, legacy_policy, policy_error = (
        summarize_state_policy_fields(
            fields,
            project_root=get_project_root(),
        )
    )
    payload = {
        "ok": True,
        "epic": str(fields.get("epic") or ""),
        "epicName": str(fields.get("epicName") or ""),
        "currentStory": _scalar_or_empty(fields.get("currentStory")),
        "currentStep": _scalar_or_empty(fields.get("currentStep")),
        "status": str(fields.get("status") or ""),
        "lastUpdated": str(fields.get("lastUpdated") or ""),
        "policyVersion": policy_version,
        "policySnapshotFile": snapshot_file,
        "policySnapshotHash": snapshot_hash,
        "legacyPolicy": legacy_policy,
        "lastAction": extract_last_action(args[0]),
    }
    if policy_error:
        payload["policyError"] = policy_error
    print_json(payload)
    return 0


def _state_update(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    fields_before = parse_simple_frontmatter(text)
    updated: list[str] = []
    idx = 1
    while idx < len(args):
        if args[idx] == "--set" and idx + 1 < len(args):
            operand = args[idx + 1]
            if "=" not in operand:
                # A `--set key` with no `=value` would unpack-crash; surface the
                # malformed operand as a structured error instead of a traceback.
                print_json(
                    {"ok": False, "error": "invalid_set_operand", "operand": operand}
                )
                return 1
            key, value = operand.split("=", 1)
            replaced, count = re.subn(
                rf"(?m)^{re.escape(key)}:.*$",
                lambda m, k=key, v=value: f"{k}: {v}",
                text,
            )
            if count:
                text = replaced
                updated.append(key)
            idx += 2
            continue
        idx += 1
    if not updated:
        print_json({"ok": False, "error": "keys_not_found", "updated": []})
        return 1
    # Atomic write: a plain write_text truncates the live orchestration-*.md
    # state doc in place, so a crash mid-write or a concurrent reader can see a
    # half-written/empty state document. Every other durable write in this
    # codebase goes through atomic_write (temp file + fsync + os.replace).
    # (Supersedes eb0b964's bare atomic_write — adds the M04 audit-trail hook.)
    atomic_write(Path(args[0]), text)

    # REQ-12: audit after the write succeeds. Failures from append are
    # re-raised by audit_state_change so the state mutation is never
    # silently divorced from its audit record.
    if "status" in updated:
        fields_after = parse_simple_frontmatter(text)
        try:
            policy = load_runtime_policy(get_project_root(), state_file=args[0])
        except (FileNotFoundError, PolicyError):
            policy = {}
        audit_state_change(
            policy,
            _audit_path_for(get_project_root()),
            story=str(fields_before.get("currentStory") or ""),
            from_status=str(fields_before.get("status") or ""),
            to_status=str(fields_after.get("status") or ""),
            correlation_id=f"state-update:{Path(args[0]).name}",
        )

    print_json({"ok": True, "updated": updated})
    return 0


def _escalate(args: list[str]) -> int:
    trigger = args[0] if args else ""
    context = args[1] if len(args) > 1 else ""
    state_file = ""
    idx = 2
    try:
        while idx < len(args):
            if args[idx] == "--state-file":
                state_file = _flag_value(args, idx, "--state-file")
                idx += 2
                continue
            idx += 1
    except PolicyError as exc:
        # Legacy contract: arg-parse PolicyError → escalate=True. No audit
        # — we never loaded a policy, so the gate state is unknown.
        print_json({"escalate": True, "reason": str(exc)})
        return 0
    try:
        # Escalation only reads numeric workflow config (review.maxCycles /
        # crash.maxRetries), so skip skill/template/schema asset resolution.
        # Otherwise a transient or post-upgrade unresolvable skill turns a
        # recoverable crash/review retry into an immediate hard escalation.
        policy = load_runtime_policy(get_project_root(), state_file=state_file, resolve_assets=False)
    except (FileNotFoundError, PolicyError) as exc:
        # Legacy contract: policy-load failure → escalate=True. Same
        # rationale as above; do not audit when we have no policy.
        print_json({"escalate": True, "reason": str(exc)})
        return 0

    if trigger == "review-loop":
        cycles = _parse_context_int(context, "cycles")
        limit = review_max_cycles(policy)
        if cycles >= limit:
            result: dict = {
                "escalate": True,
                "reason": f"Review loop exceeded max cycles ({cycles}/{limit})",
            }
        else:
            result = {"escalate": False}
    elif trigger == "session-crash":
        retries = _parse_context_int(context, "retries")
        limit = crash_max_retries(policy)
        if retries >= limit:
            story = _parse_context_str(context, "story")
            session = _parse_context_str(context, "session")
            norm = normalize_story_key(get_project_root(), story) if story else None
            epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
            _emit_safe(
                StoryFailed(
                    timestamp=iso_now(),
                    run_id=current_run_id(get_project_root()),
                    epic=epic,
                    story_key=story,
                    error_class="session_crash",
                    reason=f"Session crashed after {retries} retries",
                    attempts=retries,
                    final_session=session,
                )
            )
            result = {
                "escalate": True,
                "reason": f"Session crashed after {retries} retries",
            }
        else:
            result = {"escalate": False, "action": "retry"}
    elif trigger == "story-validation":
        created = _parse_context_int(context, "created")
        if created != 1:
            result = {
                "escalate": True,
                "reason": "No story file created"
                if created == 0
                else f"Runaway creation: {created} files",
            }
        else:
            result = {"escalate": False}
    else:
        result = {"escalate": False, "reason": "Unknown trigger"}

    # REQ-11: audit before the user-visible print, but only on actual
    # escalations. A non-escalating dispatch is not a security event.
    if result.get("escalate"):
        _maybe_audit_event(
            policy,
            _audit_path_for(get_project_root()),
            EscalationRaised(
                trigger=trigger,
                reason=str(result.get("reason", "")),
                correlation_id=_escalate_correlation_id(state_file, trigger),
            ),
        )

    print_json(result)
    return 0


def _commit_ready(args: list[str]) -> int:
    if not args:
        print_json({"ready": False, "reason": "story_id required"})
        return 1
    project_root = get_project_root()
    try:
        status = sprint_status_get(project_root, args[0])
    except (OSError, ValueError) as exc:
        print_json({"ready": False, "reason": str(exc), "story": args[0]})
        return 1
    if status.done:
        # pre_commit fires before we touch git so a plugin can veto a
        # commit-readiness check without race-conditions against the
        # working tree. No-op when no hooks are registered.
        if _emit_hook_or_veto(
            "pre_commit",
            _hook_context(story_key=args[0], phase="commit"),
        ):
            return _veto_response("pre_commit")
        out, code = run_cmd("git", "-C", project_root, "status", "--porcelain")
        if code != 0:
            # git missing or not a repo: distinguish from a clean tree so the
            # operator gets a real error instead of "No uncommitted changes".
            print_json({"ready": False, "reason": "git_status_failed", "exit_code": code, "story": args[0]})
            return 0
        if out.strip():
            norm = normalize_story_key(project_root, args[0])
            epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
            _emit_safe(
                StoryCompleted(
                    timestamp=iso_now(),
                    run_id=current_run_id(get_project_root()),
                    epic=epic,
                    story_key=args[0],
                    duration_s=0.0,
                    cost_usd=0.0,
                    tokens_in=0,
                    tokens_out=0,
                    attempts=1,
                )
            )
            print_json(
                {
                    "ready": True,
                    "story": args[0],
                    "status": "done",
                    "uncommitted_changes": True,
                }
            )
            return 0
        print_json(
            {"ready": False, "reason": "No uncommitted changes", "story": args[0]}
        )
        return 0
    print_json(
        {
            "ready": False,
            "reason": "Story not done yet",
            "story": args[0],
            "current_status": status.status,
        }
    )
    return 0


def _normalize_key(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "input required"})
        return 1
    fmt = "json"
    if len(args) >= 3 and args[1] == "--to":
        fmt = args[2]
    try:
        result = normalize_story_key(get_project_root(), args[0])
    except (OSError, ValueError) as exc:
        print_json({"ok": False, "error": str(exc), "input": args[0]})
        return 1
    if result is None:
        print_json({"ok": False, "error": "unrecognized format", "input": args[0]})
        return 1
    if fmt == "id":
        print(result.id)
    elif fmt == "prefix":
        print(result.prefix)
    elif fmt == "key":
        print(result.key)
    else:
        print_json(
            {"ok": True, "id": result.id, "prefix": result.prefix, "key": result.key}
        )
    return 0


def _story_file_status(args: list[str]) -> int:
    if not args:
        print_json({"ok": False, "error": "story input required"})
        return 1
    try:
        norm = normalize_story_key(get_project_root(), args[0])
        if norm is None:
            print_json(
                {
                    "ok": False,
                    "error": "could not normalize story key",
                    "input": args[0],
                }
            )
            return 1
        matches = sorted(
            implementation_artifacts_dir(get_project_root()).glob(f"{norm.prefix}-*.md")
        )
    except (OSError, ValueError) as exc:
        print_json({"ok": False, "error": str(exc), "input": args[0]})
        return 1
    if not matches:
        print_json(
            {"ok": False, "error": "story file not found", "prefix": norm.prefix}
        )
        return 1
    title = find_frontmatter_value_case(matches[0], "Title") or extract_title(read_text(matches[0]))
    print_json(
        {
            "ok": True,
            "story_key": norm.key,
            "file": str(matches[0]),
            "status": find_frontmatter_value_case(matches[0], "Status") or "unknown",
            "title": title,
        }
    )
    return 0


def _verify_code_review(args: list[str]) -> int:
    if not args:
        print_json({"verified": False, "reason": "story_key_required"})
        return 1
    state_file = ""
    tail = args[1:]
    try:
        idx = 0
        while idx < len(tail):
            if tail[idx] == "--state-file":
                state_file = _flag_value(tail, idx, "--state-file")
                idx += 2
                continue
            idx += 1
    except PolicyError as exc:
        print_json(
            {
                "verified": False,
                "reason": "review_contract_invalid",
                "input": args[0],
                "error": str(exc),
            }
        )
        return 1
    review_ctx = _hook_context(story_key=args[0], phase="review")
    if _emit_hook_or_veto("pre_review", review_ctx):
        return _veto_response("pre_review")
    payload = verify_code_review_completion(
        get_project_root(), args[0], state_file=state_file or None
    )
    if _emit_hook_or_veto("post_review", review_ctx):
        return _veto_response("post_review")
    norm = normalize_story_key(get_project_root(), args[0])
    epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
    _emit_safe(
        ReviewCycle(
            timestamp=iso_now(),
            run_id=current_run_id(get_project_root()),
            epic=epic,
            story_key=args[0],
            cycle_num=int(payload.get("cycle") or 0),
            issues_found=int(payload.get("issuesFound") or 0),
            blocking=not bool(payload.get("verified")),
        )
    )
    print_json(payload)
    return 0 if bool(payload.get("verified")) else 1


def _verify_step(args: list[str]) -> int:
    if len(args) < 2:
        print_json({"verified": False, "reason": "step_and_story_required"})
        return 1
    step, story_key = args[:2]
    state_file = ""
    output_file = ""
    tail = args[2:]
    try:
        idx = 0
        while idx < len(tail):
            arg = tail[idx]
            if arg in {"--state-file", "--output-file"}:
                if (
                    idx + 1 >= len(tail)
                    or not tail[idx + 1].strip()
                    or tail[idx + 1].startswith("--")
                ):
                    raise PolicyError(f"{arg} requires a value")
                if arg == "--state-file":
                    state_file = tail[idx + 1]
                else:
                    output_file = tail[idx + 1]
                idx += 2
                continue
            idx += 1
        contract = resolve_success_contract(
            get_project_root(), step, state_file=state_file or None
        )
        verifier = str(contract.get("verifier") or "").strip()
        if not verifier:
            raise PolicyError(f"missing success verifier for {step}")
        payload = run_success_verifier(
            verifier,
            project_root=get_project_root(),
            story_key=story_key,
            output_file=output_file,
            contract=contract,
        )
        exit_code = 0
        # post_dev_phase fires only when the dev session-exit verifier
        # ran successfully; other verifiers (review_completion,
        # epic_complete, ...) belong to different lifecycle stages or
        # have their own emit sites.
        if verifier in _VERIFY_STEP_POST_DEV_PHASE:
            ctx = _hook_context(story_key=story_key, phase="dev")
            if _emit_hook_or_veto("post_dev_phase", ctx):
                return _veto_response("post_dev_phase")
    except (FileNotFoundError, OSError, PolicyError, ValueError) as exc:
        payload = {
            "verified": False,
            "step": step,
            "input": story_key,
            "reason": "verifier_contract_invalid",
            "error": str(exc),
        }
        exit_code = 1
    print_json(payload)
    return exit_code


def _parse_context_int(context: str, key: str) -> int:
    match = re.search(rf"(?:^|\s){re.escape(key)}=(\d+)", context)
    return int(match.group(1)) if match else 0


def _parse_context_str(context: str, key: str) -> str:
    match = re.search(rf"(?:^|\s){re.escape(key)}=(\S+)", context)
    return match.group(1) if match else ""


def _escalate_correlation_id(state_file: str, trigger: str) -> str:
    """Stable correlation id for one escalation event.

    Combines the state-file basename (or empty) with the trigger so the
    audit record can be cross-referenced against the orchestration log.
    """
    base = Path(state_file).name if state_file else ""
    return f"escalate:{trigger}:{base}"


def _flag_value(args: list[str], idx: int, flag: str) -> str:
    if (
        idx + 1 >= len(args)
        or not args[idx + 1].strip()
        or args[idx + 1].startswith("--")
    ):
        raise PolicyError(f"{flag} requires a value")
    return args[idx + 1]
