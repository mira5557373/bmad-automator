# M03-M3 — Budget Ceilings: Bypass, CLI, and Skill Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `evaluate_ceilings` and `bypass_allowed` (delivered in M03-M2) into the operator-facing surface: a new `ceiling-check` CLI subcommand emits a JSON verdict, and three BMAD step markdown files gain ~10-line gate insertions calling `"$scripts" ceiling-check --gate <init|story_start|retry_start>`.

**Architecture:** A new module `commands/ceiling_check.py` exposes `cmd_ceiling_check(args)` — a thin wrapper that parses CLI flags (`--gate`, `--events`, `--workflow`, `--now`), invokes `evaluate_ceilings` from `core.budget_ceilings`, and prints a single compact JSON object containing `ok`, `verdict`, `reason`, and `bypass_allowed`. The dispatcher in `cli.py` registers `"ceiling-check"`. Three step markdown files (`steps-c/step-01-init.md`, `steps-c/step-03-execute.md`, `steps-c/step-03a-execute-review.md`) each receive a ~10-line bash block that calls the CLI, parses the JSON with `jq`, branches on `verdict`, surfaces the reason on `WARN`, and refuses to proceed on `BLOCK` unless `bypass_allowed=true` and the operator confirms interactively. No source change is made to `core/budget_ceilings.py` — REQ-11 is already implemented in M2 and is consumed here.

**Tech Stack:** Python 3.11+ stdlib only (`json`, `sys`); reuse `core.budget_ceilings.evaluate_ceilings`, `core.budget_ceilings.bypass_allowed`, `core.common.iso_now`, `core.common.print_json`. Tests use `unittest.TestCase`, `tempfile.TemporaryDirectory`, `io.StringIO` for stdout capture, and `unittest.mock` for env/isatty manipulation. No third-party dependency is added.

---

## File Structure

- **Create** `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py` (~80 LOC ceiling)
  - `cmd_ceiling_check(args: list[str]) -> int` — the entry point
  - `_flag_map(args)` — small local helper (matches existing `agent_config_cmd.py` style)
- **Modify** `skills/bmad-story-automator/src/story_automator/cli.py`
  - Add import `from .commands.ceiling_check import cmd_ceiling_check`
  - Add `"ceiling-check": cmd_ceiling_check` to the `commands` dict
  - Add `"ceiling-check"` to the `_usage` listing
- **Create** `tests/test_ceiling_check.py` (~350 LOC ceiling, ≤500)
  - Covers: missing-args, ALLOW/WARN/BLOCK happy paths, no-config sentinel, workflow-source path, bypass-flag reflection (REQ-14 bypass subset), unknown gate behavior
- **Modify** `skills/bmad-story-automator/steps-c/step-01-init.md` — insert ~10-line `init` gate check between sections "5. Check Sprint Status" and "6. Setup"
- **Modify** `skills/bmad-story-automator/steps-c/step-03-execute.md` — insert ~10-line `story_start` gate inside the `FOR EACH story` loop, before the spawn block
- **Modify** `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` — insert ~10-line `retry_start` gate inside the review-loop retry branch

No other files are modified. `core/budget_ceilings.py` is read-only in this sub-milestone.

---

## Task 1: Scaffold `ceiling_check.py` and register in dispatcher

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`
- Modify: `skills/bmad-story-automator/src/story_automator/cli.py`
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-13 (CLI dispatch entry point exists).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ceiling_check.py`:

```python
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import StoryCompleted


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a
    string buffer and return ``(exit_code, parsed_json)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


class CmdCeilingCheckSurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.ceiling_check import (  # noqa: F401
            cmd_ceiling_check,
        )

    def test_cli_registers_ceiling_check_subcommand(self) -> None:
        from story_automator import cli

        # Re-running main with an unknown subcommand should not list
        # "ceiling-check" as unknown — it must appear in the dispatch dict.
        # Capture BOTH streams so the stub's print_json doesn't leak into
        # the test runner's stdout.
        err = io.StringIO()
        out = io.StringIO()
        with mock.patch.object(sys, "stderr", err), mock.patch.object(sys, "stdout", out):
            cli.main(["ceiling-check"])
        # Even with missing args, the subcommand must be dispatched
        # (returns non-zero with a structured error, NOT "Unknown command").
        self.assertNotIn("Unknown command: ceiling-check", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: 2 errors — `ModuleNotFoundError: No module named 'story_automator.commands.ceiling_check'` and the dispatch test failing because `cli.main(["ceiling-check"])` prints `Unknown command: ceiling-check`.

- [ ] **Step 3: Create the minimal module**

Create `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`:

```python
"""``sw ceiling-check`` CLI subcommand wrapping ``evaluate_ceilings``.

Thin shell-callable wrapper around ``core.budget_ceilings.evaluate_ceilings``
(M03 REQ-13). Prints a single compact JSON object to stdout describing
the verdict so BMAD step markdown can branch on ``ALLOW`` / ``WARN`` /
``BLOCK`` via ``jq``. Read-only by design — does not write the ledger,
does not call audit-log routines, and does not prompt for input
(REQ-11, REQ-12).
"""

