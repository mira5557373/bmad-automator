"""cli_dispatcher_invokers — concrete runtime invokers for ``cli_dispatcher``.

This module ships the *default* :func:`claude_code_invoker` that the
N6.5 dispatcher uses when the caller does not pass an explicit
``runtime_invoker``. It is a thin shim over the existing
:mod:`story_automator.core.tmux_runtime` public surface — no new public
API on tmux_runtime, no new third-party deps.

Why a sibling module?
---------------------

``core/cli_dispatcher.py`` is currently 481 LOC (500-LOC soft limit per
project convention). Adding the real invoker wiring inline would push
it over. Splitting also keeps the dispatcher's classification logic
unit-testable without dragging in tmux at import time.

Public surface (all consumed only by ``cli_dispatcher.py``):

* :func:`claude_code_invoker` — real invoker for ``cli_id="claude-code"``.
* :func:`default_invoker` — switch on ``profile.cli_id``; routes to
  ``claude_code_invoker`` for claude-code; raises ``NotImplementedError``
  for ``codex``, ``gemini-cli``, ``none``, and unknown ids.

Testability
-----------

The shim parameterises its tmux/git calls through module-level callables
so tests can monkey-patch them without touching tmux or a real workspace:

* :data:`_spawn_session_hook` — defaults to ``tmux_runtime.spawn_session``.
* :data:`_session_status_hook` — defaults to ``tmux_runtime.session_status``.
* :data:`_verify_output_hook` — defaults to ``tmux_runtime.verify_or_create_output``.
* :data:`_read_output_hook` — reads bytes from a path (defaults to
  ``Path.read_text`` with errors="replace").
* :data:`_kill_session_hook` — defaults to ``tmux_runtime.tmux_kill_session``.
* :data:`_git_head_hook` — defaults to ``subprocess.run(["git", "rev-parse", "HEAD"])``.
* :data:`_clock_hook` — defaults to ``time.monotonic`` (for timeout polling).
* :data:`_sleep_hook` — defaults to ``time.sleep`` (for poll backoff).

Hard guardrails honored
-----------------------

* stdlib + filelock + psutil only (this module imports no new deps).
* No mutation of :mod:`tmux_runtime` public surface.
* Calls :func:`tmux_runtime.inject_bmad_auto_env` for BMAD_AUTO_* env
  propagation — already shipped in M42, not re-implemented here.
* Wire-shape is the runner-contract dict expected by
  :func:`cli_dispatcher.dispatch_session`: keys ``stdout_tail``,
  ``head_sha``, ``session_id``, ``stderr_tail``, ``timed_out``.
"""
from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import tmux_runtime
from .cli_profile import CLIProfile

if False:  # TYPE_CHECKING — avoid a runtime import cycle.
    from .cli_dispatcher import SessionIntent


# ---------------------------------------------------------------------------
# Module-level hooks (overridable by tests).
# ---------------------------------------------------------------------------

#: tmux ``spawn_session(session, command, selected_agent, project_root)``.
_spawn_session_hook: Callable[..., tuple[str, int]] = tmux_runtime.spawn_session

#: tmux ``session_status(session, full=False, codex=False, project_root=...)``.
_session_status_hook: Callable[..., dict[str, str | int]] = tmux_runtime.session_status

#: tmux ``verify_or_create_output(output_file, session_name, hash_value, ...)``.
_verify_output_hook: Callable[..., str] = tmux_runtime.verify_or_create_output

