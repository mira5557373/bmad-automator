# D3 — Subprocess-call inventory

Repo: `/home/ubuntu/projects/personal/bmad-automator` @ `bma-d/integration-all`
Source roots: `skills/`, `bin/`, `scripts/` (excluded: `external/`, `.venv/`, `tests/`).

## Direct `subprocess.run` call sites (3)

| # | file:line | shell= | executable_path | env= | check= | args_source | secret_material_in_argv |
|---|-----------|--------|-----------------|------|--------|-------------|-------------------------|
| 1 | `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py:282` | absent (False) | PATH lookup of `claude` (param `claude_binary`, default `"claude"`) | `{**os.environ, "LANG": "C.UTF-8"}` (full inherit) | False (explicit returncode handling) | literal (`[claude_binary, "-p"]`); prompt via stdin | no (prompt via `input=prompt`, never argv) |
| 2 | `skills/bmad-story-automator/src/story_automator/core/utils.py:105` (`run_cmd` helper, `commands.CommandResult` variant) | absent (False) | caller-supplied (always literal program name: `claude`, `tmux`, `git`, `pgrep`, `ps`, `bash`) | `os.environ.copy()` + caller overlay | False (caller branches on `exit_code`) | literal (caller-controlled) | depends on caller — see callsite table below |
| 3 | `skills/bmad-story-automator/src/story_automator/core/common.py:112` (`run_cmd` helper, tuple variant) | absent (False) | caller-supplied (always literal program name) | `os.environ.copy()` + caller overlay | False (caller branches on `exit_code`) | literal (caller-controlled) | depends on caller — see callsite table below |

No `subprocess.Popen`, `subprocess.call`, `subprocess.check_output`, `subprocess.check_call`, `os.system`, `os.popen`, or `os.spawn*` exist in production sources. The two `run_cmd` helpers are functionally equivalent twins (separate Result type wrappers); both copy the full parent environment to every child.

## `run_cmd` consumers (effective subprocess sites)

| # | callsite | program | args_source | secret in argv |
|---|----------|---------|-------------|----------------|
| a | `commands/orchestrator_parse.py:44` | `parser_cfg["provider"]` (whitelisted by `VALID_PARSER_PROVIDERS` in runtime_policy.py:209) | preset (TRUSTED) + LLM-supplied `prompt` text positional arg | LLM-supplied prompt is in argv |
| b | `commands/basic.py:202,210,214,218` | `git` | literal | no |
| c | `commands/basic.py:237`; `core/tmux_runtime.py:168,173,178,188,289,321,343,609,646,683,717,744,746,1435,1456` | `tmux` | literal + session name (TRUSTED operator-supplied via `--session`) | no — but **see F-D3-001** |
| d | `core/tmux_runtime.py:1164,1582,1596` | `pgrep` / `ps` | literal | no |
| e | `core/tmux_runtime.py:744,746` | `tmux send-keys` payload = `command` string | command derived from `agent-config-presets.json` (TRUSTED) | no (command in argv is the bash literal, not a secret) |

## Node `spawnSync` (bin entrypoint)

| # | file:line | shell= | executable | source |
|---|-----------|--------|------------|--------|
| n1 | `bin/bmad-story-automator:25` | n/a (Node, no shell) | `where bash` (PATH lookup, Windows only) | literal |
| n2 | `bin/bmad-story-automator` (`spawnSync(bash, [installScript, …rest])`) | n/a (Node spawnSync arg-array form, no shell) | resolved bash | literal + forwarded argv |

Node `spawnSync` in arg-array form does not invoke a shell (no `shell: true`); arguments are passed verbatim to the executable. No injection vector.
