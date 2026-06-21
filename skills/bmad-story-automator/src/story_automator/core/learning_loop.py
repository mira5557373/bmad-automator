"""Learning loop orchestrator — gate telemetry -> metrics -> calibrate -> retro.

Ties together the learning loop pipeline: loads gate history, computes
metrics, proposes calibrations, applies safe changes, and generates
retrospective summaries for BMAD consumption.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .gate_history import load_gate_history, record_gate_result
from .gate_metrics import compute_gate_metrics
from .profile_calibrator import apply_calibrations, propose_all_calibrations
from .profile_versioning import (
    bump_profile_version,
    parse_profile_version,
)
from .retrospective_bridge import (
    build_retrospective_summary,
    format_retrospective_markdown,
)


def record_gate_for_learning(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> Path:
    """Hook called after each gate evaluation to record for learning."""
    return record_gate_result(
        project_root, gate_file,
        story_key=story_key, remediation_cycle=remediation_cycle,
    )


def run_learning_loop(
    project_root: str | Path,
    *,
    profile: dict[str, Any] | None = None,
    auto_apply_breaking: bool = False,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full learning loop pipeline.

    1. Load gate history
    2. Compute aggregate metrics
    3. Propose calibrations
    4. Apply safe (feature) calibrations
    5. Build retrospective summary + markdown
    6. Emit audit event for calibrations (if any applied)
    """
    history = load_gate_history(project_root)
    metrics = compute_gate_metrics(history)

    calibrations_applied: list[Any] = []
    calibrations_deferred: list[Any] = []
    updated_profile = profile

    if profile is not None:
        proposals = propose_all_calibrations(metrics, profile)
        if proposals:
            updated_profile, calibrations_applied, calibrations_deferred = (
                apply_calibrations(
                    profile, proposals,
                    auto_apply_breaking=auto_apply_breaking,
                )
            )

            if calibrations_applied:
                has_breaking_applied = any(
                    p.change_type == "breaking" for p in calibrations_applied
                )
                bump_type = "breaking" if has_breaking_applied else "feature"
                updated_profile = bump_profile_version(
                    updated_profile, bump_type,
                )

            if (
                calibrations_applied
                and audit_policy is not None
                and audit_path is not None
            ):
                from .gate_audit import GateCalibrationAudit, emit_gate_audit

                old_pv = parse_profile_version(profile)
                new_pv = parse_profile_version(updated_profile)
                emit_gate_audit(
                    audit_policy, audit_path,
                    GateCalibrationAudit(
                        profile_id=profile.get("id", ""),
                        proposals_applied=len(calibrations_applied),
                        proposals_deferred=len(calibrations_deferred),
                        old_version=f"{old_pv.breaking}.{old_pv.feature}",
                        new_version=f"{new_pv.breaking}.{new_pv.feature}",
                    ),
                )

    summary = build_retrospective_summary(
        metrics, calibrations_applied,
        calibrations_deferred=calibrations_deferred,
    )
    retro_md = format_retrospective_markdown(summary)

    return {
        "metrics": metrics,
        "calibrations_applied": calibrations_applied,
        "calibrations_deferred": calibrations_deferred,
        "updated_profile": updated_profile,
        "retrospective_summary": summary,
        "retrospective_md": retro_md,
    }