from __future__ import annotations

from ..core.budget_ceilings import bypass_allowed, evaluate_ceilings
from ..core.common import iso_now, print_json


def cmd_ceiling_check(args: list[str]) -> int:
    """Entry point for ``story-automator ceiling-check`` (REQ-13).

    Required flags:
        --gate {init,story_start,retry_start}
        --events <path-to-events.jsonl>

    At least one of:
        --workflow <path-to-workflow.json>
        (or no flag, in which case the no-config sentinel is returned)

    Optional:
        --now <ISO-8601 timestamp> (defaults to ``iso_now()``)
    """
    print_json({"ok": False, "error": "not_implemented"})
    return 1
```

- [ ] **Step 4: Register the subcommand in `cli.py`**

Edit `skills/bmad-story-automator/src/story_automator/cli.py`. Add the import near the other command imports:

```python
from .commands.ceiling_check import cmd_ceiling_check
```

Add to the `commands` dict (keep alphabetical ordering broken — append for clarity):

```python
    "ceiling-check": cmd_ceiling_check,
```

Add `"ceiling-check"` to the `_usage()` for-loop tuple — append after `"agent-config"`:

```python
        "agent-config",
        "ceiling-check",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
        skills/bmad-story-automator/src/story_automator/cli.py \
        tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): scaffold ceiling-check CLI subcommand (M03-M3)"
```

---

## Task 2: Flag parser — missing `--gate` returns structured error

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-13 (dispatcher; missing-arg behavior is implied by the existing CLI convention in `agent_config_cmd.py` and `basic.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckFlagParseTests(unittest.TestCase):
    def test_missing_gate_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(cmd_ceiling_check, [])
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "missing_gate")

    def test_invalid_gate_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(
            cmd_ceiling_check, ["--gate", "bogus", "--events", "events.jsonl"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "invalid_gate")

    def test_missing_events_path_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(cmd_ceiling_check, ["--gate", "init"])
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "missing_events")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: 3 failures — the stub returns `{"ok": false, "error": "not_implemented"}` rather than the specific error codes.

- [ ] **Step 3: Implement the flag parser**

Replace the body of `cmd_ceiling_check` in `ceiling_check.py`:

```python
_VALID_GATES = ("init", "story_start", "retry_start")


def _flag_map(args: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and index + 1 < len(args):
            output[token[2:]] = args[index + 1]
            index += 2
            continue
        index += 1
    return output


def cmd_ceiling_check(args: list[str]) -> int:
    params = _flag_map(args)
    gate = params.get("gate", "")
    events_path = params.get("events", "")
    if not gate:
        print_json({"ok": False, "error": "missing_gate"})
        return 1
    if gate not in _VALID_GATES:
        print_json({"ok": False, "error": "invalid_gate", "gate": gate})
        return 1
    if not events_path:
        print_json({"ok": False, "error": "missing_events"})
        return 1
    print_json({"ok": False, "error": "not_implemented"})
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (3 new tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
        tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): ceiling-check flag parser with gate/events validation (M03-M3)"
```

---

