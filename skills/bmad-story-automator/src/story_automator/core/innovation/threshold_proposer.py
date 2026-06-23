"""C5 self-improving-gate proposer (advisory only; never auto-applies).

Reads gate files under ``_bmad/gate/verdicts/`` and emits a
:class:`ThresholdProposal` recommending a single-knob, clamped
adjustment to ``PRIORITY_THRESHOLDS`` in ``core/gate_rules.py`` when
the observed pass-rate over the recent window drifts outside
``target_pass_rate_band`` for ``consecutive_runs`` in a row. Source is
never mutated here — :mod:`threshold_apply` does the splice (Stage 3).
Idempotent re-emit preserves ``confirm_slug`` + ``created_at_iso``;
auto-supersede appends a ``superseded`` decision for prior PENDING
proposals on the same ``(target_module, target_symbol, selector)``.
The ``ThresholdLockIsolationInvariant`` AST scan requires every
``FileLock(...)`` call to route through :func:`calibration_lock_path`.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from story_automator.core.atomic_io import write_atomic_text
from story_automator.core.common import compact_json, iso_now

from .threshold_decisions import (
    ACTION_ACCEPT,
    ACTION_REJECT,
    ACTION_SUPERSEDED,
    CALIBRATION_LOCK_TIMEOUT_S,
    DecisionRecord,
    calibration_dir,
    calibration_lock_path,
    decisions_path,
    latest_decision_for,
    record_decision,
)

__all__ = [
    "DRIFT_BAND_SYMBOLS",
    "MAX_PROPOSAL_AGE_HOURS",
    "MAX_REPR_BYTES",
    "PROPOSAL_SCHEMA_VERSION",
    "ProposerConfigError",
    "ThresholdProposal",
    "ThresholdProposer",
    "proposals_dir",
]


PROPOSAL_SCHEMA_VERSION: int = 1
MAX_PROPOSAL_AGE_HOURS: int = 168
MAX_REPR_BYTES: int = 24
DRIFT_BAND_SYMBOLS: frozenset[str] = frozenset({"STABLE_MAX", "MINOR_MAX", "MAJOR_MAX"})

# v1 target registry: every PRIORITY_THRESHOLDS bucket maps to the
# ``correctness`` category for signal purposes (spec §3).
_PRIORITY_TARGET_CATEGORY: dict[str, str] = {p: "correctness" for p in ("P0", "P1", "P2", "P3")}

_DEFAULT_TARGET_MODULE = "story_automator.core.gate_rules"
_DEFAULT_TARGET_SYMBOL = "PRIORITY_THRESHOLDS"
_PROPOSAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class ProposerConfigError(ValueError):
    """Raised at construction for invalid kwargs (spec §3 invariant)."""


@dataclass(kw_only=True, frozen=True)
class ThresholdProposal:
    """One advisory threshold-patch proposal (spec §5.1)."""

    proposal_id: str
    target_module: str
    target_symbol: str
    target_category: str
    target_file_hint: str
    selector: dict[str, Any]
    current_value: int | float
    proposed_value: int | float
    delta: int | float
    rationale: str
    evidence_window: tuple[str, ...]
    created_at_iso: str
    confirm_slug: str
    proposer_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.proposed_value) is not type(self.current_value):
            raise ValueError(
                f"ThresholdProposal: proposed_value/current_value type mismatch "
                f"({type(self.current_value).__name__} vs {type(self.proposed_value).__name__})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Spec §5.3 JSON shape (insertion order matters for byte-equality)."""
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "target_module": self.target_module,
            "target_symbol": self.target_symbol,
            "target_category": self.target_category,
            "target_file_hint": self.target_file_hint,
            "selector": dict(self.selector),
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "delta": self.delta,
            "rationale": self.rationale,
            "evidence_window": list(self.evidence_window),
            "created_at_iso": self.created_at_iso,
            "confirm_slug": self.confirm_slug,
            "proposer_config": dict(self.proposer_config),
        }


