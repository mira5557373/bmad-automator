# Foundation M3: Factory Self-Trust — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the evidence-integrity trust boundary (spec §7) that makes the gate ungameable — host-only evidence collection, child sandbox formalization, evidence path isolation, fresh checkout for collectors, and gate audit events hash-chained into the existing audit log.

**Architecture:** New `trust_boundary.py` defines and enforces the host/child separation: context guard (is this the orchestrator or the generation child?), sandbox env builder (what env vars are stripped/forced for child sessions), and path isolation (evidence lives outside the child's writable tree). New `collector_checkout.py` manages temporary git worktrees so collectors run against pristine source at a pinned SHA. New `gate_audit.py` provides lightweight audit-protocol-compatible event dataclasses that hash-chain gate operations into the existing HMAC audit log without touching `telemetry_events.py`. Integration touches `adjudicator.py` (host assertion before collector runs), `evidence_io.py` (host assertion before evidence persistence), and `tmux_runtime.py` (sandbox env consolidation).

**Tech Stack:** Python 3.11+, stdlib only (`os`, `pathlib`, `subprocess`, `tempfile`, `shutil`, `dataclasses`); existing `audit.py` Event protocol; existing `gate_schema.py`/`evidence_io.py` factories; `unittest` + `unittest.mock`.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Dedicated gate telemetry events land in M18.
- **500-LOC soft limit per Python module.** `trust_boundary.py` target ≤ 200 LOC; `collector_checkout.py` ≤ 150 LOC; `gate_audit.py` ≤ 120 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/<test_file>.py -v` to validate per-task.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform**: git worktree operations must work on Linux, WSL Ubuntu, git-bash.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py` — host/child context guard, sandbox env builder, evidence path isolation (~180 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collector_checkout.py` — fresh git worktree for collectors (~130 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — audit-protocol event dataclasses + emitter (~100 LOC)
- `tests/test_trust_boundary.py` — unit tests for trust boundary module (~350 LOC)
- `tests/test_collector_checkout.py` — unit tests for collector checkout (~200 LOC)
- `tests/test_gate_audit.py` — unit tests for gate audit events + emitter (~200 LOC)
- `tests/test_trust_integration.py` — end-to-end trust boundary integration tests (~250 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/adjudicator.py` — add `assert_host_context()` guard (~+3 LOC)
- `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` — add `assert_host_context()` guard to persist + clear functions (~+8 LOC)
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py` — use `sandbox_tmux_env_args()` instead of inline env flags (~-8/+4 LOC)
- `tests/test_adjudicator.py` — add trust boundary guard tests (~+30 LOC)
- `tests/test_evidence_io.py` — add trust boundary guard tests (~+40 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/telemetry_emitter.py`, `core/product_profile.py`, `core/profile_bridge.py`, `core/gate_schema.py`, `core/gate_rules.py`.

---

### Task 1: Trust Boundary Core — Host Context Guard

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py`
- Create: `tests/test_trust_boundary.py`

**Interfaces:**
- Consumes: `os.environ` (runtime env var check)
- Produces: `TrustBoundaryError(RuntimeError)`, `is_child_session(env: dict[str, str] | None = None) -> bool`, `assert_host_context(operation: str = "", *, env: dict[str, str] | None = None) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trust_boundary.py`:

```python
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from story_automator.core.trust_boundary import (
    TrustBoundaryError,
    assert_host_context,
    is_child_session,
)


class IsChildSessionTests(unittest.TestCase):
    def test_false_when_env_var_absent(self) -> None:
        self.assertFalse(is_child_session({}))

    def test_false_when_env_var_empty(self) -> None:
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": ""}))

    def test_true_when_env_var_true(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "true"}))

    def test_true_when_env_var_1(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "1"}))

    def test_true_when_env_var_yes(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "yes"}))

    def test_true_case_insensitive(self) -> None:
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "True"}))
        self.assertTrue(is_child_session({"STORY_AUTOMATOR_CHILD": "TRUE"}))

    def test_false_for_other_values(self) -> None:
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "false"}))
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "0"}))
        self.assertFalse(is_child_session({"STORY_AUTOMATOR_CHILD": "no"}))

    def test_reads_os_environ_when_env_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_child_session())
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            self.assertTrue(is_child_session())


