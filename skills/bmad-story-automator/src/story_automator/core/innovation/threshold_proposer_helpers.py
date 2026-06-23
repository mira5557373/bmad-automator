"""C5 threshold-proposer pure helpers (split sibling of ``threshold_proposer``).

Houses the symbol-locator + AST walker + deterministic-id payload +
priority/coverage/target-equality readers + on-disk durable-append
sidecars. Splitting these out of ``threshold_proposer.py`` keeps the
canonical module comfortably under the CLAUDE.md 500-LOC soft limit
(threshold_proposer.py landed at 799 LOC pre-split, breaching the cap)
without changing any observable behavior — every public function and
type re-exported from ``threshold_proposer`` keeps working through
the existing `from .threshold_proposer_helpers import ...` chain.

The ``ThresholdLockIsolationInvariant`` AST scan over
``core/innovation/threshold_*.py`` continues to cover this module by
glob; the ``_append_decision_durable`` helper here intentionally
mirrors the analogous helper in ``threshold_apply.py`` (the duplication
is documented in the post-impl review).

Stdlib only (CLAUDE.md hard guardrail).
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

from story_automator.core.common import compact_json, iso_now

from .threshold_decisions import (
    DecisionRecord,
    calibration_dir,
    decisions_path,
)

__all__ = [
    "DRIFT_BAND_SYMBOLS",
    "MAX_PROPOSAL_AGE_HOURS",
    "MAX_REPR_BYTES",
    "PROPOSAL_SCHEMA_VERSION",
    "ThresholdProposal",
    "_PROPOSAL_ID_RE",
    "_append_decision_durable",
    "_append_partial_supersede",
    "_canonical_id_payload",
    "_compute_proposal_id",
    "_compute_proposed_value",
    "_decimals_in_segment",
    "_locate_leaf_for_selector",
    "_maybe_calibration_sentence",
    "_maybe_emit_audit",
    "_module_to_relative_hint",
    "_partial_supersedes_path",
    "_proposal_from_dict",
    "_read_coverage",
    "_read_priority",
    "_render_rationale",
    "_resolve_target_source",
    "_same_target",
    "_walk_module_assigns",
]


PROPOSAL_SCHEMA_VERSION: int = 1
MAX_PROPOSAL_AGE_HOURS: int = 168
MAX_REPR_BYTES: int = 24
DRIFT_BAND_SYMBOLS: frozenset[str] = frozenset({"STABLE_MAX", "MINOR_MAX", "MAJOR_MAX"})

_PROPOSAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")


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


# ---- AST helpers (proposer-time only; threshold_apply re-implements) ----


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


# ---- deterministic id ----


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


# ---- gate-file readers ----


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


# ---- path helpers ----


def _partial_supersedes_path(project_root: Path | str) -> Path:
    return calibration_dir(project_root) / ".partial_supersedes.jsonl"


# ---- durable JSONL appenders (caller holds .calibration.lock) ----


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


# ---- core math (stateless) ----


def _compute_proposed_value(
    *,
    window: list[tuple[str, float]],
    current_value: int | float,
    source_segment: str | None,
    consecutive_runs: int,
    max_delta_pct: int,
) -> int | float | None:
    """Clamped, quantized proposed value (spec §3 tail-of-window).

    Trigger is the binary ``all(pass_flags)`` / ``not any(pass_flags)``
    check on the consecutive-runs tail; the earlier band-comparison on
    ``observed_mean`` was dead code in the surviving branches (mean was
    unconditionally 1.0 / 0.0) and has been deleted.
    """
    tail = window[-consecutive_runs:]
    pass_flags = [cov >= float(current_value) for _gid, cov in tail]
    if not pass_flags:
        return None
    if all(pass_flags):
        direction = "up"
    elif not any(pass_flags):
        direction = "down"
    else:
        return None

    mean_cov = sum(cov for _gid, cov in window) / len(window)
    decimals = _decimals_in_segment(source_segment) if isinstance(current_value, float) else 0

    if direction == "up":
        delta = math.ceil(mean_cov) - current_value
        if delta <= 0:
            return None
        clamped = min(delta, max_delta_pct)
    else:
        delta = math.floor(mean_cov) - current_value
        if delta >= 0:
            return None
        clamped = max(delta, -max_delta_pct)

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
    *,
    project_root: Path | str,
    priority: str,
    window: list[tuple[str, float]],
    current_value: int | float,
    proposed_value: int | float,
    target_pass_rate_band: tuple[float, float],
    max_delta_pct: int,
) -> str:
    lo, hi = target_pass_rate_band
    mean_cov = sum(c for _g, c in window) / len(window) if window else 0.0
    direction = "up" if proposed_value > current_value else "down"
    base = (
        f"Observed {priority} correctness coverage mean {mean_cov:.2f} "
        f"over last {len(window)} gates is "
        f"{'above' if direction == 'up' else 'below'} target band "
        f"[{lo:.2f}, {hi:.2f}]; ratcheting required_pct {direction} "
        f"from {current_value} to {proposed_value} (max-delta-pct={max_delta_pct})."
    )
    calib = _maybe_calibration_sentence(project_root)
    return f"{base} {calib}" if calib else base


# ---- best-effort calibration sentence + audit emission ----


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