## Task 3: No-config sentinel JSON output

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-06 (no-config sentinel propagated through CLI), REQ-13 (CLI surface).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckNoConfigTests(unittest.TestCase):
    def test_no_workflow_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(
            cmd_ceiling_check,
            ["--gate", "init", "--events", "events.jsonl"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("verdict"), "ALLOW")
        self.assertEqual(payload.get("reason"), "no_ceilings_configured")
        self.assertIn("bypass_allowed", payload)
        self.assertIsInstance(payload["bypass_allowed"], bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: 1 failure — current stub returns `{"ok": false, "error": "not_implemented"}`.

- [ ] **Step 3: Implement the evaluator call and JSON shape**

Replace the trailing block of `cmd_ceiling_check` (after the `missing_events` guard):

```python
    workflow_path: str | None = params.get("workflow") or None
    now_iso = params.get("now") or iso_now()
    verdict, reason = evaluate_ceilings(
        events_path,
        gate,
        now_iso,
        workflow_json_path=workflow_path,
    )
    print_json(
        {
            "ok": True,
            "verdict": verdict.value,
            "reason": reason,
            "bypass_allowed": bypass_allowed(),
        }
    )
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (1 new test).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
        tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): ceiling-check emits no-config sentinel JSON (M03 REQ-06/REQ-13)"
```

---

## Task 4: ALLOW path — workflow + events fixtures produce ALLOW JSON

**Files:**
- Test: `tests/test_ceiling_check.py` (no source change expected — Task 3 wired the evaluator)

Spec reference: REQ-09 (ALLOW verdict), REQ-13 (CLI surface), REQ-15 (fixtures via `compact_json` + M01 events).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ceiling_check.py`:

```python
def _write_workflow(tmp: str, ceilings: list[dict]) -> Path:
    path = Path(tmp) / "workflow.json"
    path.write_text(
        compact_json({"policy": {"cost_ceilings": ceilings}}),
        encoding="utf-8",
    )
    return path


def _write_ledger(tmp: str, events: list[object]) -> Path:
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = "\n".join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _completed(cost: float, ts: str = "2026-06-15T00:00:00Z") -> StoryCompleted:
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


class CmdCeilingCheckAllowTests(unittest.TestCase):
    def test_allow_when_spend_below_warn(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with tempfile.TemporaryDirectory() as tmp:
            wf = _write_workflow(
                tmp,
                [
                    {
                        "name": "per_run_cap",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.8,
                        "gate_names": ["init"],
                    }
                ],
            )
            ledger = _write_ledger(tmp, [_completed(1.0)])
            code, payload = _capture(
                cmd_ceiling_check,
                [
                    "--gate", "init",
                    "--events", str(ledger),
                    "--workflow", str(wf),
                    "--now", "2026-06-15T00:00:00Z",
                ],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertIn("per_run_cap", payload["reason"])
        self.assertIn("spent=1.0000", payload["reason"])
        self.assertIn("limit=10.0000", payload["reason"])
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (1 new test). Task 3 already wired the evaluator end-to-end.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): ceiling-check ALLOW path emits structured reason (M03 REQ-09/REQ-13)"
```

---

## Task 5: WARN and BLOCK paths

**Files:**
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-09 (WARN at `warn_at * limit_usd`, BLOCK at `limit_usd`); REQ-13.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckWarnBlockTests(unittest.TestCase):
    def _run(self, cost: float, gate: str = "init", warn_at: float = 0.8):
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with tempfile.TemporaryDirectory() as tmp:
            wf = _write_workflow(
                tmp,
                [
                    {
                        "name": "cap",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": warn_at,
                        "gate_names": [gate],
                    }
                ],
            )
            ledger = _write_ledger(tmp, [_completed(cost)])
            return _capture(
                cmd_ceiling_check,
                [
                    "--gate", gate,
                    "--events", str(ledger),
                    "--workflow", str(wf),
                    "--now", "2026-06-15T00:00:00Z",
                ],
            )

    def test_warn_at_threshold(self) -> None:
        code, payload = self._run(8.0)  # 10.0 * 0.8
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "WARN")
        self.assertIn("spent=8.0000", payload["reason"])

    def test_warn_between_threshold_and_limit(self) -> None:
        code, payload = self._run(9.0)
        self.assertEqual(payload["verdict"], "WARN")

    def test_block_at_limit(self) -> None:
        code, payload = self._run(10.0)
        self.assertEqual(code, 0)  # CLI exit code remains 0 on BLOCK;
        # callers branch on payload["verdict"].
        self.assertEqual(payload["verdict"], "BLOCK")
        self.assertIn("spent=10.0000", payload["reason"])

    def test_block_above_limit(self) -> None:
        code, payload = self._run(99.0)
        self.assertEqual(payload["verdict"], "BLOCK")
        self.assertIn("spent=99.0000", payload["reason"])

    def test_block_carries_ok_true(self) -> None:
        """BLOCK is a successful evaluation, not a CLI error — ``ok``
        stays true so callers don't conflate a real verdict with a
        flag-parsing failure."""
        _, payload = self._run(99.0)
        self.assertTrue(payload["ok"])
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (5 new tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): ceiling-check WARN/BLOCK paths emit verdict JSON (M03 REQ-09/REQ-13)"
```

---

## Task 6: REQ-14 bypass subset — `bypass_allowed` reflected in CLI JSON

**Files:**
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-11 (`bypass_allowed` helper truth table); REQ-14 (test matrix includes bypass-False-when-env-unset); REQ-13 (CLI surface must surface the bypass flag so markdown can branch).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckBypassReflectionTests(unittest.TestCase):
    """REQ-14 bypass subset — verify ``bypass_allowed`` is reflected in
    the CLI output and only returns ``True`` when both the env var and
    isatty signal agree."""

    def setUp(self) -> None:
        self._prior = os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)
        if self._prior is not None:
            os.environ["BMAD_ALLOW_CEILING_BYPASS"] = self._prior

    def _invoke(self, env_value, isatty_value):
        if env_value is None:
            os.environ.pop("BMAD_ALLOW_CEILING_BYPASS", None)
        else:
            os.environ["BMAD_ALLOW_CEILING_BYPASS"] = env_value
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with mock.patch("sys.stdin.isatty", return_value=isatty_value):
            return _capture(
                cmd_ceiling_check,
                ["--gate", "init", "--events", "no-such.jsonl"],
            )

    def test_bypass_false_when_env_unset(self) -> None:
        _, payload = self._invoke(None, True)
        self.assertFalse(payload["bypass_allowed"])

    def test_bypass_false_when_no_tty(self) -> None:
        _, payload = self._invoke("1", False)
        self.assertFalse(payload["bypass_allowed"])

    def test_bypass_false_for_other_env_values(self) -> None:
        for value in ("0", "true", "yes", "TRUE", "01"):
            with self.subTest(env=value):
                _, payload = self._invoke(value, True)
                self.assertFalse(payload["bypass_allowed"])

    def test_bypass_true_when_env_and_tty_agree(self) -> None:
        _, payload = self._invoke("1", True)
        self.assertTrue(payload["bypass_allowed"])

    def test_bypass_flag_present_even_in_no_config_path(self) -> None:
        """The skill markdown branches on bypass_allowed regardless of
        verdict — the field must be present in EVERY successful payload,
        including the no-config sentinel branch."""
        _, payload = self._invoke(None, False)
        self.assertIn("bypass_allowed", payload)
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertEqual(payload["reason"], "no_ceilings_configured")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (5 new tests — including the `subTest` loop). `bypass_allowed()` from M2 powers this and the CLI already calls it (Task 3).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): ceiling-check reflects bypass_allowed truth table (M03 REQ-11/REQ-14)"
```

---

## Task 7: `--workflow` path round-trip and gate filter via CLI

**Files:**
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-06 (workflow_json_path source), REQ-07 (gate filter), REQ-13.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckGateFilterTests(unittest.TestCase):
    def test_ceiling_only_for_other_gate_returns_no_ceilings(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with tempfile.TemporaryDirectory() as tmp:
            wf = _write_workflow(
                tmp,
                [
                    {
                        "name": "story_only",
                        "window": "per_run",
                        "limit_usd": 1.0,
                        "warn_at": 0.5,
                        "gate_names": ["story_start"],
                    }
                ],
            )
            ledger = _write_ledger(tmp, [_completed(99.0)])
            _, payload = _capture(
                cmd_ceiling_check,
                [
                    "--gate", "init",
                    "--events", str(ledger),
                    "--workflow", str(wf),
                    "--now", "2026-06-15T00:00:00Z",
                ],
            )
        # No applicable ceiling — sentinel takes over.
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertEqual(payload["reason"], "no_ceilings_configured")

    def test_each_gate_name_routes_through_cli(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        for gate in ("init", "story_start", "retry_start"):
            with self.subTest(gate=gate):
                with tempfile.TemporaryDirectory() as tmp:
                    wf = _write_workflow(
                        tmp,
                        [
                            {
                                "name": "any_gate",
                                "window": "per_run",
                                "limit_usd": 5.0,
                                "warn_at": 0.5,
                                "gate_names": ["init", "story_start", "retry_start"],
                            }
                        ],
                    )
                    ledger = _write_ledger(tmp, [_completed(6.0)])
                    _, payload = _capture(
                        cmd_ceiling_check,
                        [
                            "--gate", gate,
                            "--events", str(ledger),
                            "--workflow", str(wf),
                            "--now", "2026-06-15T00:00:00Z",
                        ],
                    )
                self.assertEqual(payload["verdict"], "BLOCK")
                self.assertIn("any_gate", payload["reason"])
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (2 new tests, `test_each_gate_name_routes_through_cli` covers 3 subtests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): ceiling-check honors gate filter and workflow source (M03 REQ-06/REQ-07)"
```

---

## Task 8: `--now` defaults to `iso_now()` when omitted

**Files:**
- Test: `tests/test_ceiling_check.py`

Spec reference: REQ-08 (anchor for window math); REQ-13 (CLI ergonomics — callers should not need to pass `--now` for `per_run` ceilings).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ceiling_check.py`:

```python
class CmdCeilingCheckNowDefaultTests(unittest.TestCase):
    def test_now_omitted_uses_iso_now(self) -> None:
        """For per_run ceilings the anchor is unused, so the test
        verifies the call succeeds without ``--now``. (24h/7d/30d
        windows still resolve against the runtime ``iso_now()``.)"""
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with tempfile.TemporaryDirectory() as tmp:
            wf = _write_workflow(
                tmp,
                [
                    {
                        "name": "cap",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            ledger = _write_ledger(tmp, [_completed(1.0)])
            code, payload = _capture(
                cmd_ceiling_check,
                [
                    "--gate", "init",
                    "--events", str(ledger),
                    "--workflow", str(wf),
                ],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "ALLOW")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_ceiling_check -v`
Expected: PASS (1 new test). Task 3's source already falls back to `iso_now()` when `--now` is absent.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): ceiling-check defaults --now to iso_now() (M03 REQ-13)"
```

---

## Task 9: BMAD `init` gate insertion in `step-01-init.md`

**Files:**
- Modify: `skills/bmad-story-automator/steps-c/step-01-init.md`

Spec reference: REQ-13 — call `sw cli ceiling-check --gate init`, parse tri-state, refuse to proceed on `BLOCK` unless `bypass_allowed()` is true and the operator confirms interactively, surface the reason on `WARN`, silent on `ALLOW`. ≤15 lines per gate site.

The insertion goes between section "5. Check Sprint Status (MANDATORY)" and section "6. Setup", numbered as "5b. Budget Ceiling Preflight (init gate)". Frontmatter gains an `eventsLedger` reference pointing at the standard JSONL location.

> Convention: this plan assumes `events.jsonl` lives at `{output_folder}/story-automator/events.jsonl` (the M02 emitter's canonical path) and `workflow.json` lives at `{project-root}/workflow.json`. The evaluator tolerates missing files (NFR), so misalignment between the assumed location and the actual project layout returns the no-config / zero-spend sentinel rather than an error. Confirm the locations during M03-wire-log-sites integration; if either path is wrong, change only the frontmatter values — the bash block stays identical.

The gate insertion uses two layers of "refuse to proceed": (1) `exit 1` inside the bash sub-shell so any script-driven invocation halts, and (2) an explicit LLM-readable `**HALT**` directive matching the existing convention in section 1 of this same file (lines 38, 54, 64).

- [ ] **Step 1: Add frontmatter keys for the ledger and workflow path**

Edit `skills/bmad-story-automator/steps-c/step-01-init.md`. Append two keys to the frontmatter block (after `settingsFile`):

```yaml
eventsLedger: '{output_folder}/story-automator/events.jsonl'
workflowJson: '{project-root}/workflow.json'
```

- [ ] **Step 2: Insert the gate block**

Insert this block immediately after section "5. Check Sprint Status (MANDATORY)" (between the closing of section 5 and the start of section "6. Setup"):

```markdown
### 5b. Budget Ceiling Preflight (init gate)

Refuse to begin a run if a configured cost ceiling is already breached.

```bash
ceiling=$("{scripts}" ceiling-check --gate init \
  --events "{eventsLedger}" --workflow "{workflowJson}")
verdict=$(echo "$ceiling" | jq -r '.verdict')
reason=$(echo "$ceiling" | jq -r '.reason')
bypass=$(echo "$ceiling" | jq -r '.bypass_allowed')
case "$verdict" in
  BLOCK) echo "❌ Budget ceiling reached: $reason"
         [ "$bypass" = "true" ] && read -r -p "Bypass? [y/N] " ans
         [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1 ;;
  WARN)  echo "⚠️ Budget ceiling warning: $reason" ;;
  ALLOW) : ;;
esac
```

**IF verdict == "BLOCK" and bypass != "true":**
Display: `**Budget ceiling reached** — $reason`
**HALT** — Do not proceed.

**IF verdict == "BLOCK" and bypass == "true":**
Display: `**Budget ceiling reached** — $reason\nBypass requires explicit operator confirmation.`
Wait for the operator's confirmation prompt above. If not confirmed, **HALT**.

**IF verdict == "WARN":**
Display: `⚠️ Budget ceiling warning: $reason`
Continue.
```

(Bash block: 11 lines, comfortably within the "approximately ten lines" guidance. The trailing markdown directives are LLM-readable HALT signals matching the existing step-01-init convention — they do not count against the bash gate budget.)

- [ ] **Step 3: Verify the file still parses as Markdown**

Run a sanity check that the file has not been corrupted:

```bash
python -c "
import re, pathlib
text = pathlib.Path('skills/bmad-story-automator/steps-c/step-01-init.md').read_text(encoding='utf-8')
# Frontmatter must still be a single block at the top
assert text.startswith('---'), 'frontmatter missing'
end = text.index('\n---\n', 1)
print('Frontmatter ends at byte', end)
# Insertion must precede '## Then'
assert text.index('### 5b. Budget Ceiling Preflight') < text.index('## Then')
# Insertion must follow '### 5. Check Sprint Status'
assert text.index('### 5. Check Sprint Status') < text.index('### 5b. Budget Ceiling Preflight')
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Verify no placeholder tokens leaked into the file**

Use the Grep tool with pattern `\bTODO\b|\bFIXME\b|\bXXXX\b|\bTKTK\b|\bWIP\b` on `skills/bmad-story-automator/steps-c/step-01-init.md`.
Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/steps-c/step-01-init.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): wire init gate ceiling-check into step-01-init (M03 REQ-13)"
```

---

## Task 10: BMAD `story_start` gate insertion in `step-03-execute.md`

**Files:**
- Modify: `skills/bmad-story-automator/steps-c/step-03-execute.md`

Spec reference: REQ-13 — equivalent insertion at the `story_start` gate site.

- [ ] **Step 1: Add frontmatter keys for the ledger and workflow path**

Edit `skills/bmad-story-automator/steps-c/step-03-execute.md`. Append to the frontmatter block (after `subagentPrompts`):

```yaml
eventsLedger: '{output_folder}/story-automator/events.jsonl'
workflowJson: '{project-root}/workflow.json'
```

- [ ] **Step 2: Insert the gate block inside the per-story loop**

Inside the "Story Loop" section, immediately after the `awk` initialization of the Story Progress row (around `tmp_state=$(mktemp); awk ... mv "$tmp_state" "$state_file"`), insert:

```markdown

#### Budget Ceiling Preflight (story_start gate)

Refuse to start the next story if a configured ceiling has been reached.

```bash
ceiling=$("$scripts" ceiling-check --gate story_start \
  --events "{eventsLedger}" --workflow "{workflowJson}")
verdict=$(echo "$ceiling" | jq -r '.verdict')
reason=$(echo "$ceiling" | jq -r '.reason')
bypass=$(echo "$ceiling" | jq -r '.bypass_allowed')
case "$verdict" in
  BLOCK) echo "❌ story_start ceiling breached: $reason"
         [ "$bypass" = "true" ] && read -r -p "Bypass? [y/N] " ans
         [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1 ;;
  WARN)  echo "⚠️ story_start ceiling warning: $reason" ;;
  ALLOW) : ;;
esac
```

**IF verdict == "BLOCK" and bypass != "true":** stop the story loop and surface `$reason` to the operator. Do not spawn this story.
**IF verdict == "WARN":** surface `$reason` and continue with the spawn.
**IF verdict == "ALLOW":** silent.
```

- [ ] **Step 3: Verify the file still parses**

```bash
python -c "
import pathlib
text = pathlib.Path('skills/bmad-story-automator/steps-c/step-03-execute.md').read_text(encoding='utf-8')
assert 'Budget Ceiling Preflight (story_start gate)' in text
assert '--gate story_start' in text
assert text.index('## Story Loop') < text.index('Budget Ceiling Preflight (story_start gate)')
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Placeholder grep**

Grep tool pattern `\bTODO\b|\bFIXME\b|\bXXXX\b|\bTKTK\b|\bWIP\b` on `skills/bmad-story-automator/steps-c/step-03-execute.md`.
Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/steps-c/step-03-execute.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): wire story_start gate ceiling-check into step-03-execute (M03 REQ-13)"
```

---

## Task 11: BMAD `retry_start` gate insertion in `step-03a-execute-review.md`

**Files:**
- Modify: `skills/bmad-story-automator/steps-c/step-03a-execute-review.md`

Spec reference: REQ-13 — equivalent insertion at the `retry_start` gate site.

- [ ] **Step 1: Add frontmatter keys**

Edit `skills/bmad-story-automator/steps-c/step-03a-execute-review.md`. Append to the frontmatter block (after `reviewLoop`):

```yaml
eventsLedger: '{output_folder}/story-automator/events.jsonl'
workflowJson: '{project-root}/workflow.json'
```

- [ ] **Step 2: Insert the gate block at the retry decision point**

Inside section "C. Automate (Guardrails)", inside the `FAILURE → retry up to 3 attempts` bullet, immediately BEFORE the bash block that updates the Story Progress to `skip`, insert:

```markdown

Before each retry attempt, check the retry_start ceiling:

```bash
ceiling=$("$scripts" ceiling-check --gate retry_start \
  --events "{eventsLedger}" --workflow "{workflowJson}")
verdict=$(echo "$ceiling" | jq -r '.verdict')
reason=$(echo "$ceiling" | jq -r '.reason')
bypass=$(echo "$ceiling" | jq -r '.bypass_allowed')
case "$verdict" in
  BLOCK) echo "❌ retry_start ceiling breached: $reason"
         [ "$bypass" = "true" ] && read -r -p "Bypass? [y/N] " ans
         [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1 ;;
  WARN)  echo "⚠️ retry_start ceiling warning: $reason" ;;
  ALLOW) : ;;
