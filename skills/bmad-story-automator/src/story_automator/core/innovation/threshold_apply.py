"""C5 self-improving-gate apply step (operator-gated; never auto-runs).

Performs a single-knob, AST-located, surgical byte splice on the
``target_module`` referenced by a :class:`ThresholdProposal` after the
operator has typed the proposal's ``confirm_slug`` back at the CLI.

Mechanically isolated from ``core/`` + ``commands/`` per
``ThresholdApplyIsolationInvariant``; only the structurally-recognized
CLI handler (``commands/calibration_cmd.py::_cmd_apply``) is exempted.
Safety invariants (spec §3 / §4): constant-time slug compare via
``hmac.compare_digest`` with length-aware hint BEFORE proposal load;
TTL bound (default 168 h); bytes I/O with UTF-8 BOM strip/restore;
``ast.parse`` walker skips ``AnnAssign.annotation``; anti-drift via
``ast.literal_eval`` equality to ``current_value``; byte-for-byte
backup BEFORE splice with restore on post-splice ``ast.parse``
failure; serialized via ``.calibration.lock``.

Stdlib + ``filelock`` only (CLAUDE.md hard guardrail).
"""

from __future__ import annotations

import ast
import contextlib
import hmac
import importlib.util
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from story_automator.core.atomic_io import write_atomic_text
from story_automator.core.common import compact_json, iso_now

from .threshold_decisions import (
    ACTION_ACCEPT,
    ACTION_CONFIRM_FAILED,
    CALIBRATION_LOCK_TIMEOUT_S,
    DecisionRecord,
    calibration_dir,
    calibration_lock_path,
    decisions_path,
)

__all__ = [
    "AppliedThresholdRecord",
    "MAX_PROPOSAL_AGE_HOURS",
    "ThresholdApplyError",
    "apply_threshold_proposal",
]


MAX_PROPOSAL_AGE_HOURS: int = 168
"""Default TTL on a proposal — 7 days; per-proposer override via
``proposer_config['ttl_hours']`` is honored (spec §3)."""


_CONFIRM_LENGTH_HINT: str = (
    "--confirm must be exactly 8 hex chars (did you swap --confirm and --proposal-id?)"
)
_CONFIRM_MISMATCH_HINT: str = "confirm slug does not match"


@dataclass(kw_only=True, frozen=True)
class AppliedThresholdRecord:
    """One persisted apply record (spec §5.4). ``target_file`` is the
    absolute resolved path from ``find_spec(target_module).origin``;
    ``before_path`` is the relative path of the byte-for-byte backup
    under ``_bmad/calibration/proposals/<id>.applied/before.py.gate_rules``.
    """

    proposal_id: str
    applied_at_iso: str
    operator_id: str
    target_file: str
    before_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "applied_at_iso": self.applied_at_iso,
            "operator_id": self.operator_id,
            "target_file": self.target_file,
            "before_path": self.before_path,
        }


class ThresholdApplyError(RuntimeError):
    """Apply-step failure (spec §5.5). Carries a closed-vocabulary
    ``code`` attribute matched exactly by tests, plus an optional
    operator-facing ``hint`` string."""

    def __init__(self, *, code: str, hint: str = "", message: str | None = None) -> None:
        self.code = code
        self.hint = hint
        super().__init__(message or (f"{code}: {hint}" if hint else code))


def _proposals_dir(project_root: Path | str) -> Path:
    return calibration_dir(project_root) / "proposals"


def _proposal_path(project_root: Path | str, proposal_id: str) -> Path:
    return _proposals_dir(project_root) / f"{proposal_id}.json"


def _applied_dir(project_root: Path | str, proposal_id: str) -> Path:
    return _proposals_dir(project_root) / f"{proposal_id}.applied"


