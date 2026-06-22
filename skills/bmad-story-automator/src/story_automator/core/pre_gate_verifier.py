"""Pre-gate verifier — six inline checks before any collector runs (Phase 3).

The verifier is the cheap deterministic gate that catches session
hallucinations *before* the expensive gate machinery turns. Each check
returns either ``VerifyOutcome.passed()`` or a precise failure outcome;
the first non-passing check wins, and downstream checks are skipped.

The six checks (in fixed order — earlier checks are cheaper and more
fundamental, so failing one renders later ones meaningless):

  1. **result_present** — ``result.json`` exists at the expected path.
  2. **result_schema** — :func:`result_json.validate_result_json` passes.
  3. **baseline_commit** — ``claims.commit_sha`` matches the worktree
     HEAD, or matches ``baseline_sha`` when provided (delegates to
     :func:`lie_detector.detect_baseline_drift`).
  4. **files_present** — every path in ``claims.files_changed`` exists
     on disk under ``project_root``.
  5. **no_critical_escalations** — ``result.json`` does not claim any
     CRITICAL escalations. (Sessions that hit a CRITICAL escalation
     should not reach the gate at all; if they do, this is the audit
     point.)
  6. **claimed_files_in_diff** — every claimed file actually appears in
     the git diff between ``baseline_sha`` and the worktree HEAD when a
     baseline was provided. Catches the "claimed work but didn't
     actually touch the file" hallucination.

Determinism: outcomes carry no timestamps; the ``failed_check`` field
of the descriptor is one of the six fixed strings above.

Wiring: ``run_production_gate(enable_pre_gate_verifier=False)``
preserves every existing call site. When True, the orchestrator
invokes :func:`verify_pre_gate` before any other step and short-circuits
on the first failing check.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .audit import scrub_env_for_subprocess
from .git_utils import GitError, rev_parse_head, same_commit
from .lie_detector import detect_baseline_drift
from .result_json import (
    ResultJsonApiVersionError,
    ResultJsonError,
    critical_escalations,
    read_result_json,
)
from .verify_outcome import VerifyOutcome

CHECK_NAMES = (
    "result_present",
    "result_schema",
    "baseline_commit",
    "files_present",
    "no_critical_escalations",
    "claimed_files_in_diff",
)


def _check_result_present(
    result_path: Path,
) -> tuple[VerifyOutcome, dict[str, Any] | None]:
    if not result_path.is_file():
        return VerifyOutcome.retry("missing_result_json", fixable=True), None
    return VerifyOutcome.passed(), None


def _check_result_schema(
    result_path: Path,
) -> tuple[VerifyOutcome, dict[str, Any] | None]:
    try:
        payload = read_result_json(result_path)
    except ResultJsonApiVersionError as exc:
        return VerifyOutcome.escalate(
            f"result_json_api_version: {exc}", "CRITICAL",
        ), None
    except ResultJsonError as exc:
        return VerifyOutcome.retry(
            f"result_json_invalid: {exc}", fixable=True,
        ), None
    except Exception as exc:
        return VerifyOutcome.retry(
            f"result_json_unreadable: {exc!r}", fixable=False,
        ), None
    return VerifyOutcome.passed(), payload


def _check_baseline_commit(
    project_root: str | Path,
    payload: dict[str, Any],
    baseline_sha: str | None,
) -> VerifyOutcome:
    claimed_sha = payload["claims"]["commit_sha"]
    if not claimed_sha:
        return VerifyOutcome.retry("missing_claimed_commit_sha", fixable=True)
    return detect_baseline_drift(
        project_root,
        expected_sha=claimed_sha,
        baseline_sha=baseline_sha,
    )


def _check_files_present(
    project_root: str | Path,
    payload: dict[str, Any],
) -> VerifyOutcome:
    root = Path(project_root)
    missing: list[str] = []
    for rel in payload["claims"]["files_changed"]:
        if not (root / rel).exists():
            missing.append(rel)
    if missing:
        return VerifyOutcome.retry(
            f"claimed_files_missing: {sorted(missing)[:5]}",
            fixable=True,
        )
    return VerifyOutcome.passed()


def _check_no_critical_escalations(payload: dict[str, Any]) -> VerifyOutcome:
    crits = critical_escalations(payload)
    if crits:
        # CRITICAL escalations from the session itself: never retry,
        # always escalate to the operator.
        return VerifyOutcome.escalate(
            f"critical_escalations: {len(crits)}", "CRITICAL",
        )
    return VerifyOutcome.passed()


def _check_claimed_files_in_diff(
    project_root: str | Path,
    payload: dict[str, Any],
    baseline_sha: str | None,
) -> VerifyOutcome:
    # Skipped (passes) when no baseline is provided — without a
    # baseline we have nothing to diff against.
    if not baseline_sha:
        return VerifyOutcome.passed()
    try:
        head = rev_parse_head(project_root)
    except GitError as exc:
        return VerifyOutcome.escalate(
            f"git_unavailable: {exc}", "CRITICAL",
        )
    if same_commit(head, baseline_sha):
        # No commit happened; baseline_commit check should have caught
        # this. If we got here with claimed files, it's drift.
        if payload["claims"]["files_changed"]:
            return VerifyOutcome.retry(
                "files_claimed_without_commit", fixable=True,
            )
        return VerifyOutcome.passed()
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-only",
             f"{baseline_sha}..HEAD"],
            capture_output=True, text=True, timeout=30, check=False,
            env=scrub_env_for_subprocess(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return VerifyOutcome.escalate(
            f"git_diff_failed: {exc}", "CRITICAL",
        )
    if result.returncode != 0:
        return VerifyOutcome.escalate(
            f"git_diff_failed: {result.stderr.strip()}", "CRITICAL",
        )
    actually_changed = {
        line.strip() for line in result.stdout.splitlines() if line.strip()
    }
    claimed = set(payload["claims"]["files_changed"])
    not_in_diff = sorted(claimed - actually_changed)
    if not_in_diff:
        return VerifyOutcome.retry(
            f"claimed_files_not_in_diff: {not_in_diff[:5]}",
            fixable=True,
        )
    return VerifyOutcome.passed()


def verify_pre_gate(
    project_root: str | Path,
    *,
    result_path: str | Path,
    baseline_sha: str | None = None,
) -> dict[str, Any]:
    """Run the six inline pre-gate checks in order.

    The first non-passing check wins; remaining checks are skipped.

    Returns:
        ``{"ok": True, "failed_check": "", "verify": <passed wire form>,
        "payload": <result.json payload>}`` on success, or
        ``{"ok": False, "failed_check": <one of CHECK_NAMES>,
        "verify": <wire form of the failing outcome>, "payload": <may
        be None if check 1 or 2 failed>}`` on the first failure.

    The descriptor is shaped for direct embedding in audit events and
    for the orchestrator short-circuit response in
    ``run_production_gate(enable_pre_gate_verifier=True)``.
    """
    result_path = Path(result_path)

    outcome, _ = _check_result_present(result_path)
    if not outcome.ok:
        return _descriptor("result_present", outcome, None)

    outcome, payload = _check_result_schema(result_path)
    if not outcome.ok or payload is None:
        return _descriptor("result_schema", outcome, payload)

    outcome = _check_baseline_commit(project_root, payload, baseline_sha)
    if not outcome.ok:
        return _descriptor("baseline_commit", outcome, payload)

    outcome = _check_files_present(project_root, payload)
    if not outcome.ok:
        return _descriptor("files_present", outcome, payload)

    outcome = _check_no_critical_escalations(payload)
    if not outcome.ok:
        return _descriptor("no_critical_escalations", outcome, payload)

    outcome = _check_claimed_files_in_diff(
        project_root, payload, baseline_sha,
    )
    if not outcome.ok:
        return _descriptor("claimed_files_in_diff", outcome, payload)

    return _descriptor("", VerifyOutcome.passed(), payload)


def _descriptor(
    failed_check: str,
    outcome: VerifyOutcome,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "ok": outcome.ok,
        "failed_check": failed_check,
        "verify": outcome.to_dict(),
        "payload": payload,
    }
