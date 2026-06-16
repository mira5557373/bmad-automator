# M03-M2 — Budget Ceilings: Evaluator Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the evaluator half of the M03 budget-ceilings module — `evaluate_ceilings()`, the bypass helper, and the ledger-streaming summation — so the BMAD step markdown (M03-M3) and the `sw cli ceiling-check` dispatcher can call into a complete, deterministic verdict surface.

**Architecture:** The M03-M1 data types (`CeilingDecision`, `BudgetCeiling`, `parse_ceilings_config`) already exist. This sub-milestone appends three callable surfaces to `core/budget_ceilings.py`: (1) a private `_compute_spent(events_path, window, now_iso)` that streams the JSONL ledger through `parse_event` from `core.telemetry_events` and sums `cost_usd` under the four window contracts in REQ-08; (2) a public `evaluate_ceilings(events_path, gate_name, now_iso, *, ceilings=None, workflow_json_path=None) -> tuple[CeilingDecision, str]` that filters ceilings by `gate_name`, computes spend per ceiling, applies the REQ-09 verdict, and merges multiple ceilings with declaration-order tiebreak (REQ-10); (3) a public `bypass_allowed()` reading `BMAD_ALLOW_CEILING_BYPASS` and `sys.stdin.isatty()` per REQ-11. The evaluator is read-only (REQ-12), deterministic (NFR), and tolerant of `\r\n` / trailing blanks / missing ledger (NFR).

**Tech Stack:** Python 3.11+, stdlib only (`datetime`, `os`, `sys`, `pathlib`), plus the existing `core.common` and `core.telemetry_events`. Tests use `unittest.TestCase` and build fixtures by composing concrete M01 event instances and serializing them through `compact_json` (REQ-15). No third-party dependency is added or imported. BMAD step markdown wiring (REQ-13) and the `sw cli ceiling-check` dispatcher entry are explicitly **out of scope** for this sub-milestone and ship in M03-M3.

---

## File Structure

- **Modify** `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` (~211 LOC → ~360 LOC; cap is 500)
  - Add imports: `datetime as dt`, `os`, `sys` (stdlib only)
  - Add module-level `_WINDOW_SECONDS: dict[str, int]` constant for the 4 windows
  - Add private `_parse_iso_timestamp(value: str) -> dt.datetime | None`
  - Add private `_compute_spent(events_path, window, now_iso) -> float`
  - Add public `evaluate_ceilings(...) -> tuple[CeilingDecision, str]`
  - Add public `bypass_allowed() -> bool`
  - Update `__all__` to include `evaluate_ceilings` and `bypass_allowed`
- **Modify** `tests/test_budget_ceilings.py` (~412 LOC → ≤500 LOC; cap is 500)
  - Add module-level `_write_ledger(tmp, events) -> Path` helper hoisted at top of file
  - Add `EvaluateCeilingsNoConfigTests` (REQ-06 no-config path)
  - Add `EvaluateCeilingsEmptyLedgerTests` (REQ-08 missing + empty file)
  - Add `EvaluateCeilingsDecisionRuleTests` (REQ-09 ALLOW/WARN/BLOCK + reason format)
  - Add `EvaluateCeilingsGateFilterTests` (REQ-07)
  - Add `EvaluateCeilingsWindowTests` (REQ-08 each of 4 windows honored)
  - Add `EvaluateCeilingsMultiCeilingTests` (REQ-10 severity merge + tiebreak)
  - Add `EvaluateCeilingsLineEndingTests` (NFR `\r\n` + trailing blanks + malformed lines)
  - Add `EvaluateCeilingsDeterminismTests` (NFR 100-call byte-identical)
  - Add `BypassAllowedTests` (REQ-11 truth table)
  - Test file must end ≤500 LOC measured by `wc -l`

No other files are modified in this sub-milestone. REQ-13 (BMAD step markdown insertion at `steps-c/step-01-init.md`, `story_start`, `retry_start`) and the `sw cli ceiling-check` subcommand are deferred to M03-M3.

---

## Task 1: Add evaluator stubs and update `__all__`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-06 (signature surface), REQ-11 (`bypass_allowed` surface), REQ-12 (allowed imports).

