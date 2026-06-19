"""``story-automator telemetry-report`` CLI subcommand.

Read-only wrapper around ``core.telemetry_reader.TelemetryReader`` that
aggregates the M02 JSONL telemetry stream into shell-callable rollups
(cost-by-epic, retry-attempts-by-story, and per-epic retro inputs).
Prints a single compact JSON object to stdout so BMAD step markdown can
branch via ``jq``. Like ``ceiling_check.py`` it does not write the
ledger and the read is wrapped in try/except so stdout stays JSON-only
even on a corrupt line or an I/O error.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.common import print_json
from ..core.telemetry_reader import TelemetryReader
from ..core.utils import get_project_root


_VALID_REPORTS = ("cost_by_epic", "attempts_by_story", "retro_inputs", "all")


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


def _default_events_path() -> str:
    return str(Path(get_project_root()) / "telemetry" / "events.jsonl")


def _attempts_list(reader: TelemetryReader) -> list[dict[str, object]]:
    """Transform ``attempts_by_story`` tuple keys into JSON-safe objects.

    ``TelemetryReader.attempts_by_story`` returns a ``dict`` keyed by
    ``(epic, story_key)`` tuples — not JSON-serializable. Emit a sorted
    list of explicit ``{epic, story_key, attempts}`` objects so the
    payload round-trips through ``json``.
    """
    return [
        {"epic": epic, "story_key": story_key, "attempts": count}
        for (epic, story_key), count in sorted(reader.attempts_by_story().items())
    ]


def _read_tail_events(events_path: str, count: int) -> list[dict[str, object]]:
    """Return the last ``count`` events as parsed objects (read-only).

    Reads the raw JSONL leniently so a single malformed tail line during a
    live run surfaces as a ``{"_corrupt": true}`` placeholder rather than
    aborting the whole view — the opposite of the aggregations, which fail
    loud on corruption per REQ-07.
    """
    path = Path(events_path)
    if not path.is_file():
        return []
    lines = [
        line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    recent = lines[-count:] if count > 0 else []
    events: list[dict[str, object]] = []
    for line in recent:
        try:
            parsed = json.loads(line)
        except ValueError:
            events.append({"_corrupt": True, "raw": line[:500]})
            continue
        events.append(parsed if isinstance(parsed, dict) else {"_corrupt": True, "raw": line[:500]})
    return events


def cmd_telemetry_report(args: list[str]) -> int:
    """Entry point for ``story-automator telemetry-report``.

    Optional flags:
        --events <path>   telemetry JSONL (default telemetry/events.jsonl
                          under ``get_project_root()``)
        --report {cost_by_epic,attempts_by_story,retro_inputs,all}
                          (default ``all``)
        --epic <name>     required only when --report is retro_inputs
        --tail <N>        skip the rollups and stream the last N raw events
                          (live-debug view; read-only, never aborts on a
                          corrupt tail line)
    """
    params = _flag_map(args)

    if "tail" in params:
        events_path = params.get("events") or _default_events_path()
        raw_tail = params.get("tail") or ""
        if not raw_tail.lstrip("-").isdigit():
            print_json({"ok": False, "error": "invalid_tail", "tail": raw_tail})
            return 1
        count = max(int(raw_tail), 0)
        print_json(
            {
                "ok": True,
                "report": "tail",
                "events": events_path,
                "tail": count,
                "recent": _read_tail_events(events_path, count),
            }
        )
        return 0

    report = params.get("report") or "all"
    if report not in _VALID_REPORTS:
        print_json({"ok": False, "error": "invalid_report", "report": report})
        return 1

    events_path = params.get("events") or _default_events_path()
    epic = params.get("epic") or ""

    if report == "retro_inputs" and not epic:
        print_json({"ok": False, "error": "missing_epic"})
        return 1

    reader = TelemetryReader(events_path)
    payload: dict[str, object] = {"ok": True, "report": report, "events": events_path}
    try:
        if report == "cost_by_epic":
            payload["cost_by_epic"] = reader.cost_by_epic()
        elif report == "attempts_by_story":
            payload["attempts_by_story"] = _attempts_list(reader)
        elif report == "retro_inputs":
            payload["epic"] = epic
            payload["retro_inputs"] = reader.retro_inputs(epic)
        else:  # "all"
            payload["cost_by_epic"] = reader.cost_by_epic()
            payload["attempts_by_story"] = _attempts_list(reader)
            if epic:
                payload["epic"] = epic
                payload["retro_inputs"] = {epic: reader.retro_inputs(epic)}
            else:
                payload["retro_inputs"] = None
                payload["retro_note"] = "pass --epic for retro_inputs"
    except (ValueError, TypeError) as exc:
        # Corruption surfaces two ways from ``reader.iter_events`` ->
        # ``parse_event``: a malformed JSONL line raises json.JSONDecodeError
        # (a ValueError subclass), and a valid-JSON-but-malformed event raises
        # ValueError/TypeError (missing/non-string event_type, missing kwargs).
        # The skill markdown parses stdout JSON via ``jq`` and would silently
        # treat a leaked traceback as no data, so surface all of these as a
        # structured corrupt_telemetry failure instead of an internal_error.
        print_json({"ok": False, "error": "corrupt_telemetry", "detail": str(exc)})
        return 1
    except OSError as exc:
        print_json({"ok": False, "error": "io_error", "detail": str(exc)})
        return 1

    print_json(payload)
    return 0
