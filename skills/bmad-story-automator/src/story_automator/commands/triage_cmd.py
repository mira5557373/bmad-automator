"""``story-automator triage`` CLI subcommand wrapping ``classify`` (M07b).

Thin shell-callable wrapper around
``core.failure_triage.classify`` paired with the
``core.telemetry_events.parse_event`` JSONL->Event bridge. Reads a single
telemetry event (one JSONL object) from a ``--json`` flag value or from
stdin, classifies it into a failure-triage verdict, and prints a single
compact JSON object to stdout so BMAD step markdown can branch on the
``failure_class`` / ``confidence`` via ``jq``.

Read-only by design — does not write the ledger, does not call audit-log
routines, and does not prompt for input. ``classify`` never raises on a
well-formed ``Event``; the only error paths are ``parse_event`` input
validation (missing event, malformed JSON, undispatchable payload).
"""

from __future__ import annotations

import json
import sys

from ..core.common import print_json
from ..core.failure_triage import Classification, classify
from ..core.telemetry_events import parse_event


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


def _classification_to_dict(c: Classification) -> dict[str, object]:
    """Serialize a ``Classification`` into the success wire shape.

    Enum ``.value`` equals the member name for both ``FailureClass`` and
    ``Confidence`` (per their docstrings), so the bare string round-trips
    cleanly to downstream policy engines without importing the enums.
    """
    return {
        "ok": True,
        "failure_class": c.primary.value,
        "confidence": c.confidence.value,
        "implies": [member.value for member in c.implies],
        "reason": c.reason,
        "event_id": c.event_id,
    }


def cmd_triage(args: list[str]) -> int:
    """Entry point for ``story-automator triage``.

    Input source (one of):
        --json <jsonl-line>   a single telemetry event as a JSON object
        (no --json)           read the event from stdin

    Success payload (single compact line):
        {"ok":true,"failure_class":...,"confidence":...,"implies":[...],
         "reason":...,"event_id":null}

    Error payloads use the ``{"ok": false, "error": ...}`` convention with
    an optional ``detail``.
    """
    params = _flag_map(args)
    if "json" in params:
        raw = params["json"]
    else:
        raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        print_json({"ok": False, "error": "missing_event"})
        return 1
    try:
        event = parse_event(raw)
    except json.JSONDecodeError as exc:
        print_json({"ok": False, "error": "invalid_json", "detail": str(exc)})
        return 1
    except (ValueError, TypeError) as exc:
        # parse_event raises ValueError for non-object top-level JSON or a
        # missing/non-string event_type, and TypeError for a known
        # event_type whose payload fields do not match the dataclass.
        print_json({"ok": False, "error": "invalid_event", "detail": str(exc)})
        return 1
    classification = classify(event)
    print_json(_classification_to_dict(classification))
    return 0
