"""Per-unit worktree isolation for evidence collectors (G2).

Provides the per_unit dispatch path for ``run_gate_collectors``: each
collector executes inside its OWN ``tempfile.mkdtemp``-rooted git
worktree at the gate commit SHA, optionally in parallel via a bounded
``ThreadPoolExecutor``. Closes the TOCTOU / no-parallelism / crash-spread
gaps left by the single shared-checkout loop in
``collector_runner.run_gate_collectors``.

Hard guardrails honored by this module (audit-floor pinned):

* No process-global state mutation (``os.chdir``, ``os.environ``,
  ``signal.signal``).
* No ``_bmad/*.lock`` acquisition — workers MUST NOT contend with the
  parent's ``.gate.lock``.
* BaseException at the worker boundary is reified as an outcome AND
  re-raised AFTER the outcomes list is collected, so the operator
  signal propagates and the 1:1 outcome-per-collector invariant holds.
* ``KeyboardInterrupt`` on the main thread drains the queue
  (``pool.shutdown(wait=False, cancel_futures=True)``) but lets
  in-flight ``subprocess.run`` calls complete to their per-category
  timeout.
* Worker thread name is saved-then-restored via ``try/finally`` so the
  ThreadPoolExecutor's reusable worker threads don't leak a stale
  ``sa-isolated-*`` name across tasks.
* ``AuditLockTimeout`` is caught specifically and the affected
  collector is retried ONCE before being reified as
  ``_audit_timeout_outcome`` — distinguishes slow-disk events from
  true collector failures.
"""

from __future__ import annotations

import string
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from .audit import AuditLockTimeout
from .collector_checkout import (
    CollectorCheckoutError,
    cleanup_collector_checkout,
    create_collector_checkout,
)
from .collector_config import CollectorConfig, CollectorOutcome
from .evidence_io import persist_evidence_record
from .gate_audit import EvidenceCollectedAudit, emit_gate_audit
from .gate_schema import make_evidence_record

__all__ = [
    "IsolationMode",
    "DEFAULT_MAX_WORKERS",
    "MAX_PARALLEL_CEILING",
    "ESTIMATED_PER_WORKER_BYTES",
    "ADD_TIMEOUT_PER_UNIT_S",
    "run_collectors_per_unit",
]

IsolationMode = Literal["shared", "per_unit"]

# Spec §5.1 — public surface constants.
DEFAULT_MAX_WORKERS: int = 4
MAX_PARALLEL_CEILING: int = 16
ESTIMATED_PER_WORKER_BYTES: int = 256 * 1024 * 1024  # 256 MiB per worker.
ADD_TIMEOUT_PER_UNIT_S: int = 90

# Local helper constants (duplicated from collector_checkout to avoid
# Stage 2 -> Stage 1 coupling per the plan's §Stage 2 note).
_NAME_HINT_TAIL_CAP: int = 32
_ALLOWED_NAME_HINT_CHARSET: frozenset[str] = frozenset(string.ascii_letters + string.digits + "._-")

_VALID_ISOLATION_MODES: frozenset[str] = frozenset({"shared", "per_unit"})

# BaseException subclasses that ALWAYS propagate (after outcome
# collection) even if they happen at the worker boundary. KeyboardInterrupt
# + SystemExit are honored as operator signals. MemoryError is included
# per AC-I-14 — an OOM mid-pool is fatal to the gate and must surface.
_FATAL_BASEEXC: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    MemoryError,
    GeneratorExit,
)


def _validate_isolation_kwargs(
    isolation_mode: str,
    max_workers: int,
) -> None:
    """Early kwarg validation (HIGH #6).

    Called at the TOP of every entry point (``run_gate_collectors``,
    ``run_production_gate``, ``run_system_gate``, ``_run_collectors``)
    BEFORE any other work — before ``assert_host_context``, before
    gate-lock acquisition. Validates BOTH modes (no silent acceptance
    of ``max_workers="four"`` in ``shared`` mode).

    Raises:
        TypeError: ``max_workers`` is not an int (booleans excluded —
            ``bool`` is a subclass of ``int`` and would otherwise sneak
            through, an operator footgun).
        ValueError: ``isolation_mode`` is not in {"shared", "per_unit"}.
    """
    # bool is a subclass of int — reject it explicitly.
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise TypeError(f"max_workers must be int, not {type(max_workers).__name__}")
    if isolation_mode not in _VALID_ISOLATION_MODES:
        raise ValueError(
            f"isolation_mode must be one of "
            f"{sorted(_VALID_ISOLATION_MODES)!r}, got {isolation_mode!r}"
        )


def _sanitize_name_hint(hint: str) -> str:
    """Sanitize an operator-supplied name_hint into a worktree-suffix-safe slug.

    Duplicate of ``collector_checkout._sanitize_name_hint``. Co-located
    here so this module does not import a private helper across the
    public-surface boundary. Order is sanitize-FIRST (drop chars not in
    ``[A-Za-z0-9._-]``) then truncate-SECOND (take LAST 32 chars). The
    last-32 tail preserves a disambiguating suffix when multiple
    collector ids share a long prefix.
    """
    if not hint:
        return ""
    sanitized = "".join(ch for ch in hint if ch in _ALLOWED_NAME_HINT_CHARSET)
    if not sanitized:
        return ""
    return sanitized[-_NAME_HINT_TAIL_CAP:]


