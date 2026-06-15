from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from ..core.artifact_paths import implementation_artifacts_dir, implementation_artifacts_relpath
from ..core.junit import parse_junit
from ..core.run_liveness import run_is_stale
from ..core.runtime_layout import active_marker_path, runtime_provider
from ..core.runtime_policy import PolicyError, load_policy_unresolved, test_config
from ..core.stop_hooks import HookConfigError, ensure_stop_hook
from ..core.story_keys import normalize_story_key
from ..core.utils import (
    ensure_dir,
    get_project_slug,
    run_cmd,
    write_json,
)

# `git status --porcelain` already respects .gitignore, so build/dependency/cache
# junk (node_modules/, .venv/, dist/, __pycache__/, ...) never reaches us — we do
# NOT maintain a denylist of those (it could only ever be incomplete). What git
# *does* surface and we must still drop is the tracked-but-not-source set: the
# BMAD orchestration artifacts (the story file itself lives under _bmad-output/)
# and agent/IDE config dirs. That set is bounded, and these prefixes mirror the
# exclusions the review skill applies (bmad-story-automator-review/instructions.xml).
FILE_LIST_EXCLUDE_PREFIXES = (
    "_bmad/",
    "_bmad-output/",
    ".claude/",
    ".cursor/",
    ".windsurf/",
)


def _workflow_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _workflow_doc_relative(doc_name: str) -> str:
    doc_path = _workflow_root() / "data" / doc_name
    project_root = Path(os.environ.get("PROJECT_ROOT") or os.getcwd()).resolve()
    try:
        # Forward-slashed relative path for the cross-platform doc reference
        # (str() would emit backslashes on Windows).
        return doc_path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return str(doc_path.resolve())


def _stop_hook_command(command: str, project_root: Path) -> str:
    command_parts = shlex.split(command)
    if not command_parts:
        return command
    candidates = [
        _workflow_root() / "scripts" / "story-automator",
        Path(shutil.which("story-automator")) if shutil.which("story-automator") else None,
        Path(sys.argv[0]).resolve() if Path(sys.argv[0]).exists() and os.access(Path(sys.argv[0]), os.X_OK) else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            command_parts[0] = str(candidate.resolve())
            return shlex.join(["env", f"PROJECT_ROOT={project_root}", *command_parts])
    return shlex.join(["env", f"PROJECT_ROOT={project_root}", shutil.which("python3") or "python3", "-m", "story_automator", *command_parts[1:]])


def cmd_derive_project_slug(args: list[str]) -> int:
    if args and args[0] in {"--help", "-h"}:
        print("Usage: derive-project-slug [--project-root PATH]")
        return 0
    project_root = os.getcwd()
    for idx, arg in enumerate(args):
        if arg == "--project-root" and idx + 1 < len(args):
            project_root = args[idx + 1]
    write_json({"ok": True, "slug": get_project_slug(project_root), "projectRoot": project_root})
    return 0


def cmd_ensure_marker_gitignore(args: list[str]) -> int:
    gitignore = ""
    entry = ""
    for idx, arg in enumerate(args):
        if arg == "--gitignore" and idx + 1 < len(args):
            gitignore = args[idx + 1]
        if arg == "--entry" and idx + 1 < len(args):
            entry = args[idx + 1]
    if not gitignore or not entry:
        write_json({"ok": False, "error": "missing_args"})
        return 1
    path = Path(gitignore)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    content = path.read_text(encoding="utf-8")
    for line in content.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped == entry:
            write_json({"ok": True, "changed": False, "path": str(path)})
            return 0
    prefix = "" if not content or content.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}{entry}\n")
    write_json({"ok": True, "changed": True, "path": str(path)})
    return 0


