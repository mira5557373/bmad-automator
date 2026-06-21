"""Baseline-commit drift detector — Phase 1 pre-collector guard.

When the orchestrator dispatches a dev session it captures a baseline
SHA. The session is expected to commit its work on top of that SHA and
report the new HEAD. The cheapest hallucination to catch is: the session
claims to have done work, but the worktree HEAD is still the baseline
(or somewhere else entirely). Catching this BEFORE we spin up a fresh
checkout and run 22 collectors saves the better part of a minute per
false-positive cycle.

This module is intentionally tiny — it returns a typed
:class:`VerifyOutcome` and never raises on git-state issues (the gate
should still proceed via its normal failure path if git is just
unhappy). Wiring is feature-flagged in
``run_production_gate(enable_lie_detector=False)`` so existing call
sites keep their exact behavior; Phase 3 will flip the default.

Determinism: this module produces no payload that lands in a gate file
on its own — the orchestrator decides whether to surface the outcome
in audit events.
"""
from __future__ import annotations

from pathlib import Path

from .git_utils import GitError, rev_parse_head, same_commit
from .verify_outcome import VerifyOutcome


def detect_baseline_drift(
    repo: str | Path,
    *,
    expected_sha: str,
    baseline_sha: str | None = None,
) -> VerifyOutcome:
    """Check whether the worktree HEAD matches ``expected_sha``.

    Three outcomes:

    1. HEAD == expected_sha → :py:meth:`VerifyOutcome.passed`.
    2. HEAD == baseline_sha (i.e. no commit happened despite the
       session claiming progress) → ``retry("baseline_drift", fixable=True)``.
       The dev session can be re-prompted with the explicit failing
       transcript.
    3. HEAD is some third commit → ``retry("unexpected_head",
       fixable=False)``. The orchestrator should NOT auto-retry — the
       branch is in a state the gate didn't sanction.

    On git-layer failure (not a repo, git missing, timeout), returns
    :py:meth:`VerifyOutcome.escalate` with severity ``CRITICAL`` — this
    is an operator-visible problem, not a session-retry condition.
    """
    try:
        head = rev_parse_head(repo)
    except GitError as exc:
        return VerifyOutcome.escalate(f"git_unavailable: {exc}", "CRITICAL")

    if same_commit(head, expected_sha):
        return VerifyOutcome.passed()

    if baseline_sha is not None and same_commit(head, baseline_sha):
        return VerifyOutcome.retry("baseline_drift", fixable=True)

    return VerifyOutcome.retry("unexpected_head", fixable=False)