esac
```

**IF verdict == "BLOCK" and bypass != "true":** stop retrying this story and mark it `skip` per the existing failure path. Surface `$reason` to the operator.
**IF verdict == "WARN":** surface `$reason` and continue with the retry.
**IF verdict == "ALLOW":** silent.
```

- [ ] **Step 3: Verify the file still parses**

```bash
python -c "
import pathlib
text = pathlib.Path('skills/bmad-story-automator/steps-c/step-03a-execute-review.md').read_text(encoding='utf-8')
assert '--gate retry_start' in text
assert 'retry_start ceiling breached' in text
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Placeholder grep**

Grep tool pattern `\bTODO\b|\bFIXME\b|\bXXXX\b|\bTKTK\b|\bWIP\b` on `skills/bmad-story-automator/steps-c/step-03a-execute-review.md`.
Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/steps-c/step-03a-execute-review.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): wire retry_start gate ceiling-check into step-03a-execute-review (M03 REQ-13)"
```

---

## Task 12: NFR enforcement — PEP 604, file size, import allowlist, cross-platform paths

**Files:**
- Verify (no edits expected if Task 1–8 followed the rules): `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`, `tests/test_ceiling_check.py`

Spec reference: NFR PEP 604 (no `typing.Union` / `typing.Optional`), NFR file-size (≤500 LOC), NFR cross-platform (no shell-specific path separators in source), REQ-12 (import allowlist).