def cmd_ensure_stop_hook(args: list[str]) -> int:
    settings = ""
    command = ""
    timeout = 10
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--settings" and idx + 1 < len(args):
            settings = args[idx + 1]
            idx += 2
        elif arg == "--command" and idx + 1 < len(args):
            idx += 1
            command_parts: list[str] = []
            while idx < len(args) and not args[idx].startswith("--"):
                command_parts.append(args[idx])
                idx += 1
            if command_parts:
                command = command_parts[0] if len(command_parts) == 1 else shlex.join(command_parts)
        elif arg == "--timeout" and idx + 1 < len(args):
            timeout = int(args[idx + 1])
            idx += 2
        else:
            idx += 1
    if not command:
        write_json({"ok": False, "error": "missing_required_args"})
        return 1
    project_root = Path(os.environ.get("PROJECT_ROOT") or os.getcwd()).resolve()
    provider = runtime_provider(project_root)
    if provider == "claude" and not settings:
        write_json({"ok": False, "error": "missing_required_args"})
        return 1
    command = _stop_hook_command(command, project_root)
    settings_path = Path(settings).expanduser().resolve() if settings else None
    try:
        result = ensure_stop_hook(
            provider=provider,
            project_root=project_root,
            settings_path=settings_path,
            command=command,
            timeout=timeout,
        )
    except HookConfigError as exc:
        write_json(
            {
                "ok": False,
                "error": exc.code,
                "path": str(exc.path),
                "provider": provider,
                "message": exc.message,
            }
        )
        return 1
    write_json({"ok": True, **result})
    return 0


def cmd_stop_hook(_: list[str]) -> int:
    sys.stdin.read()
    if os.environ.get("STORY_AUTOMATOR_CHILD", "").lower() == "true":
        return 0
    marker = active_marker_path()
    if not marker.exists():
        return 0
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A read error or malformed JSON marker is not an actionable active run;
        # allow the stop (matches the other liveness consumers' degrade path).
        return 0
    if not isinstance(payload, dict):
        # A valid-JSON but non-object marker (e.g. 123, "", []) would crash the
        # payload.get() below with AttributeError, escaping to the cli backstop
        # and breaking the stop-hook contract. Treat it as no active run.
        return 0
    raw_remaining = payload.get("storiesRemaining", 0)
    try:
        remaining = int(float(str(raw_remaining).strip()))
    except (TypeError, ValueError):
        # A malformed/non-numeric value must not wedge the session into an
        # indefinite block; treat it as "nothing remaining" and allow stop.
        remaining = 0
    if remaining <= 0:
        return 0
    if run_is_stale(payload):
        # The orchestrator's heartbeat is provably older than the staleness
        # window, so it has very likely crashed/exited. Release the stop hook so
        # the agent can halt instead of being blocked forever by a dead
        # supervisor. A fresh/missing/malformed heartbeat falls through to the
        # normal block (run_is_stale is False unless the age is past the window).
        return 0
    reason = (
        "Story Automator active "
        f"({remaining} stories remaining). Read "
        + _workflow_doc_relative("stop-hook-recovery.md")
    )
    print(json.dumps({"decision": "block", "reason": reason}, indent=2))
    return 0


def cmd_commit_story(args: list[str]) -> int:
    repo = ""
    story = ""
    title = ""
    for idx, arg in enumerate(args):
        if arg == "--repo" and idx + 1 < len(args):
            repo = args[idx + 1]
        elif arg == "--story" and idx + 1 < len(args):
            story = args[idx + 1]
        elif arg == "--title" and idx + 1 < len(args):
            title = args[idx + 1]
    if not repo or not story or not title:
        write_json({"ok": False, "error": "missing_args"})
        return 1
    if not Path(repo).is_dir():
        write_json({"ok": False, "error": "repo_not_found"})
        return 1
    status = run_cmd("git", "-C", repo, "status", "--porcelain")
    if status.exit_code != 0:
        write_json({"ok": False, "error": "git_status_failed"})
        return 1
    lines = [line for line in status.output.strip().splitlines() if line.strip()]
    if not lines:
        write_json({"ok": False, "error": "no_changes"})
        return 0
    if run_cmd("git", "-C", repo, "add", "-A").exit_code != 0:
        write_json({"ok": False, "error": "git_add_failed"})
        return 1
    message = f"feat(story-{story}): {title}"
    commit = run_cmd("git", "-C", repo, "commit", "-m", message)
    if commit.exit_code != 0:
        write_json({"ok": False, "error": "commit_failed"})
        return 1
    sha = run_cmd("git", "-C", repo, "rev-parse", "HEAD").output.strip()
    write_json({"ok": True, "commit": sha})
    return 0


