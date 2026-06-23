"""``story-automator calibration`` CLI + C5 self-improving-gate subcommands.

Bare ``calibration`` wraps the M08 tracker and is BYTE-IDENTICAL to
the pre-C5 surface — pinned by ``tests/fixtures/calibration_bare_v1.expected.json``.
C5 adds five subcommands: ``propose`` / ``list-proposals`` / ``show``
/ ``apply`` / ``reject``. Apply lives behind ``_cmd_apply``'s
``confirm: str`` signature — the audit-floor structural-recognition
pattern the ``ThresholdApplyIsolationInvariant`` AST scan keys off.

Exit-code contract (matches ``commands/lineage_cmd.py``): 0 success,
1 domain error, 2 argparse / missing-flag.

Hard rule: ``print_json`` MUST NOT take ``sort_keys=True`` — that
would re-order the bare M08 payload and break the golden fixture.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Callable

from ..core.calibration import (
    build_calibration,
    format_calibration_report,
    lookup_success_rate,
)
from ..core.common import print_json
from ..core.innovation.threshold_apply import (
    ThresholdApplyError,
    apply_threshold_proposal,
)
from ..core.innovation.threshold_decisions import latest_decision_for
from ..core.innovation.threshold_proposer import ThresholdProposer
from ..core.utils import get_project_root

__all__ = [
    "cmd_calibration",
]


_SUBCOMMANDS: frozenset[str] = frozenset({"propose", "list-proposals", "show", "apply", "reject"})


# ---- Bare invocation (UNCHANGED — pinned by golden fixture) ----


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


def _cmd_bare(args: list[str]) -> int:
    """Original M08 calibration table emitter — DO NOT change the shape.

    Byte-pinned by ``test_bare_invocation_byte_identical``; any
    reordering or new field will break the golden fixture.
    """
    params = _flag_map(args)
    events_path = params.get("events") or str(
        Path(get_project_root()) / "telemetry" / "events.jsonl"
    )
    try:
        table = build_calibration(events_path)
    except OSError as exc:
        # A real I/O error (e.g., PermissionError on an existing ledger) would
        # emit a stack trace to stderr — skill markdown parses stdout JSON via
        # jq and would silently treat non-JSON as no calibration data. Surface
        # it as a structured failure with ok=false instead.
        print_json({"ok": False, "error": "io_error", "detail": str(exc)})
        return 1
    payload: dict = {
        "ok": True,
        "source_path": table.source_path,
        "generated_at": table.generated_at,
        "total_events_scanned": table.total_events_scanned,
        "entries": [
            {
                "model_id": entry.model_id,
                "task_kind": entry.task_kind,
                "success_rate": entry.success_rate,
                "sample_count": entry.sample_count,
                "last_seen_iso": entry.last_seen_iso,
            }
            for _, entry in sorted(table.entries.items())
        ],
    }
    model = params.get("model")
    task = params.get("task")
    if model and task:
        payload["lookup"] = {
            "model_id": model,
            "task_kind": task,
            "success_rate": lookup_success_rate(table, model, task),
        }
    # --report is a boolean flag with no value, so _flag_map (which only
    # captures --flag VALUE pairs) will not record it; detect it directly.
    if "--report" in args:
        payload["report"] = format_calibration_report(table)
    print_json(payload)
    return 0


# ---- Flag helpers (subcommand dispatchers) ----


def _arg_value(args: list[str], flag: str) -> str | None:
    """Return the value following ``flag`` in ``args``, or ``None``."""
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return args[index + 1]
    return None


def _has_flag(args: list[str], flag: str) -> bool:
    return flag in args


_PAIR_FLAGS: frozenset[str] = frozenset(
    {
        "--project-root",
        "--window",
        "--ttl-hours",
        "--proposal-id",
        "--confirm",
        "--reason",
        "--operator-id",
        "--events",
        "--model",
        "--task",
    }
)


def _first_positional(args: list[str]) -> str | None:
    """First non-flag token (skips ``--flag VAL`` pairs in ``_PAIR_FLAGS``)."""
    skip_next = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("--"):
            if tok in _PAIR_FLAGS:
                skip_next = True
            continue
        return tok
    return None


def _project_root_path(args: list[str]) -> Path:
    """Resolve ``--project-root`` if given, else the env-derived default."""
    explicit = _arg_value(args, "--project-root")
    if explicit:
        return Path(explicit).resolve()
    return Path(get_project_root()).resolve()


def _make_proposer(args: list[str]) -> ThresholdProposer:
    """Build a :class:`ThresholdProposer` honoring ``--window`` / ``--ttl-hours``."""
    kwargs: dict[str, Any] = {}
    window = _arg_value(args, "--window")
    if window is not None:
        try:
            kwargs["min_evidence_window"] = int(window)
        except ValueError as err:
            raise _CliInputError(f"invalid --window: {window!r}") from err
    ttl = _arg_value(args, "--ttl-hours")
    if ttl is not None:
        try:
            kwargs["ttl_hours"] = int(ttl)
        except ValueError as err:
            raise _CliInputError(f"invalid --ttl-hours: {ttl!r}") from err
    return ThresholdProposer(**kwargs)


class _CliInputError(ValueError):
    """Raised for invalid CLI inputs that map to exit-code 2."""


# ---- Subcommand handlers ----


def _cmd_propose(args: list[str]) -> int:
    """Run the proposer against the latest persisted gate file."""
    try:
        proposer = _make_proposer(args)
    except _CliInputError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 2
    project_root = _project_root_path(args)
    gate_file = _load_latest_gate_file(project_root)
    if gate_file is None:
        # No persisted gate file ⇒ no signal to observe; surface as a
        # non-proposal success so jq consumers see a stable shape.
        print_json({"ok": True, "proposal": None})
        return 0
    try:
        proposal = proposer.observe_gate(project_root, gate_file)
    except Exception as exc:  # noqa: BLE001 - JSON-contract backstop
        print_json({"ok": False, "error": "observe_gate_failed", "detail": str(exc)})
        return 1
    if proposal is None:
        print_json({"ok": True, "proposal": None})
        return 0
    payload = {
        "ok": True,
        "proposal_id": proposal.proposal_id,
        "confirm_slug": proposal.confirm_slug,
        "proposal": proposal.to_dict(),
    }
    print_json(payload)
    return 0


def _cmd_list_proposals(args: list[str]) -> int:
    """Enumerate proposals; include ``confirm_failed`` rows when asked."""
    proposer = ThresholdProposer()
    project_root = _project_root_path(args)
    include_failed = _has_flag(args, "--include-failed")
    try:
        all_proposals = proposer.list_proposals(project_root)
    except Exception as exc:  # noqa: BLE001 - JSON-contract backstop
        print_json({"ok": False, "error": "list_failed", "detail": str(exc)})
        return 1
    rows: list[dict[str, Any]] = []
    for proposal in all_proposals:
        latest = latest_decision_for(project_root, proposal.proposal_id)
        latest_action = latest.action if latest is not None else None
        if not include_failed and latest_action == "confirm_failed":
            # Operators tuning a flaky slug shouldn't see the failure
            # noise unless they opt in (spec §4 list-proposals box).
            continue
        rows.append(
            {
                "proposal_id": proposal.proposal_id,
                "confirm_slug": proposal.confirm_slug,
                "target_module": proposal.target_module,
                "target_symbol": proposal.target_symbol,
                "current_value": proposal.current_value,
                "proposed_value": proposal.proposed_value,
                "created_at_iso": proposal.created_at_iso,
                "latest_decision": latest_action,
            }
        )
    print_json({"ok": True, "proposals": rows})
    return 0


def _cmd_show(args: list[str]) -> int:
    """Render one proposal as JSON + bounded unified-diff."""
    proposal_id = _first_positional(args)
    if not proposal_id:
        print_json({"ok": False, "error": "missing proposal_id"})
        return 2
    proposer = ThresholdProposer()
    project_root = _project_root_path(args)
    try:
        proposal = proposer.load_proposal(project_root, proposal_id)
    except FileNotFoundError:
        print_json({"ok": False, "error": "PROPOSAL_NOT_FOUND", "proposal_id": proposal_id})
        return 1
    include_slug = _has_flag(args, "--include-slug")
    proposal_dict = proposal.to_dict()
    if not include_slug:
        proposal_dict["confirm_slug"] = "<redacted>"
    diff_text = _render_diff_for_proposal(proposal)
    applied_record = _maybe_load_applied_record(project_root, proposal_id)
    payload = {
        "ok": True,
        "proposal": proposal_dict,
        "diff": diff_text,
        "applied_record": applied_record,
    }
    print_json(payload)
    return 0


def _cmd_apply(args: list[str], *, confirm: str) -> int:
    """Apply a proposal after operator confirmation.

    The ``confirm: str`` parameter is the structural exemption key for
    ``ThresholdApplyIsolationInvariant`` (spec §7.5) — any top-level
    FunctionDef under ``commands/`` whose body calls
    :func:`apply_threshold_proposal` AND has ``confirm: str`` as its
    first non-self arg is rename-proof exempted from the isolation scan.
    """
    proposal_id = _arg_value(args, "--proposal-id")
    if not proposal_id:
        print_json({"ok": False, "error": "missing --proposal-id"})
        return 2
    operator_id = _arg_value(args, "--operator-id") or "local"
    project_root = _project_root_path(args)
    try:
        record = apply_threshold_proposal(
            project_root,
            proposal_id,
            confirm=confirm,
            operator_id=operator_id,
        )
    except ThresholdApplyError as exc:
        payload: dict[str, Any] = {"ok": False, "error": exc.code}
        if exc.hint:
            payload["hint"] = exc.hint
        print_json(payload)
        return 1
    print_json(
        {
            "ok": True,
            "applied": True,
            "target_file": record.target_file,
            "proposal_id": record.proposal_id,
        }
    )
    return 0


def _cmd_reject(args: list[str]) -> int:
    """Append a ``reject`` decision against ``proposal_id``."""
    proposal_id = _arg_value(args, "--proposal-id")
    if not proposal_id:
        print_json({"ok": False, "error": "missing --proposal-id"})
        return 2
    reason = _arg_value(args, "--reason")
    if reason is None:
        print_json({"ok": False, "error": "missing --reason"})
        return 2
    operator_id = _arg_value(args, "--operator-id") or "local"
    proposer = ThresholdProposer(operator_id=operator_id)
    project_root = _project_root_path(args)
    try:
        proposer.reject_proposal(project_root, proposal_id, reason, operator_id)
    except FileNotFoundError:
        print_json({"ok": False, "error": "PROPOSAL_NOT_FOUND", "proposal_id": proposal_id})
        return 1
    print_json({"ok": True, "rejected": True, "proposal_id": proposal_id})
    return 0


# ---- Diff rendering (spec §6.1) ----


def _render_diff(before_source: str, after_source: str, lineno: int) -> str:
    """Bounded ASCII-only unified diff (spec §6.1).

    Up to 7 lines, LF only, deterministic, ASCII only. Non-ASCII content
    surfaces as ``UnicodeEncodeError`` → returns ``""``. The truncation
    is HUNK-AWARE: post-impl review found a naive ``[:7]`` slice could
    cut between the first ``-`` removal and its matching ``+`` addition
    (operator saw what was removed but never what replaced it). The
    helper :func:`_bound_unified_diff` guarantees both sides survive.
    """
    _ = lineno  # part of the public signature; reserved for future hunk-shift
    before_lines = before_source.splitlines(keepends=False)
    after_lines = after_source.splitlines(keepends=False)
    all_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="before",
            tofile="after",
            lineterm="",
            n=3,
        )
    )
    rendered = _bound_unified_diff(all_lines, max_lines=7)
    text = "\n".join(rendered)
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return ""
    return text


def _bound_unified_diff(lines: list[str], *, max_lines: int) -> list[str]:
    """Hunk-aware cap on a ``difflib.unified_diff`` output (post-impl fix).

    Preserves the file-header pair, the first ``@@`` hunk header, AND
    the first ``-``/``+`` change pair; greedy-fills remaining budget
    with surrounding context lines.
    """
    if len(lines) <= max_lines:
        return lines
    # File header pair (leading ``---`` / ``+++``).
    header: list[str] = []
    cursor = 0
    while cursor < min(2, len(lines)) and (
        lines[cursor].startswith("---") or lines[cursor].startswith("+++")
    ):
        header.append(lines[cursor])
        cursor += 1
    # First hunk header.
    hunk_idx = next((i for i in range(cursor, len(lines)) if lines[i].startswith("@@")), None)
    if hunk_idx is None:
        return (header + lines[cursor:])[:max_lines]
    # First removal + first addition AFTER the hunk header.
    first_minus = next(
        (
            i
            for i in range(hunk_idx + 1, len(lines))
            if lines[i].startswith("-") and not lines[i].startswith("---")
        ),
        None,
    )
    first_plus = next(
        (
            i
            for i in range(hunk_idx + 1, len(lines))
            if lines[i].startswith("+") and not lines[i].startswith("+++")
        ),
        None,
    )
    keep: set[int] = {hunk_idx}
    if first_minus is not None:
        keep.add(first_minus)
    if first_plus is not None:
        keep.add(first_plus)
    budget = max_lines - len(header) - len(keep)
    if budget < 0:
        return (header + [lines[i] for i in sorted(keep)])[:max_lines]
    # Greedy outward context fill (trailing first, then leading).
    lo, hi = min(keep), max(keep)
    while budget > 0:
        added = False
        if hi + 1 < len(lines) and (hi + 1) not in keep:
            keep.add(hi + 1)
            hi += 1
            budget -= 1
            added = True
            if budget == 0:
                break
        if lo - 1 > hunk_idx and (lo - 1) not in keep:
            keep.add(lo - 1)
            lo -= 1
            budget -= 1
            added = True
        if not added:
            break
    return (header + [lines[i] for i in sorted(keep)])[:max_lines]


def _render_diff_for_proposal(proposal: Any) -> str:
    """Synthesize a semantic before/after for the leaf splice (no live read)."""
    selector = dict(proposal.selector)
    if selector.get("kind") == "dict_tuple_element":
        key = selector.get("key", "?")
        index = selector.get("index", 0)
        before = f'{proposal.target_symbol}["{key}"][{index}] = {proposal.current_value!r}'
        after = f'{proposal.target_symbol}["{key}"][{index}] = {proposal.proposed_value!r}'
    else:
        before = f"{proposal.target_symbol} = {proposal.current_value!r}"
        after = f"{proposal.target_symbol} = {proposal.proposed_value!r}"
    return _render_diff(before, after, 1)


def _maybe_load_applied_record(project_root: Path, proposal_id: str) -> dict[str, Any] | None:
    """Return the persisted ``AppliedThresholdRecord`` JSON, or ``None``."""
    path = (
        Path(project_root)
        / "_bmad"
        / "calibration"
        / "proposals"
        / f"{proposal_id}.applied"
        / "record.json"
    )
    return _read_json_or_none(path)


def _load_latest_gate_file(project_root: Path) -> dict[str, Any] | None:
    """Return the most recently persisted gate file as a dict, or ``None``."""
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    if not verdicts_dir.is_dir():
        return None
    candidates = sorted(
        (p for p in verdicts_dir.iterdir() if p.suffix == ".json" and p.is_file()),
        key=lambda p: p.name,
    )
    return _read_json_or_none(candidates[-1]) if candidates else None


def _read_json_or_none(path: Path) -> dict[str, Any] | None:
    """Best-effort JSON read; silently degrades to ``None`` on any error."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---- --help rendering ----