- [ ] **Step 1: PEP 604 grep on the new source**

Use the Grep tool with pattern `typing\.Union|typing\.Optional|from typing import (Union|Optional)|Optional\[|Union\[` on:
- `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`
- `tests/test_ceiling_check.py`

Expected: zero matches. If anything fires, rewrite the annotation using PEP 604 (`str | None` instead of `Optional[str]`).

- [ ] **Step 2: Import-allowlist grep**

REQ-12 forbids `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `filelock`, `psutil` in code imported by `core/budget_ceilings.py`. The new `commands/ceiling_check.py` consumes that module — apply the same allowlist.

Grep tool pattern `requests|httpx|aiohttp|subprocess|os\.system|filelock|psutil` on `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`.
Expected: zero matches.

- [ ] **Step 3: Cross-platform path grep**

Look for shell-specific separators in the new source:

Grep tool pattern `\\\\|\\\\\\\\|sep=\\\\| os\.sep ` on `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`.
Expected: zero matches (path operations should go through the consumed `Path` API in `evaluate_ceilings`; the CLI itself does not touch paths directly except via `--events`/`--workflow` string passthrough).

- [ ] **Step 4: File-size check**

Run (cross-platform via Python):

```bash
python -c "print('src LOC:', sum(1 for _ in open('skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py', encoding='utf-8')))"
python -c "print('test LOC:', sum(1 for _ in open('tests/test_ceiling_check.py', encoding='utf-8')))"
```

Expected: src ≤ 500 (target ~80), test ≤ 500 (target ~350).

- [ ] **Step 5: Markdown gate-block size check**

The spec caps the per-gate insertion at "fifteen lines". Count the bash blocks added in Tasks 9-11 to verify:

```bash
python -c "
import re, pathlib
for fname in [
    'skills/bmad-story-automator/steps-c/step-01-init.md',
    'skills/bmad-story-automator/steps-c/step-03-execute.md',
    'skills/bmad-story-automator/steps-c/step-03a-execute-review.md',
]:
    text = pathlib.Path(fname).read_text(encoding='utf-8')
    # Find blocks bracketing a 'ceiling-check' call
    for m in re.finditer(r'\`\`\`bash\n(.*?\n)\`\`\`', text, re.DOTALL):
        block = m.group(1)
        if 'ceiling-check' in block:
            lines = block.count(chr(10))
            print(f'{fname}: ceiling-check block has {lines} lines')
            assert lines <= 18, f'{fname} block too long ({lines} > 18)'