def _git_changed_files(repo: str, extra_excludes: tuple[str, ...] = ()) -> list[str] | None:
    # `-z` gives NUL-separated, verbatim paths — no C-quoting/escaping of spaces or
    # non-ASCII, which `git status --porcelain` would otherwise apply. Superset of
    # staged+unstaged+untracked; `--untracked-files=all` lists files inside new dirs
    # instead of collapsing them to "src/".
    status = run_cmd("git", "-C", repo, "status", "--porcelain", "--untracked-files=all", "-z")
    if status.exit_code != 0:
        return None
    excludes = FILE_LIST_EXCLUDE_PREFIXES + extra_excludes
    fields = status.output.split("\0")
    files: set[str] = set()
    idx = 0
    while idx < len(fields):
        entry = fields[idx]
        if len(entry) < 3:  # empty trailing field or malformed line
            idx += 1
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:  # rename/copy: path is the destination; next field is the source
            idx += 2
        else:
            idx += 1
        if path and not any(path.startswith(prefix) for prefix in excludes):
            files.add(path)
    return sorted(files)


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    target = heading.strip().lower()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == target:
            start = idx
            break
    if start is None:
        return None
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("#"):  # column-0 heading only (ignore indented '#' in code blocks)
            end = idx
            break
    return start, end


def _file_list_bounds(lines: list[str]) -> tuple[int, int] | None:
    return _section_bounds(lines, "### File List")


# Known dev-record status annotations to strip when parsing a hand-written File
# List — a closed set, so we never mangle a real filename that ends in ")".
_FILE_LIST_ANNOTATIONS = ("(new)", "(modified)", "(deleted)", "(added)", "(renamed)", "(updated)")


def _paths_from_block(block: list[str]) -> list[str]:
    paths: list[str] = []
    for raw in block:
        cleaned = raw.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lstrip("-*").strip().strip("`").strip()
        low = cleaned.lower()
        for annotation in _FILE_LIST_ANNOTATIONS:
            if low.endswith(annotation):
                cleaned = cleaned[: -len(annotation)].strip().strip("`").strip()
                break
        if cleaned and not cleaned.startswith("("):
            paths.append(cleaned)
    return paths


def _reconcile_section(text: str, git_files: list[str]) -> tuple[str, list[str]]:
    """Return (new_text, current_paths). Rewrites the `### File List` body
    deterministically from git_files, leaving every other section untouched."""
    lines = text.splitlines()
    rendered = [f"- {path}" for path in git_files] if git_files else ["- (no files changed)"]
    suffix = "\n" if text.endswith("\n") else ""
    bounds = _file_list_bounds(lines)
    if bounds is None:
        new_lines = [*lines, "", "### File List", "", *rendered]
        return "\n".join(new_lines) + suffix, []
    start, end = bounds
    current = _paths_from_block(lines[start + 1 : end])
    tail = lines[end:]
    block = ["", *rendered]
    if tail:  # blank separator only when another section follows — avoids an extra EOF newline
        block.append("")
    new_lines = [*lines[: start + 1], *block, *tail]
    return "\n".join(new_lines) + suffix, current


# Map a story id to its artifact file (resolved key first, prefix glob fallback).
# Returns (story_file, None) on success or (None, error_payload) so callers can
# emit the error verbatim and bail.
def _resolve_story_file(repo: str, story: str) -> tuple[Path | None, dict | None]:
    norm = normalize_story_key(repo, story)
    if norm is None:
        return None, {"ok": False, "error": "story_key_invalid", "input": story}
    artifacts = implementation_artifacts_dir(repo)
    exact = artifacts / f"{norm.key}.md"
    if norm.key and exact.is_file():  # disambiguate via the resolved key before falling back to prefix glob
        return exact, None
    matches = sorted(artifacts.glob(f"{norm.prefix}-*.md"))
    if not matches:
        return None, {"ok": False, "error": "story_file_not_found", "prefix": norm.prefix}
    return matches[0], None