_HELP_TEXT = """\
story-automator calibration [subcommand] [args]

Without a subcommand, prints the M08 success-rate calibration table.

Subcommands:
  propose          [--window N] [--ttl-hours H] [--project-root PATH]
  list-proposals   [--include-failed] [--project-root PATH]
  show <id>        [--include-slug] [--project-root PATH]
  apply            --proposal-id <id> --confirm <slug> [--project-root PATH]
  reject           --proposal-id <id> --reason <note> [--project-root PATH]
"""


def _print_help() -> int:
    print(_HELP_TEXT, end="")
    return 0


# ---- Dispatcher ----


_DISPATCH: dict[str, Callable[[list[str]], int]] = {
    "propose": _cmd_propose,
    "list-proposals": _cmd_list_proposals,
    "show": _cmd_show,
    "reject": _cmd_reject,
}


def _apply_dispatch(args: list[str]) -> int:
    """Bridge to ``_cmd_apply``'s kw-only ``confirm`` parameter."""
    confirm = _arg_value(args, "--confirm")
    if not confirm:
        print_json({"ok": False, "error": "missing --confirm"})
        return 2
    return _cmd_apply(args, confirm=confirm)


def cmd_calibration(args: list[str]) -> int:
    """Entry point for ``story-automator calibration``.

    Bare (no subcommand) → M08 surface. ``--help`` → help text.
    Subcommand → handler. Unknown positional → exit 2.
    """
    if not args or args[0].startswith("--") or args[0].startswith("-"):
        if args and args[0] in ("-h", "--help"):
            return _print_help()
        return _cmd_bare(args)

    head = args[0]
    rest = args[1:]
    if head not in _SUBCOMMANDS:
        print_json({"ok": False, "error": f"unknown subcommand: {head!r}"})
        return 2
    if any(tok in ("-h", "--help") for tok in rest):
        return _print_help()
    if head == "apply":
        return _apply_dispatch(rest)
    return _DISPATCH[head](rest)
