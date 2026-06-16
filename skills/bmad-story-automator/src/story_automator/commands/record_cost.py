"""``story-automator record-cost`` CLI subcommand — the cost INGESTION primitive.

Closes critic Gap 3b: the budget-ceiling safety gate is structurally inert
because ``CostCharged`` is never emitted, so spent is always 0 and the
ceiling-check always ALLOWs. This command constructs a
``core.telemetry_events.CostCharged`` event from CLI flags and emits it via
``core.telemetry_emitter.emitter_for_project_root(get_project_root())`` so that
``ceiling-check`` and ``TelemetryReader.cost_by_epic`` become functional.

Read-only with respect to source state: it appends one JSONL row to the
project's ``telemetry/events.jsonl`` (the same emitter every other wiring call
site uses) and prints a single compact JSON object describing the record so
BMAD step markdown can branch via ``jq``. Mirrors the ``_flag_map`` /
``print_json`` / ``_telemetry_emitter`` patterns from ``ceiling_check.py`` and
``orchestrator.py``.
"""

from __future__ import annotations

from ..core.common import iso_now, print_json
from ..core.telemetry_emitter import TelemetryEmitter, emitter_for_project_root
from ..core.telemetry_events import CostCharged
from ..core.utils import get_project_root


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


def _telemetry_emitter() -> TelemetryEmitter:
    return emitter_for_project_root(get_project_root())


def _safe_int(value: str, default: int = 0) -> int:
    """Parse an optional integer flag, falling back to ``default``.

    Token counts are advisory metadata on the cost row; a malformed value
    should not block the cost ingestion (the cost figure is what drives the
    ceiling gate). The required, validated field is ``--cost-usd``.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def cmd_record_cost(args: list[str]) -> int:
    """Entry point for ``story-automator record-cost`` (Gap 3b ingestion).

    Required flags:
        --epic <epic>
        --story-key <story_key>
        --cost-usd <float>
    Optional flags:
        --phase <phase>       (default "")
        --tokens-in <int>     (default 0)
        --tokens-out <int>    (default 0)
        --model <model>       (default "")
        --run-id <run_id>     (default ""; emitter stamps if configured)
        --now <iso8601>       (default ``iso_now()``)
    """
    params = _flag_map(args)
    epic = params.get("epic", "")
    story_key = params.get("story-key", "")
    if not epic or not story_key:
        print_json({"ok": False, "error": "missing_args"})
        return 1

    raw_cost = params.get("cost-usd", "")
    try:
        cost_usd = float(raw_cost)
    except (TypeError, ValueError):
        print_json({"ok": False, "error": "invalid_cost", "detail": raw_cost})
        return 1

    event = CostCharged(
        timestamp=params.get("now") or iso_now(),
        run_id=params.get("run-id", ""),
        epic=epic,
        story_key=story_key,
        phase=params.get("phase", ""),
        cost_usd=cost_usd,
        tokens_in=_safe_int(params.get("tokens-in", "")),
        tokens_out=_safe_int(params.get("tokens-out", "")),
        model=params.get("model", ""),
    )

    try:
        _telemetry_emitter().emit(event)
    except OSError as exc:
        # The emitter performs filesystem I/O (fsync + filelock). A real I/O
        # failure would otherwise emit a stack trace to stderr; the skill
        # markdown parses stdout JSON via jq and would silently treat
        # non-JSON as success. Surface it as a structured failure instead.
        print_json({"ok": False, "error": "io_error", "detail": str(exc)})
        return 1

    print_json(
        {
            "ok": True,
            "recorded": "cost_charged",
            "epic": epic,
            "story_key": story_key,
            "cost_usd": cost_usd,
        }
    )
    return 0