def _resolve_module_file(target_module: str) -> Path:
    """Resolve a logical Python path to an on-disk file via ``find_spec``.
    Raises ``MODULE_NOT_RESOLVABLE`` if spec/origin is ``None``."""
    try:
        spec = importlib.util.find_spec(target_module)
    except (ImportError, ValueError):
        spec = None
    if spec is None or spec.origin is None:
        _raise("MODULE_NOT_RESOLVABLE", f"could not resolve {target_module!r}")
    return Path(spec.origin)  # type: ignore[union-attr]


def _strip_bom(raw: bytes) -> tuple[bytes, bool]:
    """Strip a leading UTF-8 BOM; return the residual bytes + flag."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:], True
    return raw, False


def _build_line_starts(body: bytes) -> list[int]:
    """Byte offsets of each line start in ``body`` (line 1 == index 0).
    Python AST ``col_offset`` is a UTF-8 BYTE offset, not a char index."""
    starts = [0]
    for i, b in enumerate(body):
        if b == 0x0A:  # newline
            starts.append(i + 1)
    return starts


def _compute_byte_slice(node: ast.AST, line_starts: list[int]) -> tuple[int, int]:
    """Map ``(lineno, col_offset, end_lineno, end_col_offset)`` to bytes."""
    start_line = node.lineno  # type: ignore[attr-defined]
    end_line = node.end_lineno  # type: ignore[attr-defined]
    if start_line is None or end_line is None or start_line < 1 or end_line < 1:
        _raise("NON_LITERAL_TARGET", f"bad line position {start_line!r}/{end_line!r}")
    start = line_starts[start_line - 1] + node.col_offset  # type: ignore[attr-defined]
    end = line_starts[end_line - 1] + node.end_col_offset  # type: ignore[attr-defined]
    return start, end


def _walk_module_assigns(tree: ast.Module, target_symbol: str) -> ast.expr | None:
    """Return RHS for top-level ``target_symbol = ...`` (Assign / AnnAssign).
    Never recurses into ``AnnAssign.annotation`` — spec §3 anti-drift
    guarantee for type-hint subtrees like ``dict[str, tuple[int, int]]``."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == target_symbol:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and tgt.id == target_symbol and node.value is not None:
                return node.value
    return None


def _raise(code: str, hint: str) -> None:
    raise ThresholdApplyError(code=code, hint=hint)


def _locate_leaf_constant(
    tree: ast.Module, target_symbol: str, selector: dict[str, Any]
) -> ast.Constant:
    """Resolve a selector to a single ``ast.Constant`` leaf per spec §5.2."""
    kind = selector.get("kind")
    if kind not in ("dict_tuple_element", "name"):
        _raise("UNSUPPORTED_SELECTOR_KIND", f"selector.kind={kind!r}")
    rhs = _walk_module_assigns(tree, target_symbol)
    if rhs is None:
        _raise("SELECTOR_NOT_FOUND", f"no top-level assignment to {target_symbol!r}")
    if kind == "dict_tuple_element":
        if not isinstance(rhs, ast.Dict):
            _raise("SELECTOR_NOT_FOUND", f"RHS of {target_symbol!r} is not a Dict")
        key = selector.get("key")
        index = selector.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            _raise("SELECTOR_NOT_FOUND", f"selector.index must be int; got {index!r}")
        assert isinstance(rhs, ast.Dict)
        assert isinstance(index, int)
        for k_node, v_node in zip(rhs.keys, rhs.values, strict=False):
            if not isinstance(k_node, ast.Constant) or k_node.value != key:
                continue
            if not isinstance(v_node, (ast.Tuple, ast.List)):
                _raise("NON_LITERAL_TARGET", f"value for key={key!r} not a Tuple/List")
            if not (0 <= index < len(v_node.elts)):
                _raise("SELECTOR_NOT_FOUND", f"index {index} out of range for key={key!r}")
            elt = v_node.elts[index]
            if not isinstance(elt, ast.Constant):
                _raise("NON_LITERAL_TARGET", f"element at {key!r}[{index}] not Constant")
            return elt
        _raise("SELECTOR_NOT_FOUND", f"key={key!r} not in {target_symbol!r}")
    if not isinstance(rhs, ast.Constant):
        _raise("NON_LITERAL_TARGET", f"RHS of {target_symbol!r} is not ast.Constant")
    return rhs  # type: ignore[return-value]