def _proposal_from_dict(data: dict[str, Any]) -> ThresholdProposal:
    return ThresholdProposal(
        proposal_id=str(data["proposal_id"]),
        target_module=str(data["target_module"]),
        target_symbol=str(data["target_symbol"]),
        target_category=str(data["target_category"]),
        target_file_hint=str(data.get("target_file_hint", "")),
        selector=dict(data["selector"]),
        current_value=data["current_value"],
        proposed_value=data["proposed_value"],
        delta=data["delta"],
        rationale=str(data.get("rationale", "")),
        evidence_window=tuple(data.get("evidence_window", [])),
        created_at_iso=str(data["created_at_iso"]),
        confirm_slug=str(data["confirm_slug"]),
        proposer_config=dict(data.get("proposer_config", {})),
    )


# ----- path helpers --------------------------------------------------------


def proposals_dir(project_root: Path | str, *, create: bool = False) -> Path:
    """``<root>/_bmad/calibration/proposals/`` (lazily created when ``create``)."""
    root = calibration_dir(project_root, create=create) / "proposals"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _proposal_path(project_root: Path | str, proposal_id: str) -> Path:
    return proposals_dir(project_root) / f"{proposal_id}.json"


def _partial_supersedes_path(project_root: Path | str) -> Path:
    return calibration_dir(project_root) / ".partial_supersedes.jsonl"


def _gate_verdicts_dir(project_root: Path | str) -> Path:
    return Path(project_root) / "_bmad" / "gate" / "verdicts"


# ----- AST helpers (proposer-time only; threshold_apply re-implements) -----


def _resolve_target_source(target_module: str) -> str | None:
    spec = importlib.util.find_spec(target_module)
    if spec is None or spec.origin is None:
        return None
    try:
        text = Path(spec.origin).read_text(encoding="utf-8")
    except OSError:
        return None
    if text.startswith("﻿"):
        text = text[1:]
    return text


def _walk_module_assigns(tree: ast.Module, target_symbol: str) -> ast.expr | None:
    """Return RHS expr for top-level ``target_symbol = ...`` (skips
    ``AnnAssign.annotation`` subtrees — spec §3)."""
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


def _locate_leaf_for_selector(
    tree: ast.Module, target_symbol: str, selector: dict[str, Any]
) -> ast.Constant | None:
    """Locate the leaf ``ast.Constant`` named by ``selector`` (spec §3)."""
    rhs = _walk_module_assigns(tree, target_symbol)
    if rhs is None:
        return None
    kind = selector.get("kind")
    if kind == "dict_tuple_element":
        if not isinstance(rhs, ast.Dict):
            return None
        key = selector.get("key")
        index = selector.get("index")
        if not isinstance(index, int):
            return None
        for k_node, v_node in zip(rhs.keys, rhs.values, strict=False):
            if (
                isinstance(k_node, ast.Constant)
                and k_node.value == key
                and isinstance(v_node, (ast.Tuple, ast.List))
                and 0 <= index < len(v_node.elts)
                and isinstance(v_node.elts[index], ast.Constant)
            ):
                return v_node.elts[index]
        return None
    if kind == "name":
        return rhs if isinstance(rhs, ast.Constant) else None
    return None


def _decimals_in_segment(segment: str | None) -> int:
    """Digits after ``.`` in a numeric source segment (0 for ints)."""
    if not segment:
        return 0
    s = segment.strip()
    if "." not in s:
        return 0
    if "e" in s or "E" in s:
        s = re.split(r"[eE]", s, maxsplit=1)[0]
    tail = s.split(".", 1)[1]
    n = 0
    for ch in tail:
        if not ch.isdigit():
            break
        n += 1
    return n


# ----- deterministic id ----------------------------------------------------


