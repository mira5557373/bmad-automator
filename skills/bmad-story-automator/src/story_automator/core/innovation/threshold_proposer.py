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

Pure helpers + the :class:`ThresholdProposal` dataclass live in the
sibling :mod:`threshold_proposer_helpers` module; this module re-exports
them so existing callers see no public-surface change while staying
under the CLAUDE.md 500-LOC soft limit (pre-split: 799 LOC).
"""

from __future__ import annotations

import ast
import json
import os
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
    latest_decision_for,
    record_decision,
)
from .threshold_proposer_helpers import (
    DRIFT_BAND_SYMBOLS,
    MAX_PROPOSAL_AGE_HOURS,
    MAX_REPR_BYTES,
    PROPOSAL_SCHEMA_VERSION,
    _PROPOSAL_ID_RE,
    _append_decision_durable,
    _append_partial_supersede,
    _canonical_id_payload,
    _compute_proposal_id,
    _compute_proposed_value,
    _locate_leaf_for_selector,
    _maybe_emit_audit,
    _module_to_relative_hint,
    _proposal_from_dict,
    _read_coverage,
    _read_priority,
    _render_rationale,
    _resolve_target_source,
    _same_target,
    ThresholdProposal,
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


# v1 target registry: every PRIORITY_THRESHOLDS bucket maps to the
# ``correctness`` category for signal purposes (spec §3).
_PRIORITY_TARGET_CATEGORY: dict[str, str] = {p: "correctness" for p in ("P0", "P1", "P2", "P3")}

_DEFAULT_TARGET_MODULE = "story_automator.core.gate_rules"
_DEFAULT_TARGET_SYMBOL = "PRIORITY_THRESHOLDS"


class ProposerConfigError(ValueError):
    """Raised at construction for invalid kwargs (spec §3 invariant)."""


# ----- path helpers --------------------------------------------------------


def proposals_dir(project_root: Path | str, *, create: bool = False) -> Path:
    """``<root>/_bmad/calibration/proposals/`` (lazily created when ``create``)."""
    root = calibration_dir(project_root, create=create) / "proposals"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _proposal_path(project_root: Path | str, proposal_id: str) -> Path:
    return proposals_dir(project_root) / f"{proposal_id}.json"


def _gate_verdicts_dir(project_root: Path | str) -> Path:
    return Path(project_root) / "_bmad" / "gate" / "verdicts"


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

        proposed_value = _compute_proposed_value(
            window=window,
            current_value=current_value,
            source_segment=source_segment,
            consecutive_runs=self.consecutive_runs,
            max_delta_pct=self.max_delta_pct,
        )
        if proposed_value is None:
            return None

        evidence_window = tuple(gid for gid, _ in window)
        delta = proposed_value - current_value
        rationale = _render_rationale(
            project_root=project_root,
            priority=priority,
            window=window,
            current_value=current_value,
            proposed_value=proposed_value,
            target_pass_rate_band=self.target_pass_rate_band,
            max_delta_pct=self.max_delta_pct,
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