def _clamp_max_workers(
    requested: int,
    project_root: str | Path | None = None,
) -> int:
    """Clamp ``requested`` to ``min(MAX_PARALLEL_CEILING, cpu-2, ram_ceiling)``.

    Spec §3 formula (single source of truth):

      cpu_ceiling = min(16, max(1, (os.cpu_count() or 4) - 2))
      ram_ceiling = max(1, available_bytes // ESTIMATED_PER_WORKER_BYTES)
      return max(1, min(requested, cpu_ceiling, ram_ceiling))

    The ``project_root`` arg is accepted for future-proofing (per-fs
    inspection) and is currently unused. When ``psutil.virtual_memory``
    raises (test fixtures, oddball platforms), ``ram_ceiling`` falls
    back to ``cpu_ceiling`` so the clamp degrades gracefully without
    ever crashing.
    """
    del project_root  # currently unused; reserved for future expansion.
    import os

    cpu_count = os.cpu_count() or 4
    cpu_ceiling = min(MAX_PARALLEL_CEILING, max(1, cpu_count - 2))
    try:
        import psutil

        avail = psutil.virtual_memory().available
        ram_ceiling = max(1, int(avail // ESTIMATED_PER_WORKER_BYTES))
    except Exception:
        ram_ceiling = cpu_ceiling
    return max(1, min(int(requested), cpu_ceiling, ram_ceiling))


def _create_unit_checkout(
    project_root: str | Path,
    commit_sha: str,
    name_hint: str,
    add_timeout: int,
) -> Path:
    """Delegate to ``create_collector_checkout`` with both additive kwargs."""
    return create_collector_checkout(
        project_root,
        commit_sha,
        name_hint=name_hint,
        add_timeout=add_timeout,
    )


def _cleanup_unit_checkout(
    checkout: Path,
    project_root: str | Path,
) -> None:
    """Best-effort cleanup. Mirrors ``cleanup_collector_checkout`` semantics.

    Never raises: catches ``OSError`` + ``RuntimeError`` and swallows.
    Cleanup failures are orthogonal to the collector outcome (they do
    NOT produce an error evidence record).
    """
    try:
        cleanup_collector_checkout(checkout, project_root)
    except (OSError, RuntimeError):
        pass


def _make_error_outcome(
    config: CollectorConfig,
    findings: list[str],
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None,
    audit_path: Path | None,
) -> CollectorOutcome:
    """Mirror ``collector_runner``'s error path: persist evidence + emit audit."""
    evidence = make_evidence_record(
        collector=config.collector_id,
        tool=config.tool,
        category=config.category,
        status="error",
        findings=findings,
        exit_code=-1,
        deterministic=config.deterministic,
    )
    try:
        persisted = persist_evidence_record(project_root, gate_id, evidence)
    except Exception:
        persisted = None
    if audit_policy is not None and audit_path is not None:
        try:
            emit_gate_audit(
                audit_policy,
                audit_path,
                EvidenceCollectedAudit(
                    gate_id=gate_id,
                    category=config.category,
                    collector=config.collector_id,
                    tool=config.tool,
                    status="error",
                    duration_ms=0,
                ),
            )
        except Exception:
            # Audit emission failure here is observability-only and
            # must not corrupt the outcome.
            pass
    return CollectorOutcome(
        config=config,
        evidence=evidence,
        persisted_path=persisted,
    )


def _error_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify a checkout-creation failure as an ``error`` outcome."""
    return _make_error_outcome(
        config, [f"checkout failed: {exc}"], project_root, gate_id, audit_policy, audit_path
    )


def _crash_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify a worker-thread Exception / BaseException as ``error`` outcome.

    The finding string carries the exception type name so operators can
    distinguish a crash from a slow-disk audit timeout.
    """
    return _make_error_outcome(
        config,
        [f"worker terminated: {type(exc).__name__}: {exc}"],
        project_root,
        gate_id,
        audit_policy,
        audit_path,
    )


def _audit_timeout_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify an ``AuditLockTimeout`` (after retry) as an ``error`` outcome.

    Finding string is intentionally distinct from ``_crash_outcome``.
    """
    return _make_error_outcome(
        config,
        [f"audit lock timeout after retry: {exc}"],
        project_root,
        gate_id,
        audit_policy,
        audit_path,
    )


def _run_isolated(
    config: CollectorConfig,
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    audit_policy: dict[str, Any] | None,
    audit_path: Path | None,
) -> CollectorOutcome:
    """Run a single collector inside its OWN fresh worktree.

    Thread-name save+restore (MED #4 fix) — ThreadPoolExecutor reuses
    worker threads across tasks; without restore, stack traces from
    task B incorrectly attribute to collector A.

    Failure ladder:
        1. Checkout creation: ``CollectorCheckoutError`` -> ``_error_outcome``.
        2. ``run_single_collector`` ``AuditLockTimeout`` -> retry once.
        3. ``Exception`` -> ``_crash_outcome``.
        4. ``BaseException`` -> ``_crash_outcome`` (then re-raised in
            ``run_collectors_per_unit`` after outcomes are sorted).
    Cleanup always runs in ``finally``; cleanup failure is best-effort.
    """
    current_thread = threading.current_thread()
    original_name = current_thread.name
    current_thread.name = f"sa-isolated-{config.collector_id}"
    checkout: Path | None = None
    kw = dict(audit_policy=audit_policy, audit_path=audit_path)
    try:
        try:
            checkout = _create_unit_checkout(
                project_root,
                commit_sha,
                name_hint=config.collector_id,
                add_timeout=ADD_TIMEOUT_PER_UNIT_S,
            )
        except CollectorCheckoutError as exc:
            return _error_outcome(config, exc, project_root, gate_id, **kw)

        # Lazy import — avoids any module-load cycle between
        # collector_runner and collector_isolation.
        from .collector_runner import run_single_collector

        def _invoke() -> CollectorOutcome:
            return run_single_collector(
                config=config,
                checkout_path=str(checkout),
                profile=profile,
                gate_id=gate_id,
                project_root=project_root,
                audit_policy=audit_policy,
                audit_path=audit_path,
            )

        try:
            return _invoke()
        except AuditLockTimeout:
            # MED #6 fix: slow-disk audit-lock contention gets ONE
            # retry before being reified as an error.
            try:
                return _invoke()
            except AuditLockTimeout as exc2:
                return _audit_timeout_outcome(config, exc2, project_root, gate_id, **kw)
        except Exception as exc:
            return _crash_outcome(config, exc, project_root, gate_id, **kw)
        except BaseException as exc:
            # HIGH #7 fix: BaseException at worker boundary. Outcome
            # is recorded; the original exception is propagated AGAIN
            # from the as_completed loop in run_collectors_per_unit.
            return _crash_outcome(config, exc, project_root, gate_id, **kw)
    finally:
        if checkout is not None:
            _cleanup_unit_checkout(checkout, project_root)
        current_thread.name = original_name


def run_collectors_per_unit(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    collectors: list[CollectorConfig],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> list[CollectorOutcome]:
    """Run ``collectors`` in parallel, each inside its own fresh worktree.

    See module docstring for the trust + safety invariants. Spec §4
    architecture box pins the precise algorithm; this implementation
    matches it line-for-line.

    Returns the outcomes list sorted by ``(category, collector_id)``
    ASCII ascending. Length is 1:1 with the input ``collectors`` list.
    If a worker raised ``KeyboardInterrupt`` / ``SystemExit`` /
    ``MemoryError`` / etc., the BaseException is RE-RAISED after the
    outcomes have been collected and persisted to disk.
    """
    if not collectors:
        return []

    clamped = _clamp_max_workers(max_workers, project_root)

    outcomes: list[CollectorOutcome] = []
    pending_baseexc: BaseException | None = None
    future_to_config: dict[Future[CollectorOutcome], CollectorConfig] = {}

    pool = ThreadPoolExecutor(
        max_workers=clamped,
        thread_name_prefix="sa-collector",
    )
    try:
        for config in collectors:
            fut = pool.submit(
                _run_isolated,
                config,
                project_root,
                gate_id,
                commit_sha,
                profile,
                audit_policy,
                audit_path,
            )
            future_to_config[fut] = config
        try:
            for fut in as_completed(future_to_config):
                cfg = future_to_config[fut]
                try:
                    outcomes.append(fut.result())
                except BaseException as exc:
                    # Worker raised before _run_isolated could reify it
                    # (e.g. a BaseException escaped the inner catch).
                    # Record a crash outcome so the 1:1 invariant
                    # holds, then capture KI/SystemExit/etc. for the
                    # post-loop re-raise.
                    outcomes.append(
                        _crash_outcome(
                            cfg,
                            exc,
                            project_root,
                            gate_id,
                            audit_policy=audit_policy,
                            audit_path=audit_path,
                        )
                    )
                    if isinstance(exc, _FATAL_BASEEXC):
                        # KeyboardInterrupt, SystemExit, MemoryError,
                        # GeneratorExit, BaseExceptionGroup-only roots —
                        # flag for re-raise after outcome sort.
                        pending_baseexc = exc
        except KeyboardInterrupt as exc:
            # HIGH #7 fix: drain the queue; in-flight subprocesses
            # complete to their per-category timeout.
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            pending_baseexc = exc
    finally:
        # If we exited via KeyboardInterrupt we already drained; the
        # second shutdown with wait=False is a no-op. For the normal
        # path we still need to release the worker threads.
        try:
            pool.shutdown(wait=(pending_baseexc is None))
        except Exception:
            pass

    outcomes.sort(
        key=lambda o: (o.config.category, o.config.collector_id),
    )
    if pending_baseexc is not None:
        raise pending_baseexc
    return outcomes