"
```

Expected: each `ceiling-check` block reports ≤18 lines (15 lines of bash plus light wrapping tolerance). If the gate already includes the case statement and exceeds 18, collapse the case into a chained `&&`/`||` form documented in Task 9.

- [ ] **Step 6: Commit (only if anything changed)**

If grep or LOC fixes required edits:

```bash
git add skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
        tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(budget-ceilings): tidy ceiling-check to satisfy PEP 604 and import allowlist"
```

Otherwise skip.

---

## Task 13: Quality gate sweep — ruff, format, compileall, coverage, full discover

**Files:**
- Format (only if `ruff format` reports diffs): `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`, `tests/test_ceiling_check.py`, `skills/bmad-story-automator/src/story_automator/cli.py`

Spec reference: Quality gates — `ruff check`, `ruff format --check`, `python -m compileall`, coverage `--fail-under=85` for `core/budget_ceilings.py` (unchanged in M3, but coverage must still pass after CLI tests increase reachable paths).

- [ ] **Step 1: Ruff lint**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
  skills/bmad-story-automator/src/story_automator/cli.py \
  tests/test_ceiling_check.py
```

Expected: exit 0. Likely candidates if something fires: unused imports, blank-line spacing, line-too-long. Fix inline.

- [ ] **Step 2: Ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
  skills/bmad-story-automator/src/story_automator/cli.py \
  tests/test_ceiling_check.py
