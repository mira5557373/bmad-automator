"""``story-automator doctor`` — operator preflight health check.

Runs a handful of cheap, read-only environment checks so an operator can
catch a misconfigured VPS *before* starting a run rather than failing
mid-story. Emits a single compact JSON object on stdout (so step markdown
can branch via ``jq``); ``--human`` adds a readable one-line-per-check
summary on stderr. Exit code is non-zero only when a ``fail`` check trips
(a missing dependency or no available agent CLI) — ``warn`` checks keep the
exit code at 0 so the command is safe to wire into a soft preflight.

Read-only by design: no writes, no ledger access, no audit-log routines.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from ..core.common import print_json, run_cmd
from ..core.product_profile import ProfileError, load_effective_profile


def _bundle_data_dir() -> Path:
    # commands/doctor.py -> commands -> story_automator -> src -> <skill root>
    return Path(__file__).resolve().parents[3] / "data"


def _project_root() -> str:
    return os.environ.get("PROJECT_ROOT") or os.getcwd()


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _binary_version(binary: str, *version_args: str) -> str:
    """Best-effort one-line version string for a resolved binary."""
    try:
        output, code = run_cmd(binary, *version_args, timeout=10)
    except Exception:  # noqa: BLE001 - a flaky --version must not crash doctor
        return "present"
    if code != 0:
        return "present"
    return output.strip().splitlines()[0] if output.strip() else "present"


def _check_python() -> dict[str, str]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        return _check("python", "ok", f"Python {version}")
    return _check("python", "warn", f"Python {version} (<3.11 declared floor)")


def _check_dependencies() -> dict[str, str]:
    missing = [
        name for name in ("filelock", "psutil") if importlib.util.find_spec(name) is None
    ]
    if missing:
        return _check(
            "dependencies",
            "fail",
            "missing required packages: "
            + ", ".join(missing)
            + " (pip install story-automator pulls these)",
        )
    return _check("dependencies", "ok", "filelock and psutil importable")


def _check_tmux() -> dict[str, str]:
    if shutil.which("tmux") is None:
        return _check("tmux", "warn", "tmux not on PATH — child-session orchestration unavailable")
    return _check("tmux", "ok", _binary_version("tmux", "-V"))


def _check_agents() -> dict[str, str]:
    available = {name: shutil.which(name) for name in ("claude", "codex")}
    found = [name for name, path in available.items() if path]
    if not found:
        return _check("agents", "fail", "neither 'claude' nor 'codex' on PATH — no agent to spawn")
    if len(found) == 1:
        return _check("agents", "warn", f"only '{found[0]}' on PATH (no fallback agent)")
    return _check("agents", "ok", "claude and codex both on PATH")


def _check_git() -> dict[str, str]:
    if shutil.which("git") is None:
        return _check("git", "warn", "git not on PATH — commit-story will not work")
    return _check("git", "ok", _binary_version("git", "--version"))


def _check_disk() -> dict[str, str]:
    try:
        free = shutil.disk_usage(_project_root()).free
    except OSError as exc:
        return _check("disk", "warn", f"could not stat project root: {exc}")
    free_gib = free / (1024**3)
    if free < 1024**3:
        return _check("disk", "warn", f"{free_gib:.2f} GiB free (<1 GiB)")
    return _check("disk", "ok", f"{free_gib:.2f} GiB free")


def _check_audit_key() -> dict[str, str]:
    key = os.environ.get("BMAD_AUDIT_KEY", "")
    if not key:
        return _check("audit_key", "ok", "BMAD_AUDIT_KEY unset (audit chain disabled)")
    if len(key) < 16:
        return _check("audit_key", "warn", f"BMAD_AUDIT_KEY set but short ({len(key)} chars; prefer >=32)")
    return _check("audit_key", "ok", f"BMAD_AUDIT_KEY set ({len(key)} chars)")


def _check_config_files() -> dict[str, str]:
    data_dir = _bundle_data_dir()
    unparseable: list[str] = []
    checked = 0
    for name in ("agent-config-presets.json", "orchestration-policy.json", "complexity-rules.json"):
        path = data_dir / name
        if not path.is_file():
            continue
        checked += 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unparseable.append(name)
    if unparseable:
        return _check("config", "fail", "invalid JSON in: " + ", ".join(unparseable))
    if checked == 0:
        return _check("config", "warn", f"no bundled config files found under {data_dir}")
    return _check("config", "ok", f"{checked} bundled config file(s) parse cleanly")


def _check_file_descriptors() -> dict[str, str]:
    try:
        import resource  # POSIX-only
    except ImportError:
        return _check("file_descriptors", "ok", "RLIMIT_NOFILE check skipped (non-POSIX)")
    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and soft < 1024:
        return _check("file_descriptors", "warn", f"RLIMIT_NOFILE soft limit low ({soft})")
    return _check("file_descriptors", "ok", f"RLIMIT_NOFILE soft limit {soft}")


def _check_profile() -> dict[str, str]:
    try:
        profile = load_effective_profile(_project_root())
    except ProfileError as exc:
        return _check("profile", "warn", f"profile load failed: {exc}")
    profile_id = profile.get("id", "unknown")
    missing: list[str] = []
    toolchain = profile.get("toolchain") or {}
    for language in sorted(toolchain):
        for entry in toolchain.get(language) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            if entry.get("required", True) and name and shutil.which(name) is None:
                missing.append(name)
    if missing:
        return _check(
            "profile", "warn",
            f"profile '{profile_id}' loaded; missing required tools: {', '.join(missing)}"
        )
    return _check("profile", "ok", f"profile '{profile_id}' loaded; toolchain OK")


def cmd_doctor(args: list[str]) -> int:
    """Entry point for ``story-automator doctor``.

    Flags:
        --human   also print a readable one-line-per-check summary to stderr.
    """
    if args and args[0] in {"--help", "-h"}:
        print("Usage: doctor [--human]")
        return 0
    human = "--human" in args

    checks = [
        _check_python(),
        _check_dependencies(),
        _check_tmux(),
        _check_agents(),
        _check_git(),
        _check_disk(),
        _check_audit_key(),
        _check_config_files(),
        _check_profile(),
        _check_file_descriptors(),
    ]
    counts = {
        "ok": sum(1 for c in checks if c["status"] == "ok"),
        "warn": sum(1 for c in checks if c["status"] == "warn"),
        "fail": sum(1 for c in checks if c["status"] == "fail"),
    }
    ok = counts["fail"] == 0

    if human:
        glyph = {"ok": "✓", "warn": "!", "fail": "✗"}
        for check in checks:
            print(f"  [{glyph[check['status']]}] {check['name']}: {check['detail']}", file=sys.stderr)

    print_json({"ok": ok, "checks": checks, "summary": counts})
    return 0 if ok else 1