def cmd_reconcile_story(args: list[str]) -> int:
    repo = ""
    story = ""
    do_write = False
    for idx, arg in enumerate(args):
        if arg == "--repo" and idx + 1 < len(args):
            repo = args[idx + 1]
        elif arg == "--story" and idx + 1 < len(args):
            story = args[idx + 1]
        elif arg == "--write":
            do_write = True
    if not repo or not story:
        write_json({"ok": False, "error": "missing_args"})
        return 1
    if not Path(repo).is_dir():
        write_json({"ok": False, "error": "repo_not_found"})
        return 1
    story_file, err = _resolve_story_file(repo, story)
    if story_file is None:
        write_json(err)
        return 1
    # Exclude the resolved artifacts dir (may be _bmad-output/ OR docs/bmad/...) so the
    # story file and its siblings never pollute the reconciled File List.
    git_files = _git_changed_files(repo, (implementation_artifacts_relpath(repo) + "/",))
    if git_files is None:
        write_json({"ok": False, "error": "git_status_failed"})
        return 1
    text = story_file.read_text(encoding="utf-8")
    new_text, current = _reconcile_section(text, git_files)
    git_set, current_set = set(git_files), set(current)
    missing = sorted(git_set - current_set)
    stale = sorted(current_set - git_set)
    wrote = False
    if do_write and new_text != text:
        story_file.write_text(new_text, encoding="utf-8")
        wrote = True
    write_json(
        {
            "ok": True,
            "story_file": str(story_file),
            "git_files": git_files,
            "missing_from_story": missing,
            "stale_in_story": stale,
            "in_sync": not missing and not stale,
            "wrote": wrote,
        }
    )
    return 0


TEST_COUNTS_HEADING = "### Test Counts"


def _render_test_counts(counts: dict) -> list[str]:
    body = [
        f"- Tests: {counts['tests']}",
        f"- Failures: {counts['failures']}",
        f"- Errors: {counts['errors']}",
        f"- Skipped: {counts['skipped']}",
    ]
    if counts.get("assertions") is not None:  # PHPUnit-only; omit the line entirely otherwise
        body.append(f"- Assertions: {counts['assertions']}")
    return body


# Rewrite `heading`'s body deterministically (leaving other sections untouched),
# appending the section at EOF when absent. Mirrors the File List reconcile so a
# re-run with identical counts is a byte-for-byte no-op.
def _replace_or_append_section(text: str, heading: str, body: list[str]) -> str:
    lines = text.splitlines()
    suffix = "\n" if text.endswith("\n") else ""
    bounds = _section_bounds(lines, heading)
    if bounds is None:
        tail = ["", heading, "", *body]
        new_lines = [*lines, *tail] if lines else [heading, "", *body]
        return "\n".join(new_lines) + suffix
    start, end = bounds
    rest = lines[end:]
    block = ["", *body]
    if rest:  # blank separator only when another section follows
        block.append("")
    new_lines = [*lines[: start + 1], *block, *rest]
    return "\n".join(new_lines) + suffix


