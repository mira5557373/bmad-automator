from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_COMMAND_TIMEOUT = 600
COMMAND_TIMEOUT_EXIT = 124


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def print_json(value: Any) -> None:
    print(compact_json(value))


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_text_if_exists(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return read_text(file_path)


def write_atomic(path: str | Path, data: str | bytes) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            payload = data.encode("utf-8") if isinstance(data, str) else data
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        fsync_dir(target.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def fsync_dir(directory: str | Path) -> None:
    """Best-effort fsync of a directory so a preceding rename is crash-durable.

    On POSIX the directory entry created by ``os.replace`` is not guaranteed
    durable until the directory inode itself is fsynced; a power loss after the
    rename returns can otherwise leave the target missing even though the data
    block was synced. No-op where directory fsync is unsupported (notably
    Windows, which has no O_RDONLY directory handle for fsync).
    """
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except (OSError, ValueError):  # pragma: no cover - platform-dependent
        pass
    finally:
        os.close(dir_fd)


def file_exists(path: str | Path) -> bool:
    return Path(path).is_file()


def dir_exists(path: str | Path) -> bool:
    return Path(path).is_dir()


def pwd() -> str:
    return os.getcwd()


def project_root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT") or pwd()).resolve()


def md5_hex8(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()[:8]


def run_cmd(*args: str, timeout: int = DEFAULT_COMMAND_TIMEOUT, env: dict[str, str] | None = None, cwd: str | Path | None = None) -> tuple[str, int]:
    from .audit import scrub_env_for_subprocess

    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    # D-04: scrub the audit chain key at the trust boundary so a child
    # process cannot read or forge audit records.
    proc_env = scrub_env_for_subprocess(proc_env)
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        # Lenient decode so a non-UTF-8 byte in child output cannot raise
        # UnicodeDecodeError and break the JSON error contract.
        errors="replace",
        timeout=timeout,
        env=proc_env,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return output, completed.returncode


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def trim_lines(text: str) -> list[str]:
    return [line.rstrip("\r") for line in text.splitlines()]


def filter_input_box(text: str) -> str:
    lines = text.splitlines()
    start_re = re.compile(r"^\s*[╭┌]")
    end_re = re.compile(r"^\s*[╰└]")
    # Only the box-drawing vertical (U+2502) — NOT the ASCII pipe — so a
    # markdown table row ("| col | col |") is never swallowed if an orphan
    # box-start glyph leaves ``in_box`` stuck True.
    box_re = re.compile(r"^\s*│")
    in_box = False
    kept: list[str] = []
    for line in lines:
        if start_re.match(line):
            in_box = True
            continue
        if end_re.match(line):
            in_box = False
            continue
        if in_box and box_re.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def unquote_scalar(value: str) -> str:
    raw = value.strip()
    if len(raw) < 2:
        return raw
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        try:
            return json.loads(raw) if raw.startswith('"') else raw[1:-1]
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def parse_string_list_literal(raw: str) -> list[str] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed
    return None


def contains_any_prefix(value: str, prefixes: list[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def help_flag(value: str) -> bool:
    return value in {"--help", "-h"}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def default_string(value: str, default: str) -> str:
    return value or default