#: Plain file read used to grab stdout_tail (decoupled so tests can stub).
def _default_read_output(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_read_output_hook: Callable[[str], str] = _default_read_output

#: tmux ``tmux_kill_session(session, project_root=...)`` — used on timeout.
_kill_session_hook: Callable[..., None] = tmux_runtime.tmux_kill_session

#: git rev-parse HEAD in ``cwd``. Returns the SHA (stripped) or "".
def _default_git_head(cwd: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


_git_head_hook: Callable[[str], str] = _default_git_head

#: monotonic clock — for timeout enforcement.
_clock_hook: Callable[[], float] = time.monotonic

#: sleep between polls.
_sleep_hook: Callable[[float], None] = time.sleep


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: How often to poll session_status while the session is running.
_POLL_INTERVAL_S: float = 1.0

#: Tail length cap (chars) so stdout_tail never balloons through the
#: dispatcher's wire surface. The dispatcher does not bound the tail; the
#: runner must — and that's us.
_STDOUT_TAIL_CAP_CHARS: int = 8000


# ---------------------------------------------------------------------------
# claude_code_invoker
# ---------------------------------------------------------------------------


def _session_name_for(intent: "SessionIntent") -> str:
    """Stable session name derived from the intent.

    The name is *not* an interface — callers cannot reach it back — but it
    must satisfy :func:`tmux_runtime._validated_session_name` which enforces
    the ``sa-...`` prefix and limited charset. We piggy-back on
    :func:`tmux_runtime.generate_session_name` style, but keep it
    deterministic so tests can assert on it. We don't depend on epic/story
    semantics; we just sanitize story_key.
    """
    # Sanitize story_key to the allowed charset (alnum + dash + underscore).
    raw = (intent.story_key or "STORY").strip() or "STORY"
    sane = "".join(c if c.isalnum() else "-" for c in raw).strip("-") or "STORY"
    phase = (intent.phase or "phase").replace("_", "-").replace("/", "-")
    return f"sa-disp-{sane}-{phase}"[:80]


def _tail(text: str, *, cap: int = _STDOUT_TAIL_CAP_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= cap:
        return text
    return text[-cap:]


def claude_code_invoker(
    *,
    profile: CLIProfile,
    intent: "SessionIntent",
) -> dict[str, Any]:
    """Drive a real Claude-Code tmux session and return the runner-contract dict.

    Wire shape matches what :func:`cli_dispatcher.dispatch_session`
    expects: ``stdout_tail``, ``head_sha``, ``session_id``, ``stderr_tail``,
    ``timed_out``.

    Lifecycle:

      1. Inject BMAD_AUTO_* into the parent env (so tmux's child shell
         inherits them) via :func:`tmux_runtime.inject_bmad_auto_env`.
      2. Spawn the session via :func:`tmux_runtime.spawn_session`. If
         spawn fails (non-zero exit), surface as a synthetic stderr.
      3. Poll :func:`tmux_runtime.session_status` until terminal or
         until ``intent.timeout_s`` elapses.
      4. On timeout: kill the tmux session, return ``timed_out=True``.
      5. On terminal: pull the output text via
         :func:`tmux_runtime.verify_or_create_output`, read it as
         ``stdout_tail``, and resolve ``head_sha`` via
         :func:`_default_git_head` on ``intent.workspace``.
    """
    if profile.cli_id != "claude-code":
        # Defensive: caller should have switched on cli_id already.
        raise NotImplementedError(
            f"claude_code_invoker called with cli_id={profile.cli_id!r}"
        )

    # 1. BMAD_AUTO_* env injection — parent process env so the subprocess
    # spawned by ``_spawn_session_hook`` (which copies ``os.environ``) sees
    # the keys when issuing ``tmux new-session -e KEY=VAL ...``.
    #
    # Bug E2_C9_D-SEC-04: prior implementation permanently mutated
    # ``os.environ`` and never restored it, leaking BMAD_AUTO_* across
    # sequential invocations and contaminating any cleanup/attribution
    # code that reads the parent env. The fix snapshots prior values,
    # applies the mutation only across the spawn call, and restores the
    # parent env in a ``finally`` block (including removing keys that
    # did not previously exist).
    enriched = tmux_runtime.inject_bmad_auto_env(
        dict(os.environ),
        story_key=intent.story_key,
        phase=intent.phase,
        cli_id=profile.cli_id,
        commit_sha=intent.baseline_sha,
    )
    _bmad_keys = {k: v for k, v in enriched.items() if k.startswith("BMAD_AUTO_")}
    # Sentinel separates "absent" from "present but empty string".
    _ENV_ABSENT = object()
    _prior_env: dict[str, object] = {
        k: os.environ.get(k, _ENV_ABSENT) for k in _bmad_keys
    }

    session = _session_name_for(intent)
    workspace = intent.workspace

    # 2. Spawn the session. We build a launch command from profile + prompt.
    # The spawn API is (session, command, selected_agent, project_root).
    binary = profile.binary or "claude"
    bypass = " ".join(profile.bypass_flags) if profile.bypass_flags else ""
    rendered_prompt = (profile.prompt_template or "{prompt}").format(
        prompt=intent.prompt
    )
    # We pass the prompt via the binary's CLI; the binary is responsible for
    # interpreting it. (Real claude-code uses stdin for /skill, but for
    # spawning we just embed the prompt in the command — tests don't actually
    # run a binary; production uses a wrapper script.)
    command = (
        f"{binary} {bypass} {rendered_prompt}".strip()
        if bypass
        else f"{binary} {rendered_prompt}".strip()
    )
    try:
        # Apply BMAD_AUTO_* keys only across the spawn call. The spawn
        # subprocess (run_cmd → subprocess.run(env=os.environ.copy()))
        # snapshots its env at exec time, so tmux's child shell inherits
        # the keys without the parent's env staying mutated afterwards.
        for k, v in _bmad_keys.items():
            os.environ[k] = str(v)
        spawn_out, spawn_code = _spawn_session_hook(
            session, command, "claude", workspace
        )
    finally:
        # Restore parent env regardless of spawn outcome (success, failure,
        # or exception). Keys that were absent before are removed.
        for k, prior in _prior_env.items():
            if prior is _ENV_ABSENT:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prior  # type: ignore[assignment]
    if spawn_code != 0:
        return {
            "stdout_tail": "",
            "head_sha": _git_head_hook(workspace),
            "session_id": "",
            "stderr_tail": f"spawn_session failed (code={spawn_code}): {spawn_out}",
            "timed_out": False,
        }

    # 3. Poll session_status until terminal or timeout.
    timeout_s = max(0.1, float(intent.timeout_s))
    start = _clock_hook()
    last_status: dict[str, str | int] = {}
    while True:
        last_status = _session_status_hook(
            session, full=False, codex=False, project_root=workspace
        )
        sstate = str(last_status.get("session_state", ""))
        status = str(last_status.get("status", ""))
        # Terminal markers: completed/dead/missing/error.
        if status in {"completed", "dead", "missing", "not_found", "error"}:
            break
        if sstate in {"completed", "success", "failure", "crashed"}:
            break
        if _clock_hook() - start >= timeout_s:
            # 4. Timeout — kill and return timed_out.
            try:
                _kill_session_hook(session, workspace)
            except Exception:
                pass
            return {
                "stdout_tail": "",
                "head_sha": _git_head_hook(workspace),
                "session_id": session,
                "stderr_tail": f"claude-code session {session} exceeded timeout_s={timeout_s}",
                "timed_out": True,
            }
        _sleep_hook(_POLL_INTERVAL_S)

    # 5. Pull stdout via verify_or_create_output, read it, tail-cap.
    output_path = _verify_output_hook("", session, "", project_root=workspace)
    stdout_tail = _tail(_read_output_hook(output_path)) if output_path else ""
    head_sha = _git_head_hook(workspace)
    return {
        "stdout_tail": stdout_tail,
        "head_sha": head_sha,
        "session_id": session,
        "stderr_tail": "",
        "timed_out": False,
    }


# ---------------------------------------------------------------------------
# default_invoker — top-level switch
# ---------------------------------------------------------------------------


def default_invoker(
    *,
    profile: CLIProfile,
    intent: "SessionIntent",
) -> dict[str, Any]:
    """Switch on ``profile.cli_id`` to the right concrete invoker.

    Raises ``NotImplementedError`` for any CLI we haven't wired yet — the
    message includes the cli_id so the orchestrator can route the failure
    cleanly.

    For ``cli_id="claude-code"`` we delegate to :func:`claude_code_invoker`.
    """
    cli_id = profile.cli_id
    if cli_id == "claude-code":
        return claude_code_invoker(profile=profile, intent=intent)
    if cli_id == "codex":
        raise NotImplementedError(
            "codex CLI invoker not yet wired; pass an explicit runtime_invoker"
        )
    if cli_id == "gemini-cli":
        raise NotImplementedError(
            "gemini-cli CLI invoker not yet wired; pass an explicit runtime_invoker"
        )
    if cli_id == "none":
        raise NotImplementedError(
            "none dialect requires an explicit runtime_invoker (no built-in runner)"
        )
    raise NotImplementedError(
        f"no built-in invoker for cli_id={cli_id!r}; pass an explicit runtime_invoker"
    )


__all__ = [
    "claude_code_invoker",
    "default_invoker",
]