class AssertHostContextTests(unittest.TestCase):
    def test_no_raise_when_host(self) -> None:
        assert_host_context("test_op", env={})

    def test_raises_when_child(self) -> None:
        with self.assertRaises(TrustBoundaryError) as ctx:
            assert_host_context("persist_evidence", env={"STORY_AUTOMATOR_CHILD": "true"})
        self.assertIn("persist_evidence", str(ctx.exception))
        self.assertIn("trust boundary violation", str(ctx.exception))

    def test_raises_without_operation_label(self) -> None:
        with self.assertRaises(TrustBoundaryError) as ctx:
            assert_host_context(env={"STORY_AUTOMATOR_CHILD": "1"})
        self.assertIn("trust boundary violation", str(ctx.exception))
        self.assertNotIn(":", str(ctx.exception).split("violation")[1].split("operation")[0])

    def test_reads_os_environ_when_env_none(self) -> None:
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                assert_host_context()

    def test_error_is_runtime_error(self) -> None:
        self.assertTrue(issubclass(TrustBoundaryError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: ModuleNotFoundError — `trust_boundary` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py`:

```python
"""Trust boundary enforcement for the factory's evidence-integrity model.

Spec §7: collectors run on the orchestrator host, never by the generation
child.  Evidence + gate files are written outside the child's working tree
and hash-chained into audit.  The child's self-reports are unverified
hints, never evidence (Blind Hunter principle).
"""
from __future__ import annotations

import os

__all__ = [
    "TrustBoundaryError",
    "is_child_session",
    "assert_host_context",
]

_CHILD_ENV_VAR = "STORY_AUTOMATOR_CHILD"
_TRUTHY_VALUES = frozenset({"true", "1", "yes"})


class TrustBoundaryError(RuntimeError):
    """Raised when a trust-boundary-protected operation is attempted
    from a child session (generation agent)."""


def is_child_session(env: dict[str, str] | None = None) -> bool:
    """Return True if the current process is a generation child session."""
    source = env if env is not None else os.environ
    return source.get(_CHILD_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def assert_host_context(
    operation: str = "",
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Raise TrustBoundaryError if called from a child session.

    Every security-critical operation (evidence persistence, collector
    execution) calls this guard before proceeding.
    """
    if is_child_session(env):
        label = f": {operation}" if operation else ""
        raise TrustBoundaryError(
            f"trust boundary violation{label} — "
            f"operation requires host context but {_CHILD_ENV_VAR} is set"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/trust_boundary.py tests/test_trust_boundary.py
git commit -m "feat(gate): add trust boundary core — host context guard

TrustBoundaryError + is_child_session + assert_host_context enforce
that evidence-critical operations only run on the orchestrator host,
never inside a generation child session (spec §7).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Child Sandbox Env Formalization

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py`
- Modify: `tests/test_trust_boundary.py`

**Interfaces:**
- Consumes: `is_child_session()`, `os.environ`
- Produces: `CHILD_STRIPPED_VARS: frozenset[str]`, `CHILD_FORCED_VARS: dict[str, str]`, `sandbox_env(*, agent: str = "", extras: dict[str, str] | None = None) -> dict[str, str]`, `verify_sandbox_env(env: dict[str, str]) -> tuple[bool, list[str]]`, `sandbox_tmux_env_args(agent: str = "") -> list[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trust_boundary.py`:

```python
from story_automator.core.trust_boundary import (
    CHILD_FORCED_VARS,
    CHILD_STRIPPED_VARS,
    sandbox_env,
    sandbox_tmux_env_args,
    verify_sandbox_env,
)


class ChildSandboxConstantsTests(unittest.TestCase):
    def test_stripped_vars_contains_audit_key(self) -> None:
        self.assertIn("BMAD_AUDIT_KEY", CHILD_STRIPPED_VARS)

    def test_stripped_vars_contains_claudecode(self) -> None:
        self.assertIn("CLAUDECODE", CHILD_STRIPPED_VARS)

    def test_stripped_vars_contains_bash_env(self) -> None:
        self.assertIn("BASH_ENV", CHILD_STRIPPED_VARS)

    def test_stripped_vars_is_frozenset(self) -> None:
        self.assertIsInstance(CHILD_STRIPPED_VARS, frozenset)

    def test_forced_vars_sets_child_flag(self) -> None:
        self.assertEqual(CHILD_FORCED_VARS["STORY_AUTOMATOR_CHILD"], "true")


class SandboxEnvTests(unittest.TestCase):
    def test_strips_security_vars(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret", "PATH": "/usr/bin"}, clear=True):
            env = sandbox_env()
            self.assertNotIn("BMAD_AUDIT_KEY", env)
            self.assertIn("PATH", env)

    def test_forces_child_flag(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertEqual(env["STORY_AUTOMATOR_CHILD"], "true")

    def test_sets_agent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env(agent="claude")
            self.assertEqual(env["AI_AGENT"], "claude")

    def test_no_agent_when_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertNotIn("AI_AGENT", env)

    def test_extras_applied(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env(extras={"MY_VAR": "val"})
            self.assertEqual(env["MY_VAR"], "val")

    def test_strips_all_defined_vars(self) -> None:
        fake_env = {var: "should_strip" for var in CHILD_STRIPPED_VARS}
        with patch.dict(os.environ, fake_env, clear=True):
            env = sandbox_env()
            for var in CHILD_STRIPPED_VARS:
                value = env.get(var, "")
                self.assertEqual(value, "", f"{var} should be stripped but got {value!r}")


class VerifySandboxEnvTests(unittest.TestCase):
    def test_valid_env_passes(self) -> None:
        env = {"STORY_AUTOMATOR_CHILD": "true", "PATH": "/usr/bin"}
        ok, violations = verify_sandbox_env(env)
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_audit_key_present_fails(self) -> None:
        env = {"STORY_AUTOMATOR_CHILD": "true", "BMAD_AUDIT_KEY": "secret"}
        ok, violations = verify_sandbox_env(env)
        self.assertFalse(ok)
        self.assertTrue(any("BMAD_AUDIT_KEY" in v for v in violations))

    def test_missing_child_flag_fails(self) -> None:
        env = {"PATH": "/usr/bin"}
        ok, violations = verify_sandbox_env(env)
        self.assertFalse(ok)
        self.assertTrue(any("STORY_AUTOMATOR_CHILD" in v for v in violations))


class SandboxTmuxEnvArgsTests(unittest.TestCase):
    def test_contains_forced_vars(self) -> None:
        args = sandbox_tmux_env_args()
        self.assertIn("-e", args)
        self.assertIn("STORY_AUTOMATOR_CHILD=true", args)

    def test_contains_stripped_vars_as_empty(self) -> None:
        args = sandbox_tmux_env_args()
        for var in CHILD_STRIPPED_VARS:
            self.assertIn(f"{var}=", args)

    def test_contains_agent_when_specified(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        self.assertIn("AI_AGENT=claude", args)

    def test_no_agent_when_empty(self) -> None:
        args = sandbox_tmux_env_args()
        agent_args = [a for a in args if a.startswith("AI_AGENT=")]
        self.assertEqual(agent_args, [])

    def test_args_are_paired(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        for i in range(0, len(args), 2):
            self.assertEqual(args[i], "-e")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: ImportError — `CHILD_STRIPPED_VARS` etc. not yet exported.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py`, updating `__all__`:

```python
__all__ = [
    "TrustBoundaryError",
    "is_child_session",
    "assert_host_context",
    "CHILD_STRIPPED_VARS",
    "CHILD_FORCED_VARS",
    "sandbox_env",
    "verify_sandbox_env",
    "sandbox_tmux_env_args",
]

# ... (existing code stays above) ...

CHILD_STRIPPED_VARS: frozenset[str] = frozenset({
    "BMAD_AUDIT_KEY",
    "CLAUDECODE",
    "BASH_ENV",
})

CHILD_FORCED_VARS: dict[str, str] = {
    "STORY_AUTOMATOR_CHILD": "true",
}


def sandbox_env(
    *,
    agent: str = "",
    extras: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized env dict for a child generation session.

    Strips security-sensitive vars, forces the child-session flag,
    and optionally sets the AI_AGENT identifier.
    """
    env = dict(os.environ)
    for var in CHILD_STRIPPED_VARS:
        env.pop(var, None)
    env.update(CHILD_FORCED_VARS)
    if agent:
        env["AI_AGENT"] = agent
    if extras:
        env.update(extras)
    return env


def verify_sandbox_env(env: dict[str, str]) -> tuple[bool, list[str]]:
    """Validate that a child env meets sandbox requirements.

    Returns (ok, list_of_violations).
    """
    violations: list[str] = []
    for var in CHILD_STRIPPED_VARS:
        if env.get(var, ""):
            violations.append(f"security-sensitive var {var} not stripped")
    for var, expected in CHILD_FORCED_VARS.items():
        if env.get(var) != expected:
            violations.append(f"required var {var}={expected!r} not set")
    return (len(violations) == 0, violations)


def sandbox_tmux_env_args(agent: str = "") -> list[str]:
    """Return tmux ``-e`` flag pairs for a sandboxed child session.

    Deterministic order: forced vars, then agent (if set), then
    stripped vars (alphabetical).  Matches the env semantics of
    ``tmux new-session -e KEY=VALUE``.
    """
    args: list[str] = []
    for var in sorted(CHILD_FORCED_VARS):
        args.extend(["-e", f"{var}={CHILD_FORCED_VARS[var]}"])
    if agent:
        args.extend(["-e", f"AI_AGENT={agent}"])
    for var in sorted(CHILD_STRIPPED_VARS):
        args.extend(["-e", f"{var}="])
    return args
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/trust_boundary.py tests/test_trust_boundary.py
git commit -m "feat(gate): add child sandbox env formalization

CHILD_STRIPPED_VARS / CHILD_FORCED_VARS / sandbox_env / verify_sandbox_env
/ sandbox_tmux_env_args formalize the env-var sanitization for generation
child sessions.  Extracts the inline tmux -e logic into testable functions.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Evidence Path Isolation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/trust_boundary.py`
- Modify: `tests/test_trust_boundary.py`

**Interfaces:**
- Consumes: `pathlib.Path`
- Produces: `is_path_under(parent: Path, child: Path) -> bool`, `validate_evidence_path_isolation(evidence_path: Path, child_working_tree: Path) -> tuple[bool, str]`, `resolve_host_evidence_dir(project_root: str | Path) -> Path`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trust_boundary.py`:

```python
import tempfile
from pathlib import Path

from story_automator.core.trust_boundary import (
    is_path_under,
    resolve_host_evidence_dir,
    validate_evidence_path_isolation,
)


class IsPathUnderTests(unittest.TestCase):
    def test_child_under_parent(self) -> None:
        self.assertTrue(is_path_under(Path("/a/b"), Path("/a/b/c/d")))

    def test_child_is_parent(self) -> None:
        self.assertTrue(is_path_under(Path("/a/b"), Path("/a/b")))

    def test_child_not_under_parent(self) -> None:
        self.assertFalse(is_path_under(Path("/a/b"), Path("/x/y")))

    def test_traversal_attempt(self) -> None:
        self.assertFalse(is_path_under(Path("/a/b"), Path("/a/b/../c")))

    def test_real_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td) / "parent"
            parent.mkdir()
            child = parent / "sub" / "deep"
            child.mkdir(parents=True)
            self.assertTrue(is_path_under(parent, child))
            self.assertFalse(is_path_under(child, parent))


class ValidateEvidencePathIsolationTests(unittest.TestCase):
    def test_isolated_path_passes(self) -> None:
        ok, reason = validate_evidence_path_isolation(
            Path("/host/evidence"), Path("/child/workdir")
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_evidence_under_child_fails(self) -> None:
        ok, reason = validate_evidence_path_isolation(
            Path("/child/workdir/_bmad/gate"), Path("/child/workdir")
        )
        self.assertFalse(ok)
        self.assertIn("under child working tree", reason)


class ResolveHostEvidenceDirTests(unittest.TestCase):
    def test_returns_bmad_gate_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = resolve_host_evidence_dir(td)
            self.assertEqual(result, Path(td).resolve() / "_bmad" / "gate")

    def test_returns_absolute_path(self) -> None:
        result = resolve_host_evidence_dir("relative/path")
        self.assertTrue(result.is_absolute())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py::IsPathUnderTests tests/test_trust_boundary.py::ValidateEvidencePathIsolationTests tests/test_trust_boundary.py::ResolveHostEvidenceDirTests -v`
Expected: ImportError — functions not yet exported.

- [ ] **Step 3: Write minimal implementation**

Add to `trust_boundary.py`, updating `__all__`:

```python
from pathlib import Path

__all__ = [
    # ... existing entries ...
    "is_path_under",
    "validate_evidence_path_isolation",
    "resolve_host_evidence_dir",
]

# ... (append after sandbox functions) ...


def is_path_under(parent: Path, child: Path) -> bool:
    """Return True if child path is inside (or equal to) parent, resolving symlinks."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_evidence_path_isolation(
    evidence_path: Path,
    child_working_tree: Path,
) -> tuple[bool, str]:
    """Validate that evidence_path is NOT under the child's working tree.

    §7: evidence + gate files must be written outside the child's tmux
    working tree so the generation agent cannot tamper with them.
    """
    if is_path_under(child_working_tree, evidence_path):
        return (
            False,
            f"evidence path {evidence_path} is under child working tree "
            f"{child_working_tree}",
        )
    return (True, "")


def resolve_host_evidence_dir(project_root: str | Path) -> Path:
    """Return the canonical host-controlled gate artifact directory."""
    return Path(project_root).resolve() / "_bmad" / "gate"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/trust_boundary.py tests/test_trust_boundary.py
git commit -m "feat(gate): add evidence path isolation enforcement

is_path_under + validate_evidence_path_isolation + resolve_host_evidence_dir
ensure evidence artifacts live outside the child's writable tree (spec §7).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Collector Checkout — Fresh Worktree at SHA

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collector_checkout.py`
- Create: `tests/test_collector_checkout.py`

**Interfaces:**
- Consumes: `subprocess.run`, `tempfile.mkdtemp`, `shutil.rmtree`
- Produces: `CollectorCheckoutError(RuntimeError)`, `create_collector_checkout(project_root: str | Path, commit_sha: str) -> Path`, `cleanup_collector_checkout(checkout_path: Path, project_root: str | Path | None = None) -> None`, `collector_checkout(project_root: str | Path, commit_sha: str) -> Generator[Path, None, None]` (context manager)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collector_checkout.py`:

```python
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.collector_checkout import (
    CollectorCheckoutError,
    cleanup_collector_checkout,
    collector_checkout,
    create_collector_checkout,
)


def _init_test_repo(path: Path) -> str:
    """Create a minimal git repo with one commit, return the SHA."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    marker = path / "marker.txt"
    marker.write_text("initial")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class CreateCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_creates_checkout_at_sha(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue(checkout.is_dir())
            result = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                capture_output=True, text=True,
            )
            self.assertTrue(result.stdout.strip().startswith(self.sha[:7]))
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_checkout_has_repo_contents(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue((checkout / "marker.txt").exists())
            self.assertEqual((checkout / "marker.txt").read_text(), "initial")
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_empty_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "")

    def test_invalid_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "deadbeef" * 5)

    def test_not_a_git_repo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(CollectorCheckoutError):
                create_collector_checkout(td, "abc123")


class CleanupCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_removes_checkout_dir(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        self.assertTrue(checkout.is_dir())
        cleanup_collector_checkout(checkout, self.repo_dir)
        self.assertFalse(checkout.exists())

    def test_cleanup_nonexistent_no_error(self) -> None:
        cleanup_collector_checkout(Path("/nonexistent/path"), self.repo_dir)


class CollectorCheckoutContextManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_yields_checkout_path(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            self.assertTrue(checkout.is_dir())
            self.assertTrue((checkout / "marker.txt").exists())

    def test_cleans_up_on_exit(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            path = checkout
        self.assertFalse(path.exists())

    def test_cleans_up_on_exception(self) -> None:
        path = None
        with self.assertRaises(ValueError):
            with collector_checkout(self.repo_dir, self.sha) as checkout:
                path = checkout
                raise ValueError("boom")
        self.assertIsNotNone(path)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_checkout.py -v`
Expected: ModuleNotFoundError — `collector_checkout` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collector_checkout.py`:

```python
"""Fresh checkout management for evidence collectors (spec §7).

Creates temporary git worktrees at a specific commit SHA so collectors
run against pristine source, not the child's modified working copy.
This closes the TOCTOU gap: the child cannot modify code between
generation and evidence collection.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

__all__ = [
    "CollectorCheckoutError",
    "create_collector_checkout",
    "cleanup_collector_checkout",
    "collector_checkout",
]

_GIT_TIMEOUT = 30
_PRUNE_TIMEOUT = 15


class CollectorCheckoutError(RuntimeError):
    """Raised when a collector checkout cannot be created or validated."""


def create_collector_checkout(
    project_root: str | Path,
    commit_sha: str,
) -> Path:
    """Create a detached git worktree at commit_sha for collectors.

    Returns the path to the worktree directory.  Caller must call
    cleanup_collector_checkout() when done, or use the
    collector_checkout() context manager.
    """
    root = Path(project_root).resolve()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        raise CollectorCheckoutError(f"not a git repository: {root}")
    if not commit_sha or not commit_sha.strip():
        raise CollectorCheckoutError("commit_sha must not be empty")
    checkout_dir = Path(
        tempfile.mkdtemp(prefix="sa-collector-", suffix=f"-{commit_sha[:8]}")
    )
    try:
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(checkout_dir), commit_sha],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            shutil.rmtree(checkout_dir, ignore_errors=True)
            raise CollectorCheckoutError(
                f"git worktree add failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        verify = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(checkout_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        actual_sha = verify.stdout.strip()
        if not actual_sha.startswith(commit_sha[:7]):
            cleanup_collector_checkout(checkout_dir, root)
            raise CollectorCheckoutError(
                f"checkout SHA mismatch: expected {commit_sha}, got {actual_sha}"
            )
        return checkout_dir
    except subprocess.TimeoutExpired:
        shutil.rmtree(checkout_dir, ignore_errors=True)
        raise CollectorCheckoutError("git worktree add timed out")
    except CollectorCheckoutError:
        raise
    except OSError as exc:
        shutil.rmtree(checkout_dir, ignore_errors=True)
        raise CollectorCheckoutError(f"checkout failed: {exc}") from exc


def cleanup_collector_checkout(
    checkout_path: Path,
    project_root: str | Path | None = None,
) -> None:
    """Remove a collector worktree and its directory.

    Best-effort: never raises on cleanup failure.
    """
    if project_root is not None:
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout_path)],
                cwd=str(Path(project_root).resolve()),
                capture_output=True,
                timeout=_PRUNE_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
    shutil.rmtree(checkout_path, ignore_errors=True)


@contextmanager
def collector_checkout(
    project_root: str | Path,
    commit_sha: str,
) -> Generator[Path, None, None]:
    """Context manager: create a collector checkout, clean up on exit."""
    checkout = create_collector_checkout(project_root, commit_sha)
    try:
        yield checkout
    finally:
        cleanup_collector_checkout(checkout, project_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_checkout.py -v`
Expected: All 10 tests PASS (tests that use real git repos).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_checkout.py tests/test_collector_checkout.py
git commit -m "feat(gate): add collector checkout — fresh worktree at SHA

create_collector_checkout / cleanup_collector_checkout / collector_checkout
context manager create temporary git worktrees for evidence collectors,
closing the TOCTOU gap between generation and collection (spec §7).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Gate Audit Event Types

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Create: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: `audit.Event` protocol (`event_name: str`, `to_dict() -> Mapping[str, Any]`), `common.iso_now()`
- Produces: `GateStartedAudit(gate_id, commit_sha, profile_hash, tier)`, `EvidenceCollectedAudit(gate_id, category, collector, tool, status, duration_ms)`, `GateBoundaryViolation(operation, context)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gate_audit.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.audit import Event as AuditEventProtocol
from story_automator.core.gate_audit import (
    EvidenceCollectedAudit,
    GateBoundaryViolation,
    GateStartedAudit,
)


class GateStartedAuditTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = GateStartedAudit(
            gate_id="gate-001",
            commit_sha="abc123",
            profile_hash="def456",
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="sha1", profile_hash="h1")
        self.assertEqual(event.event_name, "GateStarted")

    def test_to_dict_contains_fields(self) -> None:
        event = GateStartedAudit(
            gate_id="gate-001",
            commit_sha="abc123",
            profile_hash="def456",
            tier="code",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "gate-001")
        self.assertEqual(d["commit_sha"], "abc123")
        self.assertEqual(d["profile_hash"], "def456")
        self.assertEqual(d["tier"], "code")

    def test_default_tier(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="s1", profile_hash="h1")
        self.assertEqual(event.tier, "code")

    def test_frozen(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="s1", profile_hash="h1")
        with self.assertRaises(AttributeError):
            event.gate_id = "mutated"  # type: ignore[misc]


class EvidenceCollectedAuditTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1",
            category="security",
            collector="semgrep-collector",
            tool="semgrep",
            status="ok",
            duration_ms=1234,
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1", category="c", collector="co", tool="t",
            status="ok", duration_ms=0,
        )
        self.assertEqual(event.event_name, "EvidenceCollected")

    def test_to_dict_contains_fields(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1",
            category="security",
            collector="semgrep-collector",
            tool="semgrep",
            status="violation",
            duration_ms=500,
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["category"], "security")
        self.assertEqual(d["collector"], "semgrep-collector")
        self.assertEqual(d["tool"], "semgrep")
        self.assertEqual(d["status"], "violation")
        self.assertEqual(d["duration_ms"], 500)


class GateBoundaryViolationTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = GateBoundaryViolation(
            operation="persist_evidence",
            context="child tried to write evidence",
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = GateBoundaryViolation(operation="op", context="ctx")
        self.assertEqual(event.event_name, "GateBoundaryViolation")

    def test_to_dict_contains_fields(self) -> None:
        event = GateBoundaryViolation(
            operation="run_collector",
            context="STORY_AUTOMATOR_CHILD=true",
        )
        d = event.to_dict()
        self.assertEqual(d["operation"], "run_collector")
        self.assertEqual(d["context"], "STORY_AUTOMATOR_CHILD=true")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: ModuleNotFoundError — `gate_audit` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`:

```python
"""Gate audit events for hash-chaining into the HMAC audit log.

Minimal dataclasses satisfying the audit.Event protocol (event_name +
to_dict).  These do NOT live in telemetry_events.py (owned by M01).
Dedicated GateDecision/GateRendered telemetry events land in M18.
"""
from __future__ import annotations

import dataclasses
from typing import Any

__all__ = [
    "GateStartedAudit",
    "EvidenceCollectedAudit",
    "GateBoundaryViolation",
]


@dataclasses.dataclass(frozen=True)
class GateStartedAudit:
    """Audit event: gate evaluation started for a commit."""
    event_name: str = dataclasses.field(default="GateStarted", init=False)
    gate_id: str = ""
    commit_sha: str = ""
    profile_hash: str = ""
    tier: str = "code"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "commit_sha": self.commit_sha,
            "profile_hash": self.profile_hash,
            "tier": self.tier,
        }


@dataclasses.dataclass(frozen=True)
class EvidenceCollectedAudit:
    """Audit event: a single evidence collector completed."""
    event_name: str = dataclasses.field(default="EvidenceCollected", init=False)
    gate_id: str = ""
    category: str = ""
    collector: str = ""
    tool: str = ""
    status: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "category": self.category,
            "collector": self.collector,
            "tool": self.tool,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }


@dataclasses.dataclass(frozen=True)
class GateBoundaryViolation:
    """Audit event: a trust boundary violation was detected."""
    event_name: str = dataclasses.field(default="GateBoundaryViolation", init=False)
    operation: str = ""
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "context": self.context,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add gate audit event types

GateStartedAudit / EvidenceCollectedAudit / GateBoundaryViolation
satisfy the audit.Event protocol for hash-chaining gate operations
into the existing HMAC audit log.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Gate Audit Emitter Integration

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: `audit.audit_for_policy(policy, path) -> AuditLog | None`, `audit.AuditLog.append(event)`, `GateStartedAudit`, `EvidenceCollectedAudit`, `GateBoundaryViolation`
- Produces: `emit_gate_audit(policy: Mapping[str, Any], audit_path: Path, event) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
import json
import os
import pathlib
import tempfile
from unittest.mock import patch

from story_automator.core.gate_audit import emit_gate_audit


class EmitGateAuditTests(unittest.TestCase):
    def _policy_with_audit(self) -> dict:
        return {"security": {"audit_trail": True}}

    def _policy_without_audit(self) -> dict:
        return {"security": {"audit_trail": False}}

    def test_emits_to_audit_log_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = GateStartedAudit(gate_id="g1", commit_sha="abc", profile_hash="h1")
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            self.assertTrue(audit_path.exists())
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateStarted")
            self.assertIn("gate_id", record["payload"])

    def test_noop_when_audit_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_without_audit()
            event = GateStartedAudit(gate_id="g1", commit_sha="abc", profile_hash="h1")
            emit_gate_audit(policy, audit_path, event)
            self.assertFalse(audit_path.exists())

    def test_emits_boundary_violation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = GateBoundaryViolation(operation="persist", context="child")
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateBoundaryViolation")

    def test_emits_evidence_collected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = EvidenceCollectedAudit(
                gate_id="g1", category="security", collector="c",
                tool="semgrep", status="ok", duration_ms=100,
            )
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "EvidenceCollected")
            self.assertEqual(record["payload"]["status"], "ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py::EmitGateAuditTests -v`
Expected: ImportError — `emit_gate_audit` not yet defined.

- [ ] **Step 3: Write minimal implementation**

Add to `gate_audit.py`, updating `__all__` and imports:

```python
import pathlib
from typing import Any, Mapping

from .audit import audit_for_policy

__all__ = [
    "GateStartedAudit",
    "EvidenceCollectedAudit",
    "GateBoundaryViolation",
    "emit_gate_audit",
]

# ... (existing dataclasses stay above) ...


def emit_gate_audit(
    policy: Mapping[str, Any],
    audit_path: pathlib.Path,
    event: GateStartedAudit | EvidenceCollectedAudit | GateBoundaryViolation,
) -> None:
    """Emit a gate audit event through the HMAC audit chain.

    No-op when audit is disabled in policy (zero I/O).  Follows
    the same pattern as commands._audit_hooks._maybe_audit_event.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_gate_audit.py -v`
Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add gate audit emitter

emit_gate_audit wires gate events through the existing HMAC audit chain
via audit_for_policy.  No-op when audit is disabled (zero I/O).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Adjudicator Trust Boundary Guard

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/adjudicator.py`
- Modify: `tests/test_adjudicator.py`

**Interfaces:**
- Consumes: `trust_boundary.assert_host_context(operation)`, existing `run_collector_with_timeout` signature (unchanged)
- Produces: `run_collector_with_timeout` now raises `TrustBoundaryError` if called from a child session

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adjudicator.py` (add `import os` and `from unittest.mock import patch` to the file's existing imports first):

```python
import os
from unittest.mock import patch

from story_automator.core.trust_boundary import TrustBoundaryError


class CollectorTrustBoundaryTests(unittest.TestCase):
    def test_raises_in_child_session(self) -> None:
        with patch.dict("os.environ", {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                run_collector_with_timeout(
                    [sys.executable, "-c", "print('ok')"],
                    collector="test",
                    tool="python",
                    category="correctness",
                    timeout_s=10,
                )

    def test_runs_normally_on_host(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("STORY_AUTOMATOR_CHILD", None)
            record = run_collector_with_timeout(
                [sys.executable, "-c", "print('ok')"],
                collector="test",
                tool="python",
                category="correctness",
                timeout_s=10,
            )
            self.assertEqual(record["status"], "ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_adjudicator.py::CollectorTrustBoundaryTests -v`
Expected: FAIL — `test_raises_in_child_session` does not raise (guard not yet added).

- [ ] **Step 3: Write minimal implementation**

Add the import and guard to `skills/bmad-story-automator/src/story_automator/core/adjudicator.py`:

Add after existing imports:

```python
from .trust_boundary import assert_host_context
```

Add as the first line inside `run_collector_with_timeout`, before the `if not cmd:` check:

```python
    assert_host_context("run_collector_with_timeout")
```

The function body now starts:

```python
def run_collector_with_timeout(
    cmd: list[str],
    *,
    collector: str,
    tool: str,
    category: str,
    timeout_s: int,
    cwd: str | None = None,
    tool_version: str = "",
) -> dict[str, Any]:
    """Run a collector subprocess with timeout + psutil SIGKILL on expiry.
    ...
    """
    assert_host_context("run_collector_with_timeout")
    if not cmd:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_adjudicator.py -v`
Expected: All tests PASS (existing tests run without `STORY_AUTOMATOR_CHILD` set, so they pass the guard).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/adjudicator.py tests/test_adjudicator.py
git commit -m "feat(gate): add trust boundary guard to adjudicator

run_collector_with_timeout now asserts host context before executing
any collector subprocess.  Child sessions raise TrustBoundaryError.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Evidence I/O Trust Guard

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`
- Modify: `tests/test_evidence_io.py`

**Interfaces:**
- Consumes: `trust_boundary.assert_host_context(operation)`, existing `persist_evidence_record` and `persist_gate_file` signatures (unchanged)
- Produces: `persist_evidence_record`, `persist_gate_file`, `write_gate_marker`, and `clear_gate_marker` now raise `TrustBoundaryError` if called from a child session

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evidence_io.py` (add `import os` and `from unittest.mock import patch` to the file's existing imports first):

```python
import os
from unittest.mock import patch

from story_automator.core.trust_boundary import TrustBoundaryError


class EvidenceIOTrustBoundaryTests(unittest.TestCase):
    def _v1_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_persist_evidence_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    persist_evidence_record(td, "gate-001", self._v1_record())

    def test_persist_gate_file_raises_in_child(self) -> None:
        gate = make_gate_file(
            gate_id="gate-001",
            target={"kind": "story", "id": "1.1"},
            commit_sha="abc123",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    persist_gate_file(td, gate)

    def test_write_gate_marker_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    write_gate_marker(td, "gate-001", "abc123")

    def test_clear_gate_marker_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.pop("STORY_AUTOMATOR_CHILD", None)
            with patch.dict(os.environ, env, clear=True):
                write_gate_marker(td, "gate-001", "abc123")
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    clear_gate_marker(td)

    def test_persist_evidence_works_on_host(self) -> None:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, env, clear=True):
            with tempfile.TemporaryDirectory() as td:
                path = persist_evidence_record(td, "gate-001", self._v1_record())
                self.assertTrue(path.exists())

    def test_read_functions_work_in_child(self) -> None:
        """Read-only functions must NOT be guarded — child may read evidence."""
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.pop("STORY_AUTOMATOR_CHILD", None)
            with patch.dict(os.environ, env, clear=True):
                persist_evidence_record(td, "gate-001", self._v1_record())
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py::EvidenceIOTrustBoundaryTests -v`
Expected: FAIL — `test_persist_evidence_raises_in_child` does not raise.

- [ ] **Step 3: Write minimal implementation**

Add the import to `skills/bmad-story-automator/src/story_automator/core/evidence_io.py`:

```python
from .trust_boundary import assert_host_context
```

Add guard as the first line in each of these three functions:

In `persist_evidence_record`:
```python
def persist_evidence_record(
    project_root: str | Path,
    gate_id: str,
    record: dict[str, Any],
) -> Path:
    """Write a validated evidence record to _bmad/gate/evidence/<gate_id>/."""
    assert_host_context("persist_evidence_record")
    _validate_gate_id(gate_id)
    ...
```

In `persist_gate_file`:
```python
def persist_gate_file(
    project_root: str | Path,
    gate_file: dict[str, Any],
) -> Path:
    """Write a validated gate file to _bmad/gate/verdicts/<gate_id>.json."""
    assert_host_context("persist_gate_file")
    validate_gate_file(gate_file)
    ...
```

In `write_gate_marker`:
```python
def write_gate_marker(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
) -> Path:
    """§9.2: atomic marker before collector loop starts."""
    assert_host_context("write_gate_marker")
    marker = {
    ...
```

In `clear_gate_marker`:
```python
def clear_gate_marker(project_root: str | Path) -> None:
    """§9.2: remove marker after verdict is written (or on crash recovery)."""
    assert_host_context("clear_gate_marker")
    path = _gate_marker_path(project_root)
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_evidence_io.py -v`
Expected: All tests PASS (existing tests run without `STORY_AUTOMATOR_CHILD` set).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/evidence_io.py tests/test_evidence_io.py
git commit -m "feat(gate): add trust boundary guard to evidence I/O

persist_evidence_record, persist_gate_file, and write_gate_marker now
assert host context before any write.  Read functions remain unguarded
so the child (and tests) can inspect evidence.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: tmux_runtime Sandbox Consolidation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`
- Modify: `tests/test_trust_boundary.py` (add cross-check test)

**Interfaces:**
- Consumes: `trust_boundary.sandbox_tmux_env_args(agent)`, `trust_boundary.CHILD_STRIPPED_VARS`, `trust_boundary.CHILD_FORCED_VARS`
- Produces: `_spawn_runner` and `_spawn_legacy` use `sandbox_tmux_env_args()` instead of inline `-e` flags; behavioral equivalence preserved

- [ ] **Step 1: Write the failing cross-check test**

Append to `tests/test_trust_boundary.py`:

```python
class TmuxRuntimeCrossCheckTests(unittest.TestCase):
    """Verify sandbox_tmux_env_args produces flags covering all vars
    that tmux_runtime historically stripped inline."""

    HISTORICALLY_STRIPPED = {"BMAD_AUDIT_KEY", "CLAUDECODE", "BASH_ENV"}
    HISTORICALLY_FORCED = {"STORY_AUTOMATOR_CHILD": "true"}

    def test_stripped_vars_cover_historical(self) -> None:
        self.assertTrue(
            self.HISTORICALLY_STRIPPED.issubset(CHILD_STRIPPED_VARS),
            f"missing from CHILD_STRIPPED_VARS: "
            f"{self.HISTORICALLY_STRIPPED - CHILD_STRIPPED_VARS}",
        )

    def test_forced_vars_cover_historical(self) -> None:
        for var, val in self.HISTORICALLY_FORCED.items():
            self.assertEqual(
                CHILD_FORCED_VARS.get(var), val,
                f"CHILD_FORCED_VARS[{var!r}] should be {val!r}",
            )

    def test_tmux_args_contain_all_historical_vars(self) -> None:
        args = sandbox_tmux_env_args(agent="claude")
        flat = " ".join(args)
        for var in self.HISTORICALLY_STRIPPED:
            self.assertIn(f"{var}=", flat)
        self.assertIn("STORY_AUTOMATOR_CHILD=true", flat)
        self.assertIn("AI_AGENT=claude", flat)
```

- [ ] **Step 2: Run cross-check test to verify it passes (tests the contract, not the integration)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py::TmuxRuntimeCrossCheckTests -v`
Expected: PASS — the constants already cover the historical vars.

- [ ] **Step 3: Refactor tmux_runtime.py**

In `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`, add import:

```python
from .trust_boundary import sandbox_tmux_env_args
```

In `_spawn_runner`, replace the inline `-e` flags in the `run_cmd("tmux", "new-session", ...)` call. Change:

```python
        "-e",
        "STORY_AUTOMATOR_CHILD=true",
        "-e",
        f"AI_AGENT={selected_agent}",
        "-e",
        "CLAUDECODE=",
        "-e",
        "BASH_ENV=",
        "-e",
        "BMAD_AUDIT_KEY=",
```

To:

```python
        *sandbox_tmux_env_args(agent=selected_agent),
```

In `_spawn_legacy`, replace the same inline `-e` flags:

```python
        "-e",
        "STORY_AUTOMATOR_CHILD=true",
        "-e",
        f"AI_AGENT={selected_agent}",
        "-e",
        "CLAUDECODE=",
        "-e",
        "BMAD_AUDIT_KEY=",
```

To:

```python
        *sandbox_tmux_env_args(agent=selected_agent),
```

- [ ] **Step 4: Run existing tmux tests to verify no regression**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_tmux_runtime.py -v`
Expected: All existing tests PASS unchanged.

Run full trust boundary suite:

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py tests/test_trust_boundary.py
git commit -m "refactor(gate): consolidate tmux child env setup via sandbox_tmux_env_args

_spawn_runner and _spawn_legacy now use sandbox_tmux_env_args() from
trust_boundary instead of inline -e flags.  Cross-check test verifies
the new constants cover all historically stripped vars.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Blind Hunter Enforcement Integration Test

**Files:**
- Create: `tests/test_trust_integration.py`

**Interfaces:**
- Consumes: `trust_boundary.is_child_session`, `trust_boundary.assert_host_context`, `trust_boundary.sandbox_env`, `trust_boundary.verify_sandbox_env`, `trust_boundary.validate_evidence_path_isolation`, `trust_boundary.resolve_host_evidence_dir`, `evidence_io.persist_evidence_record`, `evidence_io.load_evidence_bundle`, `gate_schema.make_evidence_record`, `gate_audit.emit_gate_audit`, `gate_audit.GateStartedAudit`, `gate_audit.GateBoundaryViolation`
- Produces: Integration test suite validating the Blind Hunter property end-to-end

- [ ] **Step 1: Write the integration tests**

Create `tests/test_trust_integration.py`:

```python
"""End-to-end trust boundary integration tests.

Validates the Blind Hunter property: the generation child cannot write
evidence, forge audit entries, or bypass the trust boundary.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.evidence_io import (
    load_evidence_bundle,
    persist_evidence_record,
    persist_gate_file,
    write_gate_marker,
)
from story_automator.core.gate_audit import (
    EvidenceCollectedAudit,
    GateBoundaryViolation,
    GateStartedAudit,
    emit_gate_audit,
)
from story_automator.core.gate_schema import (
    make_evidence_record,
    make_gate_file,
)
from story_automator.core.trust_boundary import (
    TrustBoundaryError,
    assert_host_context,
    is_child_session,
    resolve_host_evidence_dir,
    sandbox_env,
    validate_evidence_path_isolation,
    verify_sandbox_env,
)


class BlindHunterEnforcementTests(unittest.TestCase):
    """Verify the child generation session cannot write evidence."""

    def _child_env(self) -> dict[str, str]:
        return {"STORY_AUTOMATOR_CHILD": "true"}

    def _host_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        return env

    def _sample_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_child_cannot_persist_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    persist_evidence_record(td, "gate-001", self._sample_record())

    def test_child_cannot_persist_gate_file(self) -> None:
        gate = make_gate_file(
            gate_id="gate-001",
            target={"kind": "story", "id": "1.1"},
            commit_sha="abc123",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    persist_gate_file(td, gate)

    def test_child_cannot_write_gate_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._child_env()):
                with self.assertRaises(TrustBoundaryError):
                    write_gate_marker(td, "gate-001", "abc123")

    def test_child_can_read_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._host_env(), clear=True):
                persist_evidence_record(td, "gate-001", self._sample_record())
            with patch.dict(os.environ, self._child_env()):
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)

    def test_host_can_persist_and_read_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, self._host_env(), clear=True):
                persist_evidence_record(td, "gate-001", self._sample_record())
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["status"], "ok")


class SandboxEnvSecurityTests(unittest.TestCase):
    """Verify the sandbox env is properly sanitized."""

    def test_sandbox_env_passes_verification(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret", "PATH": "/usr"}, clear=True):
            env = sandbox_env(agent="claude")
            ok, violations = verify_sandbox_env(env)
            self.assertTrue(ok, f"violations: {violations}")

    def test_sandbox_env_child_is_detected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = sandbox_env()
            self.assertTrue(is_child_session(env))

    def test_sandbox_env_strips_audit_key(self) -> None:
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=True):
            env = sandbox_env()
            self.assertNotIn("BMAD_AUDIT_KEY", env)

    def test_host_is_not_child(self) -> None:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        self.assertFalse(is_child_session(env))


class EvidencePathIsolationTests(unittest.TestCase):
    """Verify evidence paths are outside child working tree."""

    def test_host_evidence_dir_not_under_child_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as project_root:
            evidence_dir = resolve_host_evidence_dir(project_root)
            child_tree = pathlib.Path(tempfile.mkdtemp())
            try:
                ok, _ = validate_evidence_path_isolation(evidence_dir, child_tree)
                self.assertTrue(ok)
            finally:
                child_tree.rmdir()

    def test_evidence_under_child_fails(self) -> None:
        with tempfile.TemporaryDirectory() as child_tree:
            evidence_dir = pathlib.Path(child_tree) / "_bmad" / "gate"
            ok, reason = validate_evidence_path_isolation(
                evidence_dir, pathlib.Path(child_tree)
            )
            self.assertFalse(ok)
            self.assertIn("under child working tree", reason)


class GateAuditChainTests(unittest.TestCase):
    """Verify gate events integrate with the HMAC audit chain."""

    def test_gate_started_chains_into_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = {"security": {"audit_trail": True}}
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-key"}):
                emit_gate_audit(
                    policy, audit_path,
                    GateStartedAudit(gate_id="g1", commit_sha="sha1", profile_hash="h1"),
                )
                emit_gate_audit(
                    policy, audit_path,
                    EvidenceCollectedAudit(
                        gate_id="g1", category="security", collector="c",
                        tool="semgrep", status="ok", duration_ms=100,
                    ),
                )
            lines = audit_path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 2)
            r1 = json.loads(lines[0])
            r2 = json.loads(lines[1])
            self.assertEqual(r1["seq"], 1)
            self.assertEqual(r2["seq"], 2)
            self.assertNotEqual(r1["tag"], r2["tag"])

    def test_boundary_violation_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = {"security": {"audit_trail": True}}
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-key"}):
                emit_gate_audit(
                    policy, audit_path,
                    GateBoundaryViolation(operation="persist", context="child"),
                )
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateBoundaryViolation")
            self.assertIn("tag", record)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run integration tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_trust_integration.py
git commit -m "test(gate): add Blind Hunter enforcement integration tests

End-to-end tests verifying the trust boundary: child cannot write
evidence/gate files/markers; host can; sandbox env is properly
sanitized; evidence paths are isolated; gate events chain into audit.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Trust Pipeline Round-Trip Test

**Files:**
- Modify: `tests/test_trust_integration.py`

**Interfaces:**
- Consumes: All trust boundary, evidence I/O, gate schema, gate rules, gate audit, and collector checkout modules
- Produces: Round-trip test proving the full trust pipeline is deterministic and fail-closed

- [ ] **Step 1: Write the round-trip tests**

Append to `tests/test_trust_integration.py`:

```python
import subprocess

from story_automator.core.adjudicator import run_collector_with_timeout
from story_automator.core.collector_checkout import (
    CollectorCheckoutError,
    collector_checkout,
    create_collector_checkout,
    cleanup_collector_checkout,
)
from story_automator.core.evidence_io import (
    can_reuse_gate_file,
    compute_evidence_bundle_hash,
    load_gate_file,
)
from story_automator.core.gate_rules import (
    aggregate_verdicts,
    verdict_for_collector_status,
)
import sys


def _init_test_repo(path: pathlib.Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "src.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class TrustPipelineRoundTripTests(unittest.TestCase):
    """Full flow: host asserts context → fresh checkout → collect →
    evidence persist → bundle hash → gate file → audit event."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-pipeline-")
        self.project_root = pathlib.Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_test_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_pipeline_pass(self) -> None:
        host_env = dict(os.environ)
        host_env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, host_env, clear=True):
            with collector_checkout(self.project_root, self.sha) as checkout:
                record = run_collector_with_timeout(
                    [sys.executable, "-c", "print('ok')"],
                    collector="test",
                    tool="python",
                    category="correctness",
                    timeout_s=10,
                    cwd=str(checkout),
                )
                self.assertEqual(record["status"], "ok")
            path = persist_evidence_record(
                self.project_root, "gate-001", record,
            )
            self.assertTrue(path.exists())
            records = load_evidence_bundle(self.project_root, "gate-001")
            self.assertEqual(len(records), 1)
            bundle_hash = compute_evidence_bundle_hash(records)
            self.assertEqual(len(bundle_hash), 16)
            verdicts = {
                "correctness": verdict_for_collector_status(record["status"])
            }
            overall = aggregate_verdicts(verdicts)
            self.assertEqual(overall, "PASS")
            gate = make_gate_file(
                gate_id="gate-001",
                target={"kind": "story", "id": "1.1"},
                commit_sha=self.sha,
                profile={"id": "default", "version": 1, "hash": "prof-hash"},
                factory_version="0.1.0",
                categories={"correctness": {"verdict": "PASS"}},
                overall=overall,
                evidence_bundle_hash=bundle_hash,
            )
            persist_gate_file(self.project_root, gate)
            loaded = load_gate_file(self.project_root, "gate-001")
            self.assertEqual(loaded["overall"], "PASS")
            self.assertEqual(loaded["evidence_bundle_hash"], bundle_hash)

    def test_full_pipeline_fail_closed(self) -> None:
        host_env = dict(os.environ)
        host_env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, host_env, clear=True):
            record = run_collector_with_timeout(
                [sys.executable, "-c", "import sys; sys.exit(1)"],
                collector="test",
                tool="failing-tool",
                category="security",
                timeout_s=10,
            )
            self.assertEqual(record["status"], "violation")
            verdict = verdict_for_collector_status(record["status"])
            self.assertEqual(verdict, "FAIL")
            overall = aggregate_verdicts({"security": verdict})
            self.assertEqual(overall, "FAIL")

    def test_evidence_bundle_hash_deterministic(self) -> None:
        r1 = make_evidence_record(
            collector="a", tool="t1", category="c1", status="ok",
        )
        r2 = make_evidence_record(
            collector="b", tool="t2", category="c2", status="ok",
        )
        hash_a = compute_evidence_bundle_hash([r1, r2])
        hash_b = compute_evidence_bundle_hash([r2, r1])
        self.assertEqual(hash_a, hash_b)

    def test_gate_file_reuse_requires_matching_sha(self) -> None:
        gate = make_gate_file(
            gate_id="gate-002",
            target={"kind": "story", "id": "1.1"},
            commit_sha="sha-old",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        ok, reason = can_reuse_gate_file(
            gate, commit_sha="sha-new", profile_hash="h1", factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("commit_sha mismatch", reason)

    def test_collector_checkout_at_sha(self) -> None:
        (self.project_root / "src.py").write_text("x = 2\n")
        subprocess.run(
            ["git", "-C", str(self.project_root), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.project_root), "commit", "-m", "v2"],
            capture_output=True, check=True,
        )
        with collector_checkout(self.project_root, self.sha) as checkout:
            content = (checkout / "src.py").read_text()
            self.assertEqual(content, "x = 1\n")
```

- [ ] **Step 2: Run full integration test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Run the complete test suite for all milestone files**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_trust_boundary.py tests/test_collector_checkout.py tests/test_gate_audit.py tests/test_trust_integration.py tests/test_adjudicator.py tests/test_evidence_io.py -v`
Expected: All tests PASS — no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_integration.py
git commit -m "test(gate): add trust pipeline round-trip integration tests

Full-flow tests: host checkout → collect → evidence persist → bundle hash
→ gate file → reuse check.  Verifies determinism, fail-closed behavior,
and SHA-pinned checkout isolation.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```
