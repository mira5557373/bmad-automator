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
from .collector_isolation_outcomes import (
    audit_timeout_outcome as _audit_timeout_outcome,
)
from .collector_isolation_outcomes import (
    crash_outcome as _crash_outcome,
)
from .collector_isolation_outcomes import (
    error_outcome as _error_outcome,
)
from .collector_isolation_outcomes import (
    make_error_outcome as _make_error_outcome,  # noqa: F401 — re-exported for test compat.
)

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
    ``run_production_gate``, ``run_system_gate``) BEFORE any other
    work — before ``assert_host_context``, before gate-lock
    acquisition. ``gate_orchestrator._run_collectors`` validates by
    delegation (it is a thin wrapper that forwards to
    ``run_gate_collectors``); it does NOT call this helper directly.
    Validates BOTH modes (no silent acceptance of
    ``max_workers="four"`` in ``shared`` mode).

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
            except _FATAL_BASEEXC:
                # Post-impl AC-I-14 fix: KeyboardInterrupt / SystemExit /
                # MemoryError (which is an Exception subclass — would
                # otherwise be silently downgraded) / GeneratorExit
                # MUST propagate so ``fut.result()`` re-raises them on
                # the main thread.
                raise
            except Exception as exc:
                return _crash_outcome(config, exc, project_root, gate_id, **kw)
        except _FATAL_BASEEXC:
            # Same propagate-don't-swallow rule on the first attempt.
            raise
        except Exception as exc:
            return _crash_outcome(config, exc, project_root, gate_id, **kw)
        # NOTE: BaseException not in _FATAL_BASEEXC (e.g. a custom
        # operator-defined subclass) still falls through to the outer
        # ``except BaseException`` in run_collectors_per_unit's
        # as_completed loop, which reifies the crash outcome and sets
        # pending_baseexc only when the type is in _FATAL_BASEEXC.
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
    collected_futures: set[int] = set()

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
                collected_futures.add(id(fut))
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
            # AC-I-13: drain the queue but allow IN-FLIGHT workers'
            # subprocess.run to complete to their per-category timeout
            # and have their outcomes collected. The earlier shape used
            # ``cancel_futures=True`` + ``wait=False`` which abandoned
            # already-started workers AND their persisted evidence,
            # breaking the 1:1 outcomes-to-disk invariant.
            #
            # Correct shape:
            #   1. Issue shutdown(wait=True) so currently-running
            #      workers may finish (queued-but-not-started workers
            #      will run too because we cannot reliably distinguish
            #      "started" from "queued"; this is acceptable because
            #      the operator already accepted the per-category
            #      timeout bound by submitting work in the first place
            #      — a second Ctrl-C delivers OS-level signal).
            #   2. After shutdown, drain any futures that finished by
            #      iterating future_to_config and reading results from
            #      futures that ``done()`` returns True for, appending
            #      outcomes the as_completed loop didn't yet pick up.
            try:
                pool.shutdown(wait=True)
            except Exception:
                pass
            # Drain futures the as_completed loop didn't pick up.
            for fut2, cfg2 in future_to_config.items():
                if id(fut2) in collected_futures:
                    continue
                if not fut2.done():
                    continue
                collected_futures.add(id(fut2))
                try:
                    outcomes.append(fut2.result())
                except BaseException as exc2:
                    outcomes.append(
                        _crash_outcome(
                            cfg2,
                            exc2,
                            project_root,
                            gate_id,
                            audit_policy=audit_policy,
                            audit_path=audit_path,
                        )
                    )
            pending_baseexc = exc
    finally:
        # If we exited via KeyboardInterrupt we already drained; the
        # second shutdown with wait=True (no-op for already-shutdown
        # pool) is harmless. For the normal path we still need to
        # release the worker threads.
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