def cmd_test_counts(args: list[str]) -> int:
    if args and args[0] in {"--help", "-h"}:
        print("Usage: test-counts --repo PATH --story KEY [--since EPOCH] [--write]")
        return 0
    repo = ""
    story = ""
    since: float | None = None
    do_write = False
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--repo" and idx + 1 < len(args):
            repo = args[idx + 1]
            idx += 2
        elif arg == "--story" and idx + 1 < len(args):
            story = args[idx + 1]
            idx += 2
        elif arg == "--since" and idx + 1 < len(args):
            # --since is always machine-supplied (date +%s); a non-numeric value
            # is a contract break. Fail loud rather than silently dropping the
            # staleness gate, which would let a stale artifact pass as fresh.
            try:
                since = float(args[idx + 1])
            except ValueError:
                write_json({"ok": False, "error": "since_invalid", "value": args[idx + 1]})
                return 1
            idx += 2
        elif arg == "--write":
            do_write = True
            idx += 1
        else:
            idx += 1
    if not repo or not story:
        write_json({"ok": False, "error": "missing_args"})
        return 1
    if not Path(repo).is_dir():
        write_json({"ok": False, "error": "repo_not_found"})
        return 1
    story_file, err = _resolve_story_file(repo, story)
    if story_file is None:
        write_json(err)
        return 1
    try:
        cfg = test_config(load_policy_unresolved(repo))
    except PolicyError:
        write_json({"ok": False, "error": "policy_invalid"})
        return 1
    junit_rel = cfg["junitPath"]
    command = cfg["command"]
    if not junit_rel:  # Tier 3: nothing configured — File List reconcile still ran independently
        write_json({"ok": True, "skipped": True, "reason": "test_not_configured", "test_counts": None, "wrote": False})
        return 0
    junit_path = Path(repo) / junit_rel.replace("{story}", story_file.stem)
    fresh = junit_path.is_file() and (since is None or junit_path.stat().st_mtime >= since)
    rerun_exit: int | None = None
    if fresh:  # Tier 1: trust the artifact emitted by this dev run
        source = "capture"
    elif command:  # Tier 2: deterministic floor — re-run and parse what it emits
        # Shell-quote substitutions: the placeholders must be left UNquoted in the
        # command template (paths with spaces/metacharacters would break bash -c).
        resolved = command.replace("{junit}", shlex.quote(str(junit_path))).replace("{story}", shlex.quote(story_file.stem))
        ensure_dir(junit_path.parent)
        rerun_exit = run_cmd("bash", "-c", resolved, cwd=repo).exit_code  # non-zero is expected when tests fail
        if not junit_path.is_file():
            write_json(
                {"ok": True, "skipped": True, "reason": "test_artifact_not_emitted", "command_exit": rerun_exit, "test_counts": None, "wrote": False}
            )
            return 0
        source = "rerun"
    else:  # Tier 3: stale/missing artifact and no runner to fall back on
        reason = "test_artifact_stale" if junit_path.is_file() else "test_artifact_missing"
        write_json({"ok": True, "skipped": True, "reason": reason, "test_counts": None, "wrote": False})
        return 0
    try:
        counts = parse_junit(junit_path)
    except ValueError:
        write_json({"ok": False, "error": "junit_parse_failed", "junit_path": str(junit_path)})
        return 1
    text = story_file.read_text(encoding="utf-8")
    new_text = _replace_or_append_section(text, TEST_COUNTS_HEADING, _render_test_counts(counts))
    wrote = False
    if do_write and new_text != text:
        story_file.write_text(new_text, encoding="utf-8")
        wrote = True
    payload = {
        "ok": True,
        "skipped": False,
        "story_file": str(story_file),
        "source": source,
        "junit_path": str(junit_path),
        "test_counts": counts,
        "wrote": wrote,
    }
    if rerun_exit is not None:
        payload["command_exit"] = rerun_exit
    write_json(payload)
    return 0


def cmd_list_sessions(args: list[str]) -> int:
    if args and args[0] in {"--help", "-h"}:
        print("Usage: list-sessions --slug SLUG")
        return 0
    slug = ""
    for idx, arg in enumerate(args):
        if arg == "--slug" and idx + 1 < len(args):
            slug = args[idx + 1]
    if not slug:
        write_json({"ok": False, "error": "missing_slug"})
        return 1
    if shutil.which("tmux") is None:
        write_json({"ok": False, "error": "tmux_not_found", "sessions": [], "count": 0})
        return 0
    result = run_cmd("tmux", "list-sessions", "-F", "#{session_name}")
    if result.exit_code != 0:
        write_json({"ok": True, "sessions": [], "count": 0})
        return 0
    prefix = f"sa-{slug}-"
    sessions = [line for line in result.output.splitlines() if line.startswith(prefix)]
    write_json({"ok": True, "sessions": sessions, "count": len(sessions)})
    return 0