def _splice_bytes(raw: bytes, start: int, end: int, replacement: bytes) -> bytes:
    """Surgical byte-range substitution: ``raw[:start] + repl + raw[end:]``."""
    if start < 0 or end > len(raw) or start > end:
        _raise("APPLY_REWRITE_INVALID", f"splice [{start},{end}) out of bounds")
    return raw[:start] + replacement + raw[end:]


def _parse_iso_utc(value: str) -> datetime:
    """Parse the ``iso_now()`` format ``YYYY-MM-DDTHH:MM:SSZ`` to a UTC dt."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _load_proposal_json(project_root: Path | str, proposal_id: str) -> dict[str, Any]:
    path = _proposal_path(project_root, proposal_id)
    if not path.is_file():
        _raise("PROPOSAL_NOT_FOUND", f"no proposal JSON at {path}")
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ThresholdApplyError(code="PROPOSAL_NOT_FOUND", hint=f"load failed: {err!r}") from err


def _has_newer_proposal(project_root: Path | str, proposal: dict[str, Any]) -> bool:
    """True iff a sibling proposal on the same target has a newer
    ``created_at_iso`` (iso8601 ``Z`` form sorts chronologically)."""
    target_dir = _proposals_dir(project_root)
    if not target_dir.is_dir():
        return False
    this_created = proposal.get("created_at_iso", "")
    this_id = proposal.get("proposal_id", "")
    this_module = proposal.get("target_module", "")
    this_symbol = proposal.get("target_symbol", "")
    this_selector = proposal.get("selector", {})
    for entry in target_dir.iterdir():
        if entry.suffix != ".json" or not entry.is_file():
            continue
        if entry.stem == this_id:
            continue
        try:
            other = json.loads(entry.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            other.get("target_module") != this_module
            or other.get("target_symbol") != this_symbol
            or other.get("selector") != this_selector
        ):
            continue
        if str(other.get("created_at_iso", "")) > this_created:
            return True
    return False


def _append_decision_durable(*, project_root: Path | str, record: DecisionRecord) -> None:
    """Durable JSONL append while holding ``.calibration.lock`` externally
    (cannot re-enter :func:`record_decision` — it would re-acquire the lock)."""
    payload = compact_json(record.to_dict()).encode("utf-8") + b"\n"
    calibration_dir(project_root, create=True)
    fd = os.open(
        str(decisions_path(project_root)),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def _maybe_emit_audit(
    *,
    proposal_id: str,
    target_module: str,
    target_symbol: str,
    event: str,
    operator_id: str,
) -> None:
    """Emit ``GateThresholdProposalAudit`` when available; Stage 4 adds
    the dataclass — this stage tolerates the absence (spec §3 / §4)."""
    try:
        from story_automator.core import gate_audit as _audit

        cls = getattr(_audit, "GateThresholdProposalAudit", None)
        if cls is None:
            return
        _ = cls(
            proposal_id=proposal_id,
            target_module=target_module,
            target_symbol=target_symbol,
            event=event,
            operator_id=operator_id,
        )
    except Exception:
        return


def apply_threshold_proposal(
    project_root: Path | str,
    proposal_id: str,
    *,
    confirm: str,
    operator_id: str,
) -> AppliedThresholdRecord:
    """Apply ``proposal_id`` to its targeted module (spec §4 steps 1-20).

    Steps in order: (1) length-aware ``CONFIRM_MISMATCH`` BEFORE load;
    (2) acquire ``.calibration.lock`` (30s, raises ``LOCK_TIMEOUT``);
    (3) load proposal JSON (``PROPOSAL_NOT_FOUND``); (4) TTL check
    (``PROPOSAL_EXPIRED``); (5) constant-time slug compare, appending
    ``confirm_failed`` on mismatch (``CONFIRM_MISMATCH``); (6)
    newer-proposal precedence (``STALE_PROPOSAL``); (7) ``find_spec``
    → target file (``MODULE_NOT_RESOLVABLE``); (8) bytes I/O + BOM
    strip; (9) ``ast.parse``; (10) selector walk to leaf
    (``UNSUPPORTED_SELECTOR_KIND`` / ``SELECTOR_NOT_FOUND`` /
    ``NON_LITERAL_TARGET``); (11) type + literal_eval anti-drift
    (``TYPE_MISMATCH`` / ``LIVE_VALUE_DRIFTED``); (12) line-start byte
    slice; (13) backup BEFORE splice (``BACKUP_FAILED``); (14) splice
    + re-prepend BOM; (15) post-splice ``ast.parse``, restore-from-
    backup on ``APPLY_REWRITE_INVALID``; (16) atomic write of target;
    (17) ``record.json``; (18) durable ``accept`` decision append; (19)
    ``GateThresholdProposalAudit(event="proposal_applied", ...)``;
    (20) release lock; return the :class:`AppliedThresholdRecord`.
    """
    # Step 1 — length-aware confirm gate (BEFORE load).
    if len(confirm) != 8:
        raise ThresholdApplyError(code="CONFIRM_MISMATCH", hint=_CONFIRM_LENGTH_HINT)

    # Step 2 — acquire lock.
    calibration_dir(project_root, create=True)
    lock = FileLock(str(calibration_lock_path(project_root)))
    try:
        lock.acquire(timeout=CALIBRATION_LOCK_TIMEOUT_S)
    except Timeout as err:
        raise ThresholdApplyError(
            code="LOCK_TIMEOUT",
            hint=f"could not acquire {calibration_lock_path(project_root)} within "
            f"{CALIBRATION_LOCK_TIMEOUT_S}s",
        ) from err

    try:
        # Step 3 — load proposal JSON.
        proposal = _load_proposal_json(project_root, proposal_id)

        # Step 4 — TTL.
        ttl_hours_raw = proposal.get("proposer_config", {}).get("ttl_hours", MAX_PROPOSAL_AGE_HOURS)
        try:
            ttl_hours = int(ttl_hours_raw)
        except (TypeError, ValueError):
            ttl_hours = MAX_PROPOSAL_AGE_HOURS
        try:
            created_at = _parse_iso_utc(str(proposal["created_at_iso"]))
        except (KeyError, ValueError) as err:
            raise ThresholdApplyError(
                code="PROPOSAL_EXPIRED",
                hint=f"unparseable created_at_iso: {err!r}",
            ) from err
        now_utc = datetime.now(timezone.utc)
        if now_utc - created_at > timedelta(hours=ttl_hours):
            raise ThresholdApplyError(
                code="PROPOSAL_EXPIRED",
                hint=f"proposal created {created_at.isoformat()} exceeds {ttl_hours}h TTL",
            )

        # Step 5 — constant-time slug compare; append confirm_failed under lock.
        if not hmac.compare_digest(confirm, str(proposal.get("confirm_slug", ""))):
            with contextlib.suppress(OSError):
                _append_decision_durable(
                    project_root=project_root,
                    record=DecisionRecord(
                        proposal_id=proposal_id,
                        action=ACTION_CONFIRM_FAILED,
                        operator_id=operator_id,
                        decided_at_iso=iso_now(),
                        operator_note="",
                    ),
                )
            raise ThresholdApplyError(code="CONFIRM_MISMATCH", hint=_CONFIRM_MISMATCH_HINT)

        # Step 6 — newer sibling supersedes.
        if _has_newer_proposal(project_root, proposal):
            _raise("STALE_PROPOSAL", "a newer proposal supersedes this one")

        # Step 7 — resolve target.
        target_module = str(proposal["target_module"])
        target_symbol = str(proposal["target_symbol"])
        selector = dict(proposal.get("selector", {}))
        current_value = proposal["current_value"]
        proposed_value = proposal["proposed_value"]
        target_file = _resolve_module_file(target_module)

        # Steps 8-9 — bytes I/O + BOM strip + parse.
        raw = target_file.read_bytes()
        body, bom_present = _strip_bom(raw)
        try:
            tree = ast.parse(body)
        except SyntaxError as err:
            raise ThresholdApplyError(
                code="LIVE_VALUE_DRIFTED", hint=f"target no longer parses: {err!r}"
            ) from err

        # Step 10 — locate leaf.
        node = _locate_leaf_constant(tree, target_symbol, selector)

        # Step 11 — type + literal_eval anti-drift.
        node_value = node.value
        if isinstance(node_value, bool) or isinstance(current_value, bool):
            _raise("TYPE_MISMATCH", "bool targets unsupported")
        if type(node_value) is not type(current_value):
            _raise(
                "TYPE_MISMATCH",
                f"live {type(node_value).__name__} != proposal {type(current_value).__name__}",
            )
        extracted = ast.get_source_segment(body.decode("utf-8", errors="strict"), node)
        if extracted is None:
            _raise("LIVE_VALUE_DRIFTED", "could not extract source segment")
        try:
            live_value = ast.literal_eval(extracted)  # type: ignore[arg-type]
        except (ValueError, SyntaxError) as err:
            raise ThresholdApplyError(
                code="LIVE_VALUE_DRIFTED", hint=f"literal_eval failed: {err!r}"
            ) from err
        if live_value != current_value or type(live_value) is not type(current_value):
            _raise("LIVE_VALUE_DRIFTED", f"live {live_value!r} != current {current_value!r}")

        # Steps 12-13 — byte slice + backup BEFORE splice.
        line_starts = _build_line_starts(body)
        start, end = _compute_byte_slice(node, line_starts)
        applied_dir = _applied_dir(project_root, proposal_id)
        applied_dir.mkdir(parents=True, exist_ok=True)
        backup_path = applied_dir / "before.py.gate_rules"
        try:
            write_atomic_text(backup_path, raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError) as err:
            raise ThresholdApplyError(
                code="BACKUP_FAILED", hint=f"backup write failed: {err!r}"
            ) from err

        # Steps 14-15 — splice + re-prepend BOM + re-verify; restore on failure.
        replacement = repr(proposed_value).encode("ascii")
        new_body = _splice_bytes(body, start, end, replacement)
        new_raw = (b"\xef\xbb\xbf" + new_body) if bom_present else new_body
        try:
            ast.parse(new_body)
        except SyntaxError as err:
            with contextlib.suppress(OSError):
                write_atomic_text(target_file, raw.decode("utf-8"))
            raise ThresholdApplyError(
                code="APPLY_REWRITE_INVALID", hint=f"post-splice ast.parse: {err!r}"
            ) from err

        # Steps 16-19 — write target, record.json, accept decision, audit.
        write_atomic_text(target_file, new_raw.decode("utf-8"))
        applied_record = AppliedThresholdRecord(
            proposal_id=proposal_id,
            applied_at_iso=iso_now(),
            operator_id=operator_id,
            target_file=str(target_file.resolve()),
            before_path=str(backup_path.relative_to(Path(project_root))),
        )
        write_atomic_text(applied_dir / "record.json", compact_json(applied_record.to_dict()))
        _append_decision_durable(
            project_root=project_root,
            record=DecisionRecord(
                proposal_id=proposal_id,
                action=ACTION_ACCEPT,
                operator_id=operator_id,
                decided_at_iso=iso_now(),
                operator_note="",
            ),
        )
        _maybe_emit_audit(
            proposal_id=proposal_id,
            target_module=target_module,
            target_symbol=target_symbol,
            event="proposal_applied",
            operator_id=operator_id,
        )
        return applied_record
    finally:
        # Step 20 — release lock.
        with contextlib.suppress(RuntimeError):
            lock.release()