def _canonical_id_payload(
    *,
    target_module: str,
    target_symbol: str,
    selector: dict[str, Any],
    current_value: int | float,
    proposed_value: int | float,
    evidence_window: tuple[str, ...],
) -> str:
    return json.dumps(
        {
            "target_module": target_module,
            "target_symbol": target_symbol,
            "selector": dict(selector),
            "current_value": current_value,
            "proposed_value": proposed_value,
            "evidence_window": list(evidence_window),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _compute_proposal_id(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ----- ThresholdProposer ---------------------------------------------------


class ThresholdProposer:
    """Advisory threshold-tuning observer (spec §3/§4)."""

    def __init__(
        self,
        *,
        min_evidence_window: int = 5,
        target_pass_rate_band: tuple[float, float] = (0.80, 0.95),
        max_delta_pct: int = 5,
        consecutive_runs: int = 3,
        enable_drift_band_proposals: bool = False,
        ttl_hours: int = MAX_PROPOSAL_AGE_HOURS,
        operator_id: str = "local",
        target_module: str = _DEFAULT_TARGET_MODULE,
        target_symbol: str = _DEFAULT_TARGET_SYMBOL,
    ) -> None:
        if not isinstance(min_evidence_window, int) or min_evidence_window < 1:
            raise ProposerConfigError(
                f"min_evidence_window must be a positive int; got {min_evidence_window!r}"
            )
        if not isinstance(consecutive_runs, int) or consecutive_runs < 1:
            raise ProposerConfigError(
                f"consecutive_runs must be a positive int; got {consecutive_runs!r}"
            )
        if min_evidence_window < consecutive_runs:
            raise ProposerConfigError(
                f"min_evidence_window must be >= consecutive_runs "
                f"(got {min_evidence_window} < {consecutive_runs})"
            )
        lo, hi = target_pass_rate_band
        if not (0.0 <= lo < hi <= 1.0):
            raise ProposerConfigError(
                f"target_pass_rate_band must be (lo, hi) with 0<=lo<hi<=1; got {target_pass_rate_band!r}"
            )
        if not isinstance(max_delta_pct, int) or max_delta_pct < 1:
            raise ProposerConfigError(
                f"max_delta_pct must be a positive int; got {max_delta_pct!r}"
            )
        if not isinstance(ttl_hours, int) or ttl_hours < 1:
            raise ProposerConfigError(f"ttl_hours must be a positive int; got {ttl_hours!r}")

        self.min_evidence_window = min_evidence_window
        self.target_pass_rate_band = (float(lo), float(hi))
        self.max_delta_pct = max_delta_pct
        self.consecutive_runs = consecutive_runs
        self.enable_drift_band_proposals = bool(enable_drift_band_proposals)
        self.ttl_hours = ttl_hours
        self.operator_id = operator_id
        self.target_module = target_module
        self.target_symbol = target_symbol

    # ---- Public API ------------------------------------------------------

    def observe_gate(
        self, project_root: Path | str, gate_file: dict[str, Any]
    ) -> ThresholdProposal | None:
        """Possibly emit a proposal after a fresh gate run (spec §4)."""
        if self.target_symbol in DRIFT_BAND_SYMBOLS and not self.enable_drift_band_proposals:
            return None

        priority = _read_priority(gate_file, "correctness")
        if priority not in _PRIORITY_TARGET_CATEGORY:
            return None
        target_category = _PRIORITY_TARGET_CATEGORY[priority]
        selector = {"kind": "dict_tuple_element", "key": priority, "index": 0}

        located = self._locate_current_value(selector)
        if located is None:
            return None
        current_value, source_segment = located
        if isinstance(current_value, bool) or not isinstance(current_value, (int, float)):
            return None

        window = self._collect_window(project_root, target_category, priority)
        if len(window) < self.min_evidence_window:
            return None
        window = window[-self.min_evidence_window :]

        proposed_value = self._compute_proposed(
            window=window, current_value=current_value, source_segment=source_segment
        )
        if proposed_value is None:
            return None

        evidence_window = tuple(gid for gid, _ in window)
        delta = proposed_value - current_value
        rationale = self._render_rationale(
            project_root=project_root,
            priority=priority,
            window=window,
            current_value=current_value,
            proposed_value=proposed_value,
        )
        proposal_id = _compute_proposal_id(
            _canonical_id_payload(
                target_module=self.target_module,
                target_symbol=self.target_symbol,
                selector=selector,
                current_value=current_value,
                proposed_value=proposed_value,
                evidence_window=evidence_window,
            )
        )
        target_file_hint = _module_to_relative_hint(self.target_module)

        # Persist under the calibration lock; idempotent re-emit preserves
        # the existing slug + created_at + no decision appended.
        calibration_dir(project_root, create=True)
        with FileLock(
            str(calibration_lock_path(project_root)),
            timeout=CALIBRATION_LOCK_TIMEOUT_S,
        ) as lock:
            _ = lock  # silence linter; FileLock's __enter__ runs acquire()
            existing = self._read_proposal_unlocked(project_root, proposal_id)
            if existing is not None:
                return existing
            proposal = ThresholdProposal(
                proposal_id=proposal_id,
                target_module=self.target_module,
                target_symbol=self.target_symbol,
                target_category=target_category,
                target_file_hint=target_file_hint,
                selector=selector,
                current_value=current_value,
                proposed_value=proposed_value,
                delta=delta,
                rationale=rationale,
                evidence_window=evidence_window,
                created_at_iso=iso_now(),
                confirm_slug=os.urandom(4).hex(),
                proposer_config=self._snapshot_config(),
            )
            proposals_dir(project_root, create=True)
            write_atomic_text(
                _proposal_path(project_root, proposal_id), compact_json(proposal.to_dict())
            )
            self._maybe_auto_supersede(project_root=project_root, new_proposal=proposal)

        _maybe_emit_audit(proposal=proposal, event="proposal_created")
        return proposal

    def list_proposals(self, project_root: Path | str) -> list[ThresholdProposal]:
        """All on-disk proposals, sorted by ``created_at_iso`` descending."""
        target_dir = proposals_dir(project_root)
        if not target_dir.is_dir():
            return []
        out: list[ThresholdProposal] = []
        for entry in target_dir.iterdir():
            if entry.suffix != ".json" or not entry.is_file():
                continue
            if not _PROPOSAL_ID_RE.match(entry.stem):
                continue
            try:
                out.append(self.load_proposal(project_root, entry.stem))
            except FileNotFoundError:
                continue
        out.sort(key=lambda p: (p.created_at_iso, p.proposal_id), reverse=True)
        return out

    def load_proposal(self, project_root: Path | str, proposal_id: str) -> ThresholdProposal:
        if not _PROPOSAL_ID_RE.match(proposal_id or ""):
            raise FileNotFoundError(f"invalid proposal_id: {proposal_id!r}")
        path = _proposal_path(project_root, proposal_id)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return _proposal_from_dict(json.loads(path.read_text("utf-8")))

    def reject_proposal(
        self,
        project_root: Path | str,
        proposal_id: str,
        reason: str,
        operator_id: str | None = None,
    ) -> None:
        """Append a ``reject`` decision; raises ``FileNotFoundError`` if absent."""
        _ = self.load_proposal(project_root, proposal_id)
        record_decision(
            project_root=project_root,
            proposal_id=proposal_id,
            action=ACTION_REJECT,
            operator_id=operator_id or self.operator_id,
            operator_note=reason or "",
        )
        _maybe_emit_audit(proposal=None, event="proposal_rejected", proposal_id=proposal_id)

    # ---- Internal helpers -----------------------------------------------

    def _snapshot_config(self) -> dict[str, Any]:
        lo, hi = self.target_pass_rate_band
        return {
            "min_evidence_window": self.min_evidence_window,
            "target_pass_rate_band": [lo, hi],
            "max_delta_pct": self.max_delta_pct,
            "consecutive_runs": self.consecutive_runs,
            "enable_drift_band_proposals": self.enable_drift_band_proposals,
            "ttl_hours": self.ttl_hours,
        }

    def _locate_current_value(
        self, selector: dict[str, Any]
    ) -> tuple[int | float, str | None] | None:
        source_text = _resolve_target_source(self.target_module)
        if source_text is None:
            return None
        try:
            tree = ast.parse(source_text)
        except SyntaxError:
            return None
        node = _locate_leaf_for_selector(tree, self.target_symbol, selector)
        if node is None:
            return None
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value, ast.get_source_segment(source_text, node)

    def _collect_window(
        self, project_root: Path | str, target_category: str, priority: str
    ) -> list[tuple[str, float]]:
        """Enumerate gate files matching ``priority``. Sort ascending by
        ``gate_id`` ASCII; never consult mtime."""
        verdicts = _gate_verdicts_dir(project_root)
        if not verdicts.is_dir():
            return []
        from story_automator.core.evidence_io import load_gate_file

        out: list[tuple[str, float]] = []
        for entry in sorted(verdicts.iterdir(), key=lambda p: p.name):
            if entry.suffix != ".json" or not entry.is_file():
                continue
            gate_id = entry.stem
            try:
                gate = load_gate_file(project_root, gate_id)
            except Exception:
                continue
            cov = _read_coverage(gate, target_category)
            if cov is None:
                continue
            if _read_priority(gate, target_category) != priority:
                continue
            out.append((gate_id, float(cov)))
        return out

    def _compute_proposed(
        self,
        *,
        window: list[tuple[str, float]],
        current_value: int | float,
        source_segment: str | None,
    ) -> int | float | None:
        """Clamped, quantized proposed value (spec §3 tail-of-window)."""
        lo, hi = self.target_pass_rate_band
        tail = window[-self.consecutive_runs :]
        pass_flags = [cov >= float(current_value) for _gid, cov in tail]
        if not pass_flags:
            return None
        observed_mean = sum(1 for f in pass_flags if f) / len(pass_flags)

        if all(pass_flags):
            direction = "up"
        elif not any(pass_flags):
            direction = "down"
        else:
            return None

        mean_cov = sum(cov for _gid, cov in window) / len(window)
        decimals = _decimals_in_segment(source_segment) if isinstance(current_value, float) else 0

        if direction == "up":
            if observed_mean <= hi:
                return None
            delta = math.ceil(mean_cov) - current_value
            if delta <= 0:
                return None
            clamped = min(delta, self.max_delta_pct)
        else:
            if observed_mean >= lo:
                return None
            delta = math.floor(mean_cov) - current_value
            if delta >= 0:
                return None
            clamped = max(delta, -self.max_delta_pct)

        proposed_raw = current_value + clamped
        if isinstance(current_value, float):
            proposed = round(float(proposed_raw), max(0, decimals))
            if proposed == float(current_value):
                return None
        else:
            proposed = int(round(float(proposed_raw)))
            if proposed == int(current_value):
                return None
        if len(repr(proposed).encode("ascii")) > MAX_REPR_BYTES:
            return None
        return proposed

    def _render_rationale(
        self,
        *,
        project_root: Path | str,
        priority: str,
        window: list[tuple[str, float]],
        current_value: int | float,
        proposed_value: int | float,
    ) -> str:
        lo, hi = self.target_pass_rate_band
        mean_cov = sum(c for _g, c in window) / len(window) if window else 0.0
        direction = "up" if proposed_value > current_value else "down"
        base = (
            f"Observed {priority} correctness coverage mean {mean_cov:.2f} "
            f"over last {len(window)} gates is "
            f"{'above' if direction == 'up' else 'below'} target band "
            f"[{lo:.2f}, {hi:.2f}]; ratcheting required_pct {direction} "
            f"from {current_value} to {proposed_value} (max-delta-pct={self.max_delta_pct})."
        )
        calib = _maybe_calibration_sentence(project_root)
        return f"{base} {calib}" if calib else base

    def _read_proposal_unlocked(
        self, project_root: Path | str, proposal_id: str
    ) -> ThresholdProposal | None:
        path = _proposal_path(project_root, proposal_id)
        if not path.is_file():
            return None
        try:
            return _proposal_from_dict(json.loads(path.read_text("utf-8")))
        except Exception:
            return None

    def _maybe_auto_supersede(
        self, *, project_root: Path | str, new_proposal: ThresholdProposal
    ) -> None:
        """Append ``superseded`` for prior PENDING proposals (spec §3).

        Caller MUST hold ``.calibration.lock``; appends the JSONL line
        directly rather than re-entering ``record_decision`` (which
        constructs a NEW :class:`FileLock` and would block on the held lock).
        """
        target_dir = proposals_dir(project_root)
        if not target_dir.is_dir():
            return
        for entry in sorted(target_dir.iterdir(), key=lambda p: p.name):
            if entry.suffix != ".json" or not entry.is_file():
                continue
            stem = entry.stem
            if stem == new_proposal.proposal_id or not _PROPOSAL_ID_RE.match(stem):
                continue
            prior = self._read_proposal_unlocked(project_root, stem)
            if prior is None or not _same_target(prior, new_proposal):
                continue
            latest = latest_decision_for(project_root, prior.proposal_id)
            if latest is not None and latest.action in {ACTION_ACCEPT, ACTION_REJECT}:
                continue
            try:
                _append_decision_durable(
                    project_root=project_root,
                    record=DecisionRecord(
                        proposal_id=prior.proposal_id,
                        action=ACTION_SUPERSEDED,
                        operator_id=self.operator_id,
                        decided_at_iso=iso_now(),
                        operator_note=f"superseded by {new_proposal.proposal_id}",
                    ),
                )
                _maybe_emit_audit(
                    proposal=None,
                    event="proposal_superseded",
                    proposal_id=prior.proposal_id,
                )
            except Exception as exc:
                _append_partial_supersede(
                    project_root=project_root,
                    prior_id=prior.proposal_id,
                    new_id=new_proposal.proposal_id,
                    error=str(exc),
                )


# ----- module-level helpers ------------------------------------------------


def _read_priority(gate_file: dict[str, Any], category: str) -> str | None:
    """Spec §3: ``gate_file["categories"][cat]["required"]["priority"]``."""
    cats = gate_file.get("categories")
    if not isinstance(cats, dict):
        return None
    info = cats.get(category)
    if not isinstance(info, dict) or info.get("verdict") == "NA":
        return None
    required = info.get("required")
    if not isinstance(required, dict):
        return None
    p = required.get("priority")
    return p if isinstance(p, str) else None


def _read_coverage(gate_file: dict[str, Any], category: str) -> float | None:
    """Spec §3: ``gate_file["categories"][cat]["actual"]["coverage_pct"]``."""
    cats = gate_file.get("categories")
    if not isinstance(cats, dict):
        return None
    info = cats.get(category)
    if not isinstance(info, dict) or info.get("verdict") == "NA":
        return None
    actual = info.get("actual")
    if not isinstance(actual, dict):
        return None
    cov = actual.get("coverage_pct")
    if isinstance(cov, bool) or not isinstance(cov, (int, float)):
        return None
    return float(cov)


def _same_target(a: ThresholdProposal, b: ThresholdProposal) -> bool:
    return (
        a.target_module == b.target_module
        and a.target_symbol == b.target_symbol
        and dict(a.selector) == dict(b.selector)
    )


def _module_to_relative_hint(target_module: str) -> str:
    """Best-effort source path (cosmetic; apply re-resolves via find_spec)."""
    spec = importlib.util.find_spec(target_module)
    return spec.origin if (spec is not None and spec.origin is not None) else ""


def _append_decision_durable(*, project_root: Path | str, record: DecisionRecord) -> None:
    """Durable JSONL append inside an already-held calibration lock."""
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


def _append_partial_supersede(
    *, project_root: Path | str, prior_id: str, new_id: str, error: str
) -> None:
    """Sidecar JSONL for failed supersede appends (spec §3 partial-failure)."""
    payload = (
        compact_json(
            {
                "prior_id": prior_id,
                "new_id": new_id,
                "error": error,
                "recorded_at_iso": iso_now(),
            }
        ).encode("utf-8")
        + b"\n"
    )
    path = _partial_supersedes_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)


def _maybe_calibration_sentence(project_root: Path | str) -> str:
    """Optional M08 calibration mean sentence; degrades silently."""
    try:
        from story_automator.core.calibration import build_calibration  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        table = build_calibration(project_root=Path(project_root))  # type: ignore[call-arg]
    except Exception:
        return ""
    if not table:
        return ""
    try:
        means = [
            float(info["success_rate"])
            for info in table.values()
            if isinstance(info, dict) and isinstance(info.get("success_rate"), (int, float))
        ]
        if not means:
            return ""
        return f"Calibration mean success rate = {sum(means) / len(means):.2f}."
    except Exception:
        return ""


def _maybe_emit_audit(
    *,
    proposal: ThresholdProposal | None,
    event: str,
    proposal_id: str | None = None,
) -> None:
    """Construct a ``GateThresholdProposalAudit`` event when available
    (Stage 4 adds the dataclass; tolerate import / attribute miss)."""
    try:
        from story_automator.core import gate_audit as _audit

        cls = getattr(_audit, "GateThresholdProposalAudit", None)
        if cls is None:
            return
        _ = cls(
            proposal_id=(proposal.proposal_id if proposal is not None else proposal_id),
            target_module=(proposal.target_module if proposal is not None else ""),
            target_symbol=(proposal.target_symbol if proposal is not None else ""),
            event=event,
            operator_id="local",
        )
    except Exception:
        return
