"""``story-automator audit-verify`` CLI subcommand wrapping ``AuditLog.verify``.

Thin shell-callable wrapper around ``core.audit.AuditLog.verify`` (M04). Walks
the per-project hash-chained audit log and prints a single compact JSON object
to stdout describing whether the chain is intact and the last verified seq, so
BMAD step markdown can branch on ``valid`` via ``jq``.

Read-only by design: it never appends to the chain, never creates the audit
file, and never prompts for input. The audit key is loaded via
``load_key_from_env`` and is never echoed — only the boolean ``valid`` verdict,
the ``last_valid_seq``, and the resolved ``path`` ever reach stdout.
"""

from __future__ import annotations

from ..core.audit import AuditLog, load_key_from_env
from ..core.common import print_json, project_root
from ._audit_hooks import _audit_path_for


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


def cmd_audit_verify(args: list[str]) -> int:
    """Entry point for ``story-automator audit-verify``.

    Optional flags:
        --project-root <dir>   project root holding ``_bmad/audit/audit.jsonl``
                               (defaults to ``core.common.project_root()``).

    Requires ``BMAD_AUDIT_KEY`` in the environment — without it the chain
    tags cannot be recomputed, so the command refuses (``audit_key_missing``)
    rather than reporting a misleading verdict. On a missing or empty log
    ``verify()`` returns ``(True, 0)`` (REQ-09), which surfaces as
    ``valid=true, last_valid_seq=0``.
    """
    params = _flag_map(args)
    root = params.get("project-root") or str(project_root())

    key = load_key_from_env()
    if key is None:
        # Refuse before any filesystem access — the missing-key path is
        # strictly read-only and must not touch or create the audit log.
        print_json({"ok": False, "error": "audit_key_missing"})
        return 1

    path = _audit_path_for(root)
    try:
        valid, last_valid_seq = AuditLog(path=path, key=key).verify()
    except OSError as exc:
        # A real I/O error (e.g. PermissionError on an existing log) would
        # emit a stack trace to stderr; the skill markdown parses stdout JSON
        # via jq and would silently mistreat non-JSON. Surface a structured
        # failure with ok=false instead. The exception text never carries the
        # key (core.audit guarantees this).
        print_json({"ok": False, "error": "io_error", "detail": str(exc)})
        return 1

    print_json(
        {
            "ok": True,
            "valid": valid,
            "last_valid_seq": last_valid_seq,
            "path": str(path),
        }
    )
    return 0