The goal of this task is to introduce the public-name surface area as a no-op so subsequent tasks can layer behavior on without re-doing the import structure. Both functions raise `NotImplementedError` at this point — tests written here only assert that the names exist and are imported.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py` (just before `if __name__ == "__main__":`):

```python
class EvaluatorSurfaceTests(unittest.TestCase):
    def test_evaluate_ceilings_is_importable(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings  # noqa: F401

    def test_bypass_allowed_is_importable(self) -> None:
        from story_automator.core.budget_ceilings import bypass_allowed  # noqa: F401

    def test_exports_include_new_callables(self) -> None:
        self.assertIn("evaluate_ceilings", budget_ceilings.__all__)
        self.assertIn("bypass_allowed", budget_ceilings.__all__)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 3 errors — `ImportError: cannot import name 'evaluate_ceilings'` and `'bypass_allowed'`, plus `AssertionError` on the `__all__` membership check.

- [ ] **Step 3: Add the stubs to `budget_ceilings.py`**

Edit the imports block at the top of the source to add the stdlib modules we will need (only stdlib per REQ-12):

```python
import datetime as dt
import os
import sys
```

Append below `parse_ceilings_config`:

```python
def evaluate_ceilings(
    events_path: str | Path,
    gate_name: str,
    now_iso: str,
    *,
    ceilings: list[BudgetCeiling] | None = None,
    workflow_json_path: str | Path | None = None,
) -> tuple[CeilingDecision, str]:
    """Evaluate budget ceilings against a JSONL ledger (REQ-06).

    Returns the most severe ``CeilingDecision`` across all ceilings whose
    ``gate_names`` tuple contains ``gate_name``, along with a reason
    string describing the deciding ceiling. When both ``ceilings`` and
    ``workflow_json_path`` are ``None`` the function returns the
    ``(ALLOW, "no_ceilings_configured")`` sentinel rather than reading
    anything (REQ-06).
    """
    raise NotImplementedError


def bypass_allowed() -> bool:
    """Check whether ceiling enforcement may be bypassed (REQ-11).

    Returns ``True`` only when both ``BMAD_ALLOW_CEILING_BYPASS == "1"``
    in the environment **and** ``sys.stdin.isatty()`` is true. Any other
    combination returns ``False``. Never prompts and never reads stdin.
    """
    raise NotImplementedError
```

Update `__all__`:

```python
__all__ = [
    "BudgetCeiling",
    "CeilingDecision",
    "bypass_allowed",
    "evaluate_ceilings",
    "parse_ceilings_config",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (3 new tests, the `NotImplementedError` body is never executed because the tests only import the names).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): scaffold evaluate_ceilings and bypass_allowed (M03-M2)"
```

---

## Task 2: `evaluate_ceilings` — no-config sentinel returns `(ALLOW, "no_ceilings_configured")`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-06 — when both `ceilings` and `workflow_json_path` are `None`, return `(ALLOW, "no_ceilings_configured")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsNoConfigTests(unittest.TestCase):
    def test_both_none_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings("events.jsonl", "init", "2026-06-15T00:00:00Z")
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_empty_ceilings_list_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings(
            "events.jsonl", "init", "2026-06-15T00:00:00Z", ceilings=[]
        )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_no_config_path_does_not_touch_ledger(self) -> None:
        """Sentinel must short-circuit before any file I/O."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        verdict, reason = evaluate_ceilings(
            "/nonexistent/path/to/events.jsonl",
            "init",
            "2026-06-15T00:00:00Z",
        )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 3 errors — `NotImplementedError` from the stub.

- [ ] **Step 3: Implement the sentinel and the source-resolution rule**

Replace the body of `evaluate_ceilings` in `budget_ceilings.py`:

```python
def evaluate_ceilings(
    events_path: str | Path,
    gate_name: str,
    now_iso: str,
    *,
    ceilings: list[BudgetCeiling] | None = None,
    workflow_json_path: str | Path | None = None,
) -> tuple[CeilingDecision, str]:
    """Evaluate budget ceilings against a JSONL ledger (REQ-06).

    Resolves ceilings from the ``ceilings`` argument if supplied,
    otherwise from ``workflow_json_path`` via ``parse_ceilings_config``.
    When both are ``None`` returns the
    ``(ALLOW, "no_ceilings_configured")`` sentinel without reading the
    ledger. Otherwise filters by ``gate_name`` (REQ-07), streams the
    ledger to compute spend per window (REQ-08), applies the per-ceiling
    verdict (REQ-09), and merges multiple verdicts taking the most
    severe with declaration-order tiebreak (REQ-10).
    """
    if ceilings is None and workflow_json_path is None:
        return CeilingDecision.ALLOW, "no_ceilings_configured"
    resolved: list[BudgetCeiling]
    if ceilings is not None:
        resolved = ceilings
    else:
        # workflow_json_path is not None per the guard above
        resolved = parse_ceilings_config(workflow_json_path)  # type: ignore[arg-type]
    if not resolved:
        return CeilingDecision.ALLOW, "no_ceilings_configured"
    # Gate filter, ledger streaming, and verdict merge land in later
    # tasks. Until then, an applicable-but-unimplemented call returns
    # the sentinel so the test surface stays green.
    return CeilingDecision.ALLOW, "no_ceilings_configured"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (3 new tests pass; the `evaluate_ceilings` body now short-circuits cleanly).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): evaluate_ceilings returns no-config sentinel (M03 REQ-06)"
```

---

## Task 3: Hoist `_write_ledger` test helper

**Files:**
- Modify: `tests/test_budget_ceilings.py`

The remaining evaluator tests all need to write a JSONL ledger from a list of M01 event instances. To keep the test file under the 500-LOC cap, hoist a shared helper at module level alongside the existing `_c`, `_run_ceilings`, `_run_payload`, `_run_raw`.

- [ ] **Step 1: Add the helper at module top**

Insert after `_run_raw` in `tests/test_budget_ceilings.py`:

```python
def _write_ledger(tmp, events, *, eol="\n", trailing_blanks=0):
    """Write M01 ``events`` to ``events.jsonl`` under ``tmp``.

    Each event is serialized through ``compact_json(event.to_dict())``
    per REQ-15. ``eol`` defaults to ``\\n`` but tests can pass ``\\r\\n``
    to exercise the NFR line-ending tolerance. ``trailing_blanks``
    appends N blank lines to the end of the file to exercise the same.
    """
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = eol.join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += eol
    body += eol * trailing_blanks
    path.write_text(body, encoding="utf-8")
    return path
```

- [ ] **Step 2: Verify nothing regresses**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS — the helper is unused by existing tests so nothing should change.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): hoist _write_ledger helper for evaluator fixtures"
```

---

## Task 4: `evaluate_ceilings` — empty/missing ledger returns ALLOW

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-08 (ledger streaming), REQ-09 (decision rule), NFR (missing ledger implies zero spend). REQ-14 evaluator subset: empty ledger returning ALLOW.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsEmptyLedgerTests(unittest.TestCase):
    def _ceiling(self):
        return BudgetCeiling(
            name="c1",
            window="per_run",
            limit_usd=10.0,
            warn_at=0.8,
            gate_names=("init",),
        )

    def test_missing_ledger_file_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "events.jsonl"
            verdict, reason = evaluate_ceilings(
                missing, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")

    def test_empty_ledger_file_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=0.0000:limit=10.0000")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 2 failures — the current body still returns `"no_ceilings_configured"` even when a ceiling is supplied.

- [ ] **Step 3: Add `_WINDOW_SECONDS` and a minimal `_compute_spent`**

Edit `budget_ceilings.py`. Add the window-seconds map below `_REQUIRED_KEYS` (use the exact REQ-08 values):

```python
_WINDOW_SECONDS: dict[str, int] = {
    "per_run": 0,  # sentinel — "0" means "no time filter, sum all events"
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}
```

Add a private streaming-summation helper. The window filter ships in Task 6 — this initial cut sums every event with a `cost_usd` attribute regardless of `now_iso`:

```python
def _compute_spent(
    events_path: str | Path,
    window: str,
    now_iso: str,
) -> float:
    """Stream the JSONL ledger and sum ``cost_usd`` (REQ-08).

    Missing file returns ``0.0``. Lines that fail to parse via
    ``parse_event`` are skipped (NFR line-ending tolerance). Events
    without a ``cost_usd`` attribute do not contribute. The ``window``
    filter is applied in Task 6; this cut sums all events.
    """
    path = Path(events_path)
    if not path.is_file():
        return 0.0
    total = 0.0
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n").strip()
            if not line:
                continue
            try:
                event = parse_event(line)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            cost = getattr(event, "cost_usd", None)
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                total += float(cost)
    return total
```

Add the `parse_event` import at the top of the file. This is the first local import in `budget_ceilings.py` — place it below the stdlib imports, separated by a blank line, so the standard ordering (stdlib → local) holds:

```python
from .telemetry_events import parse_event
```

Replace the trailing block of `evaluate_ceilings` to wire in spend computation and the per-ceiling decision (gate filtering arrives in Task 7; for now any non-empty `resolved` list uses the first ceiling):

```python
    # Use the first (and, until Task 8, only) ceiling — gate filtering
    # and multi-ceiling severity merging arrive in later tasks.
    ceiling = resolved[0]
    spent = _compute_spent(events_path, ceiling.window, now_iso)
    return _decide(ceiling, spent)
```

Add the verdict helper directly above `evaluate_ceilings`:

```python
def _decide(ceiling: BudgetCeiling, spent: float) -> tuple[CeilingDecision, str]:
    """Apply the REQ-09 verdict and produce the reason string."""
    reason = (
        f"{ceiling.name}:{ceiling.window}"
        f":spent={spent:.4f}:limit={ceiling.limit_usd:.4f}"
    )
    if spent >= ceiling.limit_usd:
        return CeilingDecision.BLOCK, reason
    if spent >= ceiling.limit_usd * ceiling.warn_at:
        return CeilingDecision.WARN, reason
    return CeilingDecision.ALLOW, reason
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (2 new tests). The reason string for both is `"c1:per_run:spent=0.0000:limit=10.0000"`.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): _compute_spent streams JSONL and skips bad lines (M03 REQ-08)"
```

---

## Task 5: Decision rule — ALLOW / WARN / BLOCK boundary tests

**Files:**
- Test: `tests/test_budget_ceilings.py` (no source change expected)

Spec reference: REQ-09 — `spent >= limit_usd → BLOCK`; `spent >= limit_usd * warn_at → WARN`; else `ALLOW`. Reason string `f"{name}:{window}:spent={spent:.4f}:limit={limit_usd:.4f}"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsDecisionRuleTests(unittest.TestCase):
    def _ceiling(self):
        return BudgetCeiling(
            name="c1",
            window="per_run",
            limit_usd=10.0,
            warn_at=0.8,
            gate_names=("init",),
        )

    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_below_warn_threshold_returns_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(1.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "c1:per_run:spent=1.0000:limit=10.0000")

    def test_at_warn_threshold_returns_warn(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            # 10.0 * 0.8 = 8.0 exactly
            path = _write_ledger(tmp, [self._event(8.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertEqual(reason, "c1:per_run:spent=8.0000:limit=10.0000")

    def test_between_warn_and_limit_returns_warn(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(5.0), self._event(4.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertEqual(reason, "c1:per_run:spent=9.0000:limit=10.0000")

    def test_at_limit_returns_block(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(10.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertEqual(reason, "c1:per_run:spent=10.0000:limit=10.0000")

    def test_above_limit_returns_block(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(12.5)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertEqual(reason, "c1:per_run:spent=12.5000:limit=10.0000")
```

- [ ] **Step 2: Run tests to verify they pass**

The source already implements `_decide()` (Task 4). Run:
`PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (5 new tests). If any test fails, the bug is in `_decide` — fix in `budget_ceilings.py` until green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): cover ALLOW/WARN/BLOCK boundary cases (M03 REQ-09)"
```

---

## Task 6: Window filter using `_parse_iso_timestamp`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-08 — `per_run` sums all events; `24h` / `7d` / `30d` sum only events within 86400 / 604800 / 2592000 seconds of `now_iso`.

The `iso_now()` helper from `core.common` produces timestamps in the exact form `"YYYY-MM-DDTHH:MM:SSZ"`. Python's `datetime.fromisoformat` parses this directly on 3.11+ once `Z` is replaced with `+00:00`. Lines whose timestamp is unparseable contribute nothing (NFR tolerance).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsWindowTests(unittest.TestCase):
    def _event(self, ts, cost):
        return StoryCompleted(
            timestamp=ts,
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def _ceiling(self, window):
        return BudgetCeiling(
            name="c1",
            window=window,
            limit_usd=100.0,
            warn_at=0.5,
            gate_names=("init",),
        )

    def test_per_run_sums_all_events_regardless_of_timestamp(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        # 30-year-old event and a current event both count under per_run.
        events = [self._event("1996-01-01T00:00:00Z", 3.0),
                  self._event("2026-06-15T00:00:00Z", 4.0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("per_run")],
            )
        self.assertIn("spent=7.0000", reason)

    def test_24h_excludes_events_older_than_86400_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-06-13T23:59:59Z", 5.0),  # > 24h before now
            self._event("2026-06-14T01:00:00Z", 7.0),  # within 24h
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=7.0000", reason)

    def test_7d_excludes_events_older_than_604800_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-06-07T23:59:59Z", 5.0),  # > 7d
            self._event("2026-06-10T00:00:00Z", 9.0),  # within 7d
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("7d")],
            )
        self.assertIn("spent=9.0000", reason)

    def test_30d_excludes_events_older_than_2592000_seconds(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-05-15T23:59:59Z", 5.0),  # > 30d
            self._event("2026-05-20T00:00:00Z", 11.0),  # within 30d
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("30d")],
            )
        self.assertIn("spent=11.0000", reason)

    def test_unparseable_event_timestamp_is_skipped_in_windowed_modes(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("not-a-timestamp", 99.0),
            self._event("2026-06-14T12:00:00Z", 3.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=3.0000", reason)

    def test_future_event_beyond_window_is_excluded(self) -> None:
        """REQ-08 'within N seconds' is symmetric: events arbitrarily
        far in the future of ``now_iso`` must NOT be counted."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [
            self._event("2026-12-31T00:00:00Z", 50.0),  # ~6 months in future
            self._event("2026-06-14T12:00:00Z", 3.0),   # within 24h
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=3.0000", reason)

    def test_unparseable_now_iso_short_circuits_to_zero_in_windowed_modes(self) -> None:
        """A bad ``now_iso`` plus a windowed ceiling cannot anchor a
        time filter, so the safe behavior is to count zero spend
        (NFR tolerance)."""
        from story_automator.core.budget_ceilings import evaluate_ceilings

        events = [self._event("2026-06-14T12:00:00Z", 50.0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "not-a-timestamp",
                ceilings=[self._ceiling("24h")],
            )
        self.assertIn("spent=0.0000", reason)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: at least 4 failures — `24h`, `7d`, `30d`, and `unparseable_now_iso` tests all fail because the current `_compute_spent` ignores `now_iso`.

- [ ] **Step 3: Implement the window filter**

Edit `budget_ceilings.py`. Add a tolerant timestamp parser near the top of the file, after `_WINDOW_SECONDS`:

```python
def _parse_iso_timestamp(value: str) -> dt.datetime | None:
    """Parse an ``iso_now()``-style timestamp (REQ-08 anchor).

    Accepts the canonical ``"YYYY-MM-DDTHH:MM:SSZ"`` shape emitted by
    ``core.common.iso_now`` and any other ISO-8601 string accepted by
    ``datetime.fromisoformat`` once a trailing ``Z`` is normalized to
    ``+00:00``. Returns ``None`` on failure rather than raising —
    callers treat unparseable timestamps as out-of-window (zero spend).
    """
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed
```

Replace `_compute_spent` with a version that filters by window:

```python
def _compute_spent(
    events_path: str | Path,
    window: str,
    now_iso: str,
) -> float:
    """Stream the JSONL ledger and sum ``cost_usd`` (REQ-08).

    Window semantics (REQ-08):
    - ``per_run`` sums all events regardless of timestamp.
    - ``24h`` / ``7d`` / ``30d`` sum events whose timestamp is within
      86400 / 604800 / 2592000 seconds of ``now_iso``.

    Missing file, parse failures, and missing ``cost_usd`` attributes
    all contribute zero. An unparseable ``now_iso`` under a windowed
    mode short-circuits to zero spend (no anchor available).
    """
    path = Path(events_path)
    if not path.is_file():
        return 0.0
    delta_seconds = _WINDOW_SECONDS.get(window, 0)
    anchor: dt.datetime | None = None
    if delta_seconds > 0:
        anchor = _parse_iso_timestamp(now_iso)
        if anchor is None:
            return 0.0
    total = 0.0
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n").strip()
            if not line:
                continue
            try:
                event = parse_event(line)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            cost = getattr(event, "cost_usd", None)
            if not isinstance(cost, (int, float)) or isinstance(cost, bool):
                continue
            if anchor is not None:
                ts = _parse_iso_timestamp(getattr(event, "timestamp", ""))
                if ts is None:
                    continue
                # REQ-08 "within N seconds of now_iso" is symmetric:
                # past events older than the window AND future events
                # further out than the window are both excluded.
                if abs((anchor - ts).total_seconds()) > delta_seconds:
                    continue
            total += float(cost)
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (6 new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): window-aware spend summation (M03 REQ-08)"
```

---

## Task 7: Gate-name filtering

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-07 — `gate_name` is one of `{"init", "story_start", "retry_start"}`; only ceilings whose `gate_names` tuple contains `gate_name` apply.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsGateFilterTests(unittest.TestCase):
    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_ceiling_not_listing_gate_is_ignored(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        # Ceiling only applies to "story_start" but caller asks "init".
        ceiling = BudgetCeiling(
            name="only_story_start",
            window="per_run",
            limit_usd=1.0,
            warn_at=0.5,
            gate_names=("story_start",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(99.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[ceiling]
            )
        # No applicable ceiling — sentinel takes over.
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")

    def test_ceiling_listing_gate_is_applied(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        ceiling = BudgetCeiling(
            name="any_gate",
            window="per_run",
            limit_usd=10.0,
            warn_at=0.8,
            gate_names=("init", "story_start", "retry_start"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(11.0)])
            for gate in ("init", "story_start", "retry_start"):
                with self.subTest(gate=gate):
                    verdict, reason = evaluate_ceilings(
                        path, gate, "2026-06-15T00:00:00Z", ceilings=[ceiling]
                    )
                    self.assertEqual(verdict, CeilingDecision.BLOCK)
                    self.assertIn("any_gate", reason)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 1 failure — `test_ceiling_not_listing_gate_is_ignored` fails because the current `evaluate_ceilings` does not filter by `gate_name` and reports `BLOCK` with `only_story_start`.

- [ ] **Step 3: Add the gate filter**

Edit `evaluate_ceilings` in `budget_ceilings.py`. Replace the body after the `resolved` block:

```python
    applicable = [c for c in resolved if gate_name in c.gate_names]
    if not applicable:
        return CeilingDecision.ALLOW, "no_ceilings_configured"
    # Multi-ceiling severity merge lands in Task 8 — pick first for now.
    ceiling = applicable[0]
    spent = _compute_spent(events_path, ceiling.window, now_iso)
    return _decide(ceiling, spent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (2 new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): filter ceilings by gate_name (M03 REQ-07)"
```

---

## Task 8: Multi-ceiling severity merge with declaration-order tiebreak

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-10 — most severe verdict (`BLOCK > WARN > ALLOW`) wins; ties broken by declaration order in `workflow.json` (i.e., position in the `ceilings` list).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsMultiCeilingTests(unittest.TestCase):
    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_block_outranks_warn(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        # First ceiling reaches WARN at 2 USD; second reaches BLOCK at 1 USD.
        c1 = BudgetCeiling(name="cap_a", window="per_run", limit_usd=2.0,
                           warn_at=0.5, gate_names=("init",))
        c2 = BudgetCeiling(name="cap_b", window="per_run", limit_usd=1.0,
                           warn_at=0.5, gate_names=("init",))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(1.5)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[c1, c2]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertIn("cap_b", reason)

    def test_warn_outranks_allow(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        c1 = BudgetCeiling(name="cap_a", window="per_run", limit_usd=100.0,
                           warn_at=0.5, gate_names=("init",))
        c2 = BudgetCeiling(name="cap_b", window="per_run", limit_usd=10.0,
                           warn_at=0.5, gate_names=("init",))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(6.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[c1, c2]
            )
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertIn("cap_b", reason)

    def test_tie_break_uses_declaration_order(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        # Both ceilings hit BLOCK at 1.0 USD; the first-declared wins.
        c1 = BudgetCeiling(name="first", window="per_run", limit_usd=1.0,
                           warn_at=0.5, gate_names=("init",))
        c2 = BudgetCeiling(name="second", window="per_run", limit_usd=1.0,
                           warn_at=0.5, gate_names=("init",))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(2.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[c1, c2]
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertTrue(reason.startswith("first:"))

    def test_all_ceilings_below_warn_returns_allow_with_first_reason(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        c1 = BudgetCeiling(name="alpha", window="per_run", limit_usd=100.0,
                           warn_at=0.9, gate_names=("init",))
        c2 = BudgetCeiling(name="beta", window="per_run", limit_usd=200.0,
                           warn_at=0.9, gate_names=("init",))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(1.0)])
            verdict, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[c1, c2]
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        # On a pure ALLOW outcome the reason refers to the first-declared
        # ceiling per REQ-10's tiebreak rule.
        self.assertTrue(reason.startswith("alpha:"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: failures — current source picks the first applicable ceiling rather than the most severe.

- [ ] **Step 3: Implement the severity merge**

Edit `evaluate_ceilings` in `budget_ceilings.py`. Replace the body after the `applicable` block:

```python
    # Compute every applicable verdict in declaration order so the
    # tiebreak rule (REQ-10) emerges naturally from iteration order.
    verdicts: list[tuple[CeilingDecision, str]] = []
    for ceiling in applicable:
        spent = _compute_spent(events_path, ceiling.window, now_iso)
        verdicts.append(_decide(ceiling, spent))
    # max() with key picks the most severe; equal-severity ties are
    # resolved by Python's stable max returning the earlier element.
    # Use a manual scan to lock in stability across Python versions.
    worst_index = 0
    worst_rank = _RANK[verdicts[0][0]]
    for i in range(1, len(verdicts)):
        rank = _RANK[verdicts[i][0]]
        if rank > worst_rank:
            worst_index = i
            worst_rank = rank
    return verdicts[worst_index]
```

Add the rank table near the top of the file, after `_WINDOW_SECONDS`:

```python
_RANK: dict[CeilingDecision, int] = {
    CeilingDecision.ALLOW: 0,
    CeilingDecision.WARN: 1,
    CeilingDecision.BLOCK: 2,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (4 new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): merge multi-ceiling verdicts by severity (M03 REQ-10)"
```

---

## Task 9: Line-ending tolerance (`\r\n`, trailing blanks, malformed lines)

**Files:**
- Test: `tests/test_budget_ceilings.py` (no source change expected — `_compute_spent` already strips `\r\n` and skips blanks/malformed lines)

Spec reference: NFR line-endings — tolerate `\r\n` and trailing blank lines; NFR — must not require the ledger file to exist.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsLineEndingTests(unittest.TestCase):
    def _ceiling(self):
        return BudgetCeiling(
            name="c1",
            window="per_run",
            limit_usd=100.0,
            warn_at=0.5,
            gate_names=("init",),
        )

    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_crlf_line_endings_are_tolerated(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(
                tmp, [self._event(2.0), self._event(3.0)], eol="\r\n"
            )
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertIn("spent=5.0000", reason)

    def test_trailing_blank_lines_are_tolerated(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(7.0)], trailing_blanks=5)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertIn("spent=7.0000", reason)

    def test_malformed_lines_are_skipped(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        # Mix garbage and a valid event.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            valid = compact_json(self._event(4.0).to_dict())
            path.write_text(
                "not json\n{}\n[1,2,3]\n" + valid + "\n", encoding="utf-8"
            )
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertIn("spent=4.0000", reason)

    def test_event_without_cost_usd_attribute_contributes_zero(self) -> None:
        """``StoryStarted`` has no ``cost_usd``; mixing it must not blow up
        and must not add to the total."""
        from story_automator.core.budget_ceilings import evaluate_ceilings
        from story_automator.core.telemetry_events import StoryStarted

        events = [
            StoryStarted(
                timestamp="2026-06-15T00:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                agent="dev",
                model="m",
                complexity="L",
            ),
            self._event(3.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, events)
            _, reason = evaluate_ceilings(
                path, "init", "2026-06-15T00:00:00Z", ceilings=[self._ceiling()]
            )
        self.assertIn("spent=3.0000", reason)
```

- [ ] **Step 2: Run tests to verify they pass**

Source already tolerates these (per Task 4's `_compute_spent`). Run:
`PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (4 new tests). If anything regresses, harden `_compute_spent` until green — specifically, `line.rstrip("\r\n").strip()` should swallow trailing whitespace.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): tolerate CRLF and malformed ledger lines (M03 NFR)"
```

---

## Task 10: `bypass_allowed` truth table

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `tests/test_budget_ceilings.py`

Spec reference: REQ-11 — returns `True` only when both `BMAD_ALLOW_CEILING_BYPASS == "1"` and `sys.stdin.isatty()` is true; any other combination returns `False`; never prompts or reads input.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class BypassAllowedTests(unittest.TestCase):
    def setUp(self) -> None:
        # Save the prior env so we can restore it.
        self._prior = os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)
        if self._prior is not None:
            os.environ["BMAD_ALLOW_CEILING_BYPASS"] = self._prior

    def _run(self, env_value, isatty_value):
        if env_value is None:
            os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)
        else:
            os.environ["BMAD_ALLOW_CEILING_BYPASS"] = env_value
        from story_automator.core.budget_ceilings import bypass_allowed
        with mock.patch("sys.stdin.isatty", return_value=isatty_value):
            return bypass_allowed()

    def test_env_unset_and_no_tty_returns_false(self) -> None:
        self.assertFalse(self._run(None, False))

    def test_env_unset_with_tty_returns_false(self) -> None:
        self.assertFalse(self._run(None, True))

    def test_env_set_no_tty_returns_false(self) -> None:
        self.assertFalse(self._run("1", False))

    def test_env_set_with_tty_returns_true(self) -> None:
        self.assertTrue(self._run("1", True))

    def test_env_set_to_other_value_returns_false(self) -> None:
        for value in ["0", "true", "yes", "TRUE", "01"]:
            with self.subTest(env=value):
                self.assertFalse(self._run(value, True))
```

Hoist `import os` and `import unittest.mock as mock` at the top of `tests/test_budget_ceilings.py`. Add to the existing top-of-file import block (the M03-M1 source currently has neither):

```python
import os
import unittest.mock as mock
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 5 errors — `NotImplementedError` from the bypass stub.

- [ ] **Step 3: Implement `bypass_allowed`**

Replace the body of `bypass_allowed` in `budget_ceilings.py`:

```python
def bypass_allowed() -> bool:
    """Check whether ceiling enforcement may be bypassed (REQ-11).

    Returns ``True`` only when both the environment variable
    ``BMAD_ALLOW_CEILING_BYPASS`` equals the exact string ``"1"`` and
    ``sys.stdin.isatty()`` is true. Any other value (including ``"0"``,
    ``"true"``, ``"yes"``) returns ``False``. Never prompts and never
    reads stdin — callers that want operator confirmation must do that
    themselves at the call site.
    """
    if os.environ.get("BMAD_ALLOW_CEILING_BYPASS") != "1":
        return False
    return bool(sys.stdin.isatty())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (5 new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): bypass_allowed env + isatty truth table (M03 REQ-11)"
```

---

## Task 11: Determinism gate — 100 calls produce byte-identical output

**Files:**
- Test: `tests/test_budget_ceilings.py` (no source change expected if `_compute_spent` is order-stable)

Spec reference: NFR determinism — two calls with the same inputs return byte-identical results; dict/set iteration must not influence output. Quality gate: 100-call replay.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsDeterminismTests(unittest.TestCase):
    def _event(self, cost):
        return StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        )

    def test_one_hundred_calls_byte_identical(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        ceilings = [
            BudgetCeiling(name=f"c{i}", window="per_run", limit_usd=10.0,
                          warn_at=0.5, gate_names=("init",))
            for i in range(4)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_ledger(tmp, [self._event(6.0), self._event(2.5)])
            outputs = {
                evaluate_ceilings(
                    path, "init", "2026-06-15T00:00:00Z", ceilings=ceilings
                )
                for _ in range(100)
            }
        # All 100 calls collapse into a single tuple.
        self.assertEqual(len(outputs), 1)
        verdict, reason = outputs.pop()
        self.assertEqual(verdict, CeilingDecision.WARN)
        self.assertTrue(reason.startswith("c0:"))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (1 new test). If the call set has more than one tuple, dict-iteration order is leaking through somewhere — audit `_compute_spent` and the rank scan in `evaluate_ceilings` until output is stable.

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): determinism gate — 100 calls byte-identical (M03 NFR)"
```

---

## Task 12: `workflow_json_path` source path — REQ-06 end-to-end

**Files:**
- Test: `tests/test_budget_ceilings.py` (no source change expected — `evaluate_ceilings` already calls `parse_ceilings_config` when `ceilings is None`)

Spec reference: REQ-06 — evaluator must accept either an in-memory `ceilings` list or a `workflow_json_path` and route to `parse_ceilings_config` for the latter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_budget_ceilings.py`:

```python
class EvaluateCeilingsConfigSourceTests(unittest.TestCase):
    def test_workflow_json_path_is_read_through_parser(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "workflow.json"
            workflow.write_text(
                compact_json({"policy": {"cost_ceilings": [
                    {"name": "from_disk", "window": "per_run",
                     "limit_usd": 5.0, "warn_at": 0.5,
                     "gate_names": ["init"]}
                ]}}),
                encoding="utf-8",
            )
            events = StoryCompleted(
                timestamp="2026-06-15T00:00:00Z", run_id="r1",
                epic="E1", story_key="S1", duration_s=1.0,
                cost_usd=6.0, tokens_in=0, tokens_out=0, attempts=1,
            )
            ledger = _write_ledger(tmp, [events])
            verdict, reason = evaluate_ceilings(
                ledger, "init", "2026-06-15T00:00:00Z",
                workflow_json_path=workflow,
            )
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertTrue(reason.startswith("from_disk:"))

    def test_workflow_json_path_with_no_ceilings_returns_sentinel(self) -> None:
        from story_automator.core.budget_ceilings import evaluate_ceilings

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "workflow.json"
            workflow.write_text(
                compact_json({"policy": {"cost_ceilings": []}}),
                encoding="utf-8",
            )
            verdict, reason = evaluate_ceilings(
                "irrelevant.jsonl",
                "init",
                "2026-06-15T00:00:00Z",
                workflow_json_path=workflow,
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (2 new tests). The disk-read path already runs through `parse_ceilings_config` (added in Task 2).

- [ ] **Step 3: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): workflow_json_path source path round-trip (M03 REQ-06)"
```

---

## Task 13: Quality gate sweep — ruff, allowlist grep, line count, compileall, coverage

**Files:**
- Modify (formatting only): `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Modify (formatting only): `tests/test_budget_ceilings.py`

Spec reference: Quality gates — `ruff check`, `ruff format --check`, import-allowlist grep, `wc -l <= 500`, `python -m compileall`, coverage `--fail-under=85`.

- [ ] **Step 1: Ruff lint**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py tests/test_budget_ceilings.py`
Expected: exit 0. Likely fires: unused imports, line-too-long, blank-line spacing. Fix inline.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py tests/test_budget_ceilings.py`
Expected: exit 0. If it reports diffs, run `python -m ruff format <paths>` and review the diff before the final commit.

- [ ] **Step 3: Import-allowlist grep**

REQ-12 forbids `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `filelock`, `psutil` in `core/budget_ceilings.py`.

Run via the Grep tool: pattern `requests|httpx|aiohttp|subprocess|os\.system|filelock|psutil` on `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`.
Expected: zero matches. If something fires, refactor to stdlib-only.

- [ ] **Step 4: Line-count check**

Run (Python wrapper for cross-platform consistency):

```bash
python -c "import sys; print(sum(1 for _ in open('skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py', encoding='utf-8')))"
python -c "import sys; print(sum(1 for _ in open('tests/test_budget_ceilings.py', encoding='utf-8')))"
```

Expected: both values ≤ 500. If the test file is over 500, fall through to Task 14 (compaction). The source file should land near 350 LOC.

- [ ] **Step 5: Compileall gate**

Run: `python -m compileall skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
Expected: exit 0.

- [ ] **Step 5b: Placeholder-token grep**

Spec quality gate: "no occurrence of unresolved four-letter placeholder tokens inside the two new files". Use the Grep tool with pattern `\bTODO\b|\bFIXME\b|\bXXXX\b|\bTKTK\b|\bWIP\b` on `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` and `tests/test_budget_ceilings.py`.
Expected: zero matches. Any hit must be resolved (real action items get tracked elsewhere; comments must use full prose).

- [ ] **Step 6: Full test sweep + coverage**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core -m unittest tests.test_budget_ceilings
python -m coverage report -m --fail-under=85 --include="*/core/budget_ceilings.py"
```

Expected: discover sweep green; coverage on `budget_ceilings.py` ≥ 85%. Branches that may need extra coverage:
- `_compute_spent`: missing-file, blank-line skip, malformed-line skip, missing-cost-attr skip, unparseable-event-timestamp skip, unparseable-now-iso early-return
- `evaluate_ceilings`: no-config sentinel, empty-applicable sentinel, multi-ceiling severity merge
- `bypass_allowed`: each leg of the truth table
- `_parse_iso_timestamp`: empty input, non-string input, malformed input, valid `Z`-suffixed input, naive-datetime path

If coverage falls below 85%, add the missing branch test before continuing.

- [ ] **Step 7: Commit (formatting only, if anything changed)**

If `ruff format` changed anything:

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(budget-ceilings): apply ruff format"
```

Otherwise skip.

---

## Task 14: Test-file LOC compaction

**Files:**
- Modify: `tests/test_budget_ceilings.py`

Spec reference: NFR / quality gates — test file must remain ≤500 LOC.

The M03-M1 baseline lands the test file at 412 LOC. Adding the M03-M2 evaluator suite (~200 LOC of new test classes) will push it well over the 500-LOC cap. Compaction is therefore expected to be necessary in every realistic execution path. Always run this task after Task 13 — if Task 13 Step 4 already reported ≤500 LOC, this task becomes a no-op but it must still be checked off so the LOC gate is documented green at the milestone tail.

- [ ] **Step 1: Identify reducible patterns**

Common reductions, in order of safety:
1. Collapse repeated `StoryCompleted(...)` constructions into a shared module-level `_completed(cost, ts="2026-06-15T00:00:00Z")` helper alongside `_write_ledger`.
2. Collapse repeated `BudgetCeiling(name=..., window=..., limit_usd=..., warn_at=..., gate_names=...)` calls into a module-level `_ceiling(name="c1", window="per_run", limit_usd=10.0, warn_at=0.5, gates=("init",))` helper.
3. Merge tightly related single-line subTest cases into list-driven `with self.subTest(...):` loops (the existing `bad_limit_usd_value` test already uses this pattern).
4. Drop redundant `self.assertEqual(verdict, CeilingDecision.X)` lines when the reason string match already implies the verdict.

Do **not** reduce by deleting tests — coverage and REQ-14 alignment must remain intact.

- [ ] **Step 2: Apply the smallest set of reductions to land at ≤500 LOC**

Edit `tests/test_budget_ceilings.py`. After each reduction, re-run the test suite to confirm zero regressions.

- [ ] **Step 3: Re-run line-count check**

```bash
python -c "print(sum(1 for _ in open('tests/test_budget_ceilings.py', encoding='utf-8')))"
```

Expected: ≤ 500.

- [ ] **Step 4: Final test sweep**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS, unchanged count from the previous green run.

- [ ] **Step 5: Commit**

```bash
git add tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "refactor(budget-ceilings): compact evaluator tests to stay under 500 LOC"
```

---

## Coverage map

| Requirement | Tasks |
|---|---|
| REQ-06 (`evaluate_ceilings` signature, no-config sentinel) | 1, 2, 12 |
| REQ-07 (gate-name filtering) | 7 |
| REQ-08 (ledger streaming, window summation) | 4, 6, 9 |
| REQ-09 (decision rule, reason format) | 4, 5 |
| REQ-10 (multi-ceiling severity merge, declaration tiebreak) | 8 |
| REQ-11 (`bypass_allowed` truth table) | 1, 10 |
| REQ-12 (import allowlist) | 1, 13 |
| REQ-14 (evaluator subset of test matrix) | 4, 5, 6, 7, 8, 10 |
| REQ-15 (fixtures via `compact_json` + M01 events) | 3, 4, 5, 6, 7, 8, 9, 11, 12 |
| NFR determinism (100-call replay) | 11 |
| NFR line-endings (`\r\n`, trailing blanks, missing ledger) | 4, 9 |
| NFR cross-platform (pathlib, no shell separators) | 13 |
| Quality gates (ruff, line count, compileall, coverage) | 13, 14 |

## Out-of-scope for this sub-milestone (deliberate)

- BMAD step markdown insertion at `steps-c/step-01-init.md`, `story_start`, `retry_start` — REQ-13, M03-M3.
- `sw cli ceiling-check` dispatcher subcommand — M03-M3.
- Audit-log integration (HMAC chain) — M04.
- Operator confirmation prompt — REQ-13 requires the prompt at the call site, not inside `bypass_allowed` (REQ-11 forbids the helper from prompting).
- Caching of evaluations or sliding-window indices — spec out-of-scope.
- Mutating the ledger or emitting new event types — REQ-12.