```

Expected: exit 0. If diffs are reported, run `python -m ruff format <paths>` and commit the formatting separately.

- [ ] **Step 3: Compileall**

Run:

```bash
python -m compileall \
  skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
  skills/bmad-story-automator/src/story_automator/cli.py
```

Expected: exit 0.

- [ ] **Step 4: Full project test discover**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v
```

Expected: zero failures, zero errors across the entire repo suite (including M01/M02/previous M03 sub-milestones).

- [ ] **Step 5: Coverage on `core/budget_ceilings.py` + new module**

Run (single chained command, matching the spec's quality gate):

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator \
  -m unittest tests.test_budget_ceilings tests.test_ceiling_check
python -m coverage report -m --fail-under=85 \
  --include="*/core/budget_ceilings.py","*/commands/ceiling_check.py"
```

Expected: combined coverage ≥85% on both files. Branches that may need extra coverage in `ceiling_check.py`:
- `missing_gate`, `invalid_gate`, `missing_events` flag-parser branches
- The `_flag_map` loop's `else: index += 1` (single-arg flag like `--help` if accidentally passed)
- The `workflow_path` truthiness branch

If coverage falls below 85%, add the missing branch test and re-run.

- [ ] **Step 6: Placeholder-token grep across all M3-modified files**

Use the Grep tool with pattern `\bTODO\b|\bFIXME\b|\bXXXX\b|\bTKTK\b|\bWIP\b` on:
- `skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py`
- `skills/bmad-story-automator/src/story_automator/cli.py`
- `tests/test_ceiling_check.py`
- `skills/bmad-story-automator/steps-c/step-01-init.md`
- `skills/bmad-story-automator/steps-c/step-03-execute.md`
- `skills/bmad-story-automator/steps-c/step-03a-execute-review.md`

Expected: zero matches.

- [ ] **Step 7: Commit (formatting only, if anything changed)**

If `ruff format` modified files:

```bash
git add skills/bmad-story-automator/src/story_automator/commands/ceiling_check.py \
        skills/bmad-story-automator/src/story_automator/cli.py \
        tests/test_ceiling_check.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(budget-ceilings): apply ruff format to ceiling-check CLI"
```

Otherwise skip.

---

## Coverage map

| Requirement | Tasks |
|---|---|
| REQ-06 (`evaluate_ceilings` no-config sentinel via CLI; workflow source path) | 3, 4, 7, 8 |
| REQ-07 (gate filter via CLI) | 7 |
| REQ-09 (decision rule reason format surfaced as JSON) | 4, 5 |
| REQ-11 (`bypass_allowed` consumed and reflected in CLI JSON) | 3, 6 |
| REQ-12 (import allowlist applies to consumer module) | 12 |
| REQ-13 (CLI dispatch entry + three BMAD step markdown insertions) | 1, 9, 10, 11 |
| REQ-14 (bypass subset: helper returns False when env unset, etc.) | 6 |
| NFR file-size (src ≤500, test ≤500, markdown ≤15/gate) | 12 |
| NFR PEP 604 (no `typing.Union` / `typing.Optional`) | 12 |
| NFR cross-platform (no shell-specific separators) | 12 |
| Quality gates (ruff, format, compileall, coverage ≥85, no placeholders) | 13 |

## Out-of-scope for this sub-milestone (deliberate)

- Modifying `core/budget_ceilings.py` — M3 is wiring only; the evaluator and bypass helper landed in M03-M2.
- Audit-log integration (HMAC chain) — owned by M04.
- Operator confirmation UX beyond a single `read -r -p` line — the spec calls for "operator confirms interactively"; complex menu UX is not in scope.
- `sw run` orchestrator-level pre-emption — the gate is consulted from skill markdown, not from a Python-side wrapper.
- Caching or sliding-window indices for the evaluator — explicit spec out-of-scope.
- Migrating existing emit/log sites to call `ceiling-check` — that pre-orchestrator wiring is M03-wire-log-sites (separate plan).
