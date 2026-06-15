# M13 — Soak Archive Verifier (foundation-m1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `scripts/verify_soak_format.py` — a pure-stdlib validator for `_bmad-output/soak/<YYYY-MM-DD>/<arm>/` archives — and `tests/test_soak_format.py` covering REQ-13(a)–(d) plus placeholder-token detection.

**Scope (M1 only):** This milestone implements the verifier and its tests. It explicitly does NOT touch `scripts/seed_soak_dir.py` (M2), `CONTRIBUTING.md` (M2), REQ-13(e)/(f) seed→verify tests (M2), coverage gates (M2), or any file under `skills/`. Per the milestone description in `.claude/workflow.json`, M1 is bounded to REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-12, REQ-13(a)–(d), REQ-14, the verifier-relevant NFRs, and the verifier-relevant quality gates.

**Architecture:** One standalone script under `scripts/`, with a `main(argv: list[str] | None = None) -> int` entry point and a `if __name__ == "__main__": raise SystemExit(main())` guard. Pure stdlib only (allowlist: `__future__`, `json`, `pathlib`, `datetime`, `argparse`, `sys`, `re`). Walks `<root>/<YYYY-MM-DD>/<arm>/`, validates three required files, normalizes `\r\n` to `\n` when reading text, emits findings sorted by path on stderr, returns `0`/`1`/`2`. The verifier MUST NOT import from `story_automator`.

**Tech Stack:** Python 3.11+, stdlib only. Tests use `unittest.TestCase` with `tempfile.TemporaryDirectory` fixtures (no tmux, no subprocess, no network).

---

## File Structure

| File | Purpose | LOC budget |
|---|---|---|
| `scripts/__init__.py` | Empty marker so `from scripts.verify_soak_format import main` works under `unittest discover -s tests` run from the repo root. | trivial |
| `scripts/verify_soak_format.py` | Pure-stdlib validator. CLI + `main(argv)`. Walks `<root>/<YYYY-MM-DD>/<arm>/`, validates three required files, returns 0/1/2. | ≤500 |
| `tests/test_soak_format.py` | `unittest.TestCase` covering REQ-13(a)–(d) plus placeholder-token detection, line-ending normalization, deterministic output, exit codes, and import-allowlist guard. | ≤500 |

**Module boundary.** The verifier is read-only and pure stdlib so it can be run against a minimal image. It MUST NOT import from `story_automator`. Tests construct fixtures in-process — they never invoke the script via subprocess.

**Discoverability.** Tests import via `from scripts.verify_soak_format import main`. This works because (a) `scripts/__init__.py` exists, and (b) `python -m unittest discover -s tests` inserts the cwd (repo root) at `sys.path[0]`. The existing `npm run test:python` sets `PYTHONPATH=skills/bmad-story-automator/src` and runs from the repo root, so the repo root remains on sys.path. As a belt-and-suspenders guard the test module also inserts the repo root explicitly.

---

## Conventions for Every Task

- Every Python file in this milestone begins with `from __future__ import annotations`.
- Every annotated parameter or return uses PEP 604 (`list[str] | None`), never `typing.Optional`/`typing.Union`.
- Path joins use `pathlib.Path`, never `os.sep` string concatenation.
- Text reads normalize `\r\n` to `\n` before parsing (NFR line-ending portability).
- Conventional Commits (`feat(m13):`, `test(m13):`, `docs(m13):`, etc.) with `Generated-By: claude-opus-4-7` trailer.
- One commit per task. Do not skip pre-commit hooks.

---

## Task 1: Scaffold verifier skeleton + first failing test (exit codes)

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/verify_soak_format.py`
- Create: `tests/test_soak_format.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_soak_format.py
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Belt-and-suspenders: make sure the repo root is on sys.path so
# `from scripts.verify_soak_format import main` resolves regardless of
# how the test runner sets PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class VerifyExitCodesTests(unittest.TestCase):
    def test_main_returns_zero_on_empty_root(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([tmp]), 0)

    def test_main_returns_two_on_usage_error(self) -> None:
        from scripts.verify_soak_format import main

        # Passing an unknown flag is a usage error (exit 2).
        self.assertEqual(main(["--no-such-flag"]), 2)

    def test_main_returns_one_when_path_missing(self) -> None:
        from scripts.verify_soak_format import main

        self.assertEqual(main(["/definitely/does/not/exist/soak-root"]), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_soak_format -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.verify_soak_format'`.

- [ ] **Step 3: Create the package marker and verifier skeleton**

```python
# scripts/__init__.py
```

```python
# scripts/verify_soak_format.py
from __future__ import annotations

import argparse
import json  # noqa: F401  # used by later tasks
import re  # noqa: F401  # used by later tasks
import sys
from datetime import date, datetime  # noqa: F401  # used by later tasks
from pathlib import Path

REQUIRED_FILES = ("telemetry.jsonl", "report.md", "config.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_soak_format.py",
        description="Validate the _bmad-output/soak/ archive layout.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="_bmad-output/soak/",
        help="Path to soak archive root (default: _bmad-output/soak/).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with 2 on usage error; preserve that.
        return int(exc.code) if isinstance(exc.code, int) else 2

    root = Path(args.path)
    if not root.exists():
        print(f"{root}: archive root does not exist", file=sys.stderr)
        return 1

    findings: list[str] = []
    # Future tasks populate findings via _validate_root(root).
    for line in sorted(findings):
        print(line, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests again**

Run: `python -m unittest tests.test_soak_format -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): scaffold verify_soak_format with exit-code contract"
```

---

## Task 2: Date directory + arm slug validation

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
class DateAndArmValidationTests(unittest.TestCase):
    def _make_root(self, tmp: str) -> Path:
        root = Path(tmp) / "soak"
        root.mkdir()
        return root

    def test_invalid_date_directory_is_reported(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "not-a-date").mkdir()
            self.assertEqual(main([str(root)]), 1)

    def test_invalid_arm_slug_is_reported(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            arm = root / "2026-06-13" / "BAD ARM!"
            arm.mkdir(parents=True)
            # Even with required files present, the slug is invalid.
            (arm / "telemetry.jsonl").write_text("", encoding="utf-8")
            (arm / "report.md").write_text("", encoding="utf-8")
            (arm / "config.json").write_text("{}", encoding="utf-8")
            self.assertEqual(main([str(root)]), 1)

    def test_empty_date_dir_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            (root / "2026-06-13").mkdir()
            self.assertEqual(main([str(root)]), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.DateAndArmValidationTests -v`
Expected: tests fail (verifier currently never reports findings).

- [ ] **Step 3: Implement date + slug validation**

In `scripts/verify_soak_format.py`, add module-level constants and helpers, then thread `_validate_root` into `main`:

```python
ARM_SLUG_RE = re.compile(r"^[a-z0-9._-]+$")


def _validate_date_dir(name: str) -> str | None:
    try:
        date.fromisoformat(name)
    except ValueError:
        return f"date directory name does not parse as ISO date: {name!r}"
    return None


def _validate_arm_slug(name: str) -> str | None:
    if not ARM_SLUG_RE.match(name):
        return f"arm directory name is not a valid slug [a-z0-9._-]+: {name!r}"
    return None


def _validate_root(root: Path) -> list[str]:
    findings: list[str] = []
    for date_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        date_err = _validate_date_dir(date_dir.name)
        if date_err is not None:
            findings.append(f"{date_dir}: {date_err}")
            continue
        for arm_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            arm_err = _validate_arm_slug(arm_dir.name)
            if arm_err is not None:
                findings.append(f"{arm_dir}: {arm_err}")
                continue
    return findings
```

Then in `main`, replace the empty `findings: list[str] = []` with:

```python
    findings = _validate_root(root)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): validate ISO date dirs and arm slugs"
```

---

## Task 3: Required-files check (REQ-13(a) and (b))

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
def _write_minimal_arm(root: Path, date_str: str = "2026-06-13", arm: str = "control") -> Path:
    arm_dir = root / date_str / arm
    arm_dir.mkdir(parents=True)
    (arm_dir / "telemetry.jsonl").write_text(
        '{"event_type":"StoryStarted","ts":"2026-06-13T00:00:00Z"}\n',
        encoding="utf-8",
        newline="",
    )
    (arm_dir / "report.md").write_text(
        "---\n"
        "arm: control\n"
        "date: 2026-06-13\n"
        "run_id: r1\n"
        "git_sha: abc1234\n"
        "started_at: 2026-06-13T00:00:00Z\n"
        "ended_at: 2026-06-13T01:00:00Z\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
        newline="",
    )
    (arm_dir / "config.json").write_text(
        '{"arm":"control","seed":1,"model":"m","concurrency":1,"notes":"n"}',
        encoding="utf-8",
        newline="",
    )
    return arm_dir


class RequiredFilesTests(unittest.TestCase):
    def test_valid_arm_passes(self) -> None:
        # REQ-13(a)
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            _write_minimal_arm(root)
            self.assertEqual(main([str(root)]), 0)

    def test_each_missing_required_file_fails(self) -> None:
        # REQ-13(b) — covers each of the three required files individually.
        from scripts.verify_soak_format import main

        for missing in ("telemetry.jsonl", "report.md", "config.json"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "soak"
                root.mkdir()
                arm_dir = _write_minimal_arm(root)
                (arm_dir / missing).unlink()
                self.assertEqual(main([str(root)]), 1, missing)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.RequiredFilesTests -v`
Expected: `test_each_missing_required_file_fails` fails (verifier doesn't check files yet).

- [ ] **Step 3: Add required-files check**

In `scripts/verify_soak_format.py`, add `_validate_arm_dir` and call it from `_validate_root`:

```python
def _validate_arm_dir(arm_dir: Path) -> list[str]:
    findings: list[str] = []
    for name in REQUIRED_FILES:
        if not (arm_dir / name).is_file():
            findings.append(f"{arm_dir / name}: required file missing")
    return findings


def _validate_root(root: Path) -> list[str]:
    findings: list[str] = []
    for date_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        date_err = _validate_date_dir(date_dir.name)
        if date_err is not None:
            findings.append(f"{date_dir}: {date_err}")
            continue
        for arm_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            arm_err = _validate_arm_slug(arm_dir.name)
            if arm_err is not None:
                findings.append(f"{arm_dir}: {arm_err}")
                continue
            findings.extend(_validate_arm_dir(arm_dir))
    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): require telemetry.jsonl, report.md, config.json"
```

---

## Task 4: Validate report.md frontmatter (REQ-13(c))

REQ-05 says `started_at` and `ended_at` "must parse via `datetime.datetime.fromisoformat`". The verifier enforces this literally — both keys must be valid ISO datetimes. (The seeder's `pending` sentinel for `ended_at` is M2's concern; resolving that tension is M2 scope.)

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
class FrontmatterTests(unittest.TestCase):
    # REQ-13(c)

    def test_missing_frontmatter_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text("Body only.\n", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 1)

    def test_unterminated_frontmatter_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "no closing fence\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_required_key_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            # Drop git_sha.
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_unparseable_started_at_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: nope\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_unparseable_ended_at_fails(self) -> None:
        # REQ-05 is literal: ended_at must parse via fromisoformat. No
        # 'pending' carve-out here — that tension is M2 scope.
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: pending\n"
                "---\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.FrontmatterTests -v`
Expected: fails (no frontmatter validation yet).

- [ ] **Step 3: Implement frontmatter parsing + validation**

Add to `scripts/verify_soak_format.py`:

```python
REQUIRED_FRONTMATTER_KEYS = ("arm", "date", "run_id", "git_sha", "started_at", "ended_at")
_FRONTMATTER_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def _read_text_lf(path: Path) -> str:
    # NFR: treat CRLF and LF equivalently when reading.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    result: dict[str, str] = {}
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() == "---":
            return result
        match = _FRONTMATTER_LINE_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        # Strip optional surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return None  # closing --- not found


def _parse_iso_datetime(value: str) -> bool:
    # datetime.fromisoformat in 3.11+ accepts 'Z' suffix on 3.11+? Only 3.12+
    # natively, and Python 3.11 raises. Normalize to '+00:00' to keep
    # behavior identical across 3.11/3.12/3.13/3.14 per CLAUDE.md tech stack.
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_report_md(arm_dir: Path) -> list[str]:
    path = arm_dir / "report.md"
    findings: list[str] = []
    try:
        text = _read_text_lf(path)
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    fm = _parse_frontmatter(text)
    if fm is None:
        return [f"{path}: missing or unterminated YAML frontmatter block"]
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm:
            findings.append(f"{path}: frontmatter missing required key {key!r}")
    started = fm.get("started_at")
    if started is not None and not _parse_iso_datetime(started):
        findings.append(
            f"{path}: frontmatter 'started_at' does not parse as ISO datetime: {started!r}"
        )
    ended = fm.get("ended_at")
    if ended is not None and not _parse_iso_datetime(ended):
        findings.append(
            f"{path}: frontmatter 'ended_at' does not parse as ISO datetime: {ended!r}"
        )
    return findings
```

In `_validate_arm_dir`, after the required-files loop, if `(arm_dir / "report.md").is_file()`, call `_validate_report_md(arm_dir)` and extend findings.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): validate report.md frontmatter keys and datetimes"
```

---

## Task 5: Validate config.json (schema + arm-name consistency)

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
class ConfigJsonTests(unittest.TestCase):
    def test_non_object_root_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text("[]", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 1)

    def test_missing_key_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":1,"model":"m","concurrency":1}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_wrong_type_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":"one","model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_bool_does_not_satisfy_int(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":true,"model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_arm_mismatch_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)  # arm dir named "control"
            (arm_dir / "config.json").write_text(
                '{"arm":"treatment","seed":1,"model":"m","concurrency":1,"notes":"n"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_invalid_json_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text("{not json", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.ConfigJsonTests -v`
Expected: fails.

- [ ] **Step 3: Implement config.json validation**

Add to `scripts/verify_soak_format.py`:

```python
CONFIG_SCHEMA: tuple[tuple[str, type], ...] = (
    ("arm", str),
    ("seed", int),
    ("model", str),
    ("concurrency", int),
    ("notes", str),
)


def _validate_config_json(arm_dir: Path) -> list[str]:
    path = arm_dir / "config.json"
    findings: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc.msg}"]
    if not isinstance(data, dict):
        return [f"{path}: top-level value must be a JSON object"]
    for key, expected_type in CONFIG_SCHEMA:
        if key not in data:
            findings.append(f"{path}: missing required key {key!r}")
            continue
        value = data[key]
        # Reject bool for int (bool is subclass of int in Python).
        if expected_type is int and isinstance(value, bool):
            findings.append(f"{path}: key {key!r} must be int, got bool")
        elif not isinstance(value, expected_type):
            findings.append(
                f"{path}: key {key!r} must be {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
    arm_value = data.get("arm")
    if isinstance(arm_value, str) and arm_value != arm_dir.name:
        findings.append(
            f"{path}: config 'arm' = {arm_value!r} does not match directory name {arm_dir.name!r}"
        )
    return findings
```

Wire it into `_validate_arm_dir` after the frontmatter check, guarded by `(arm_dir / "config.json").is_file()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): validate config.json schema and arm consistency"
```

---

## Task 6: Validate telemetry.jsonl (REQ-13(d))

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
class TelemetryJsonlTests(unittest.TestCase):
    def test_empty_file_passes(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text("", encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 0)

    def test_blank_lines_are_skipped(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\n\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)

    def test_invalid_json_line_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\nnot-json\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_event_type_fails(self) -> None:
        # REQ-13(d)
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"ts":"2026-06-13T00:00:00Z"}\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_missing_ts_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X"}\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_non_object_line_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '["not","object"]\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.TelemetryJsonlTests -v`
Expected: fails.

- [ ] **Step 3: Implement telemetry.jsonl validation**

Add to `scripts/verify_soak_format.py`:

```python
def _validate_telemetry_jsonl(arm_dir: Path) -> list[str]:
    path = arm_dir / "telemetry.jsonl"
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read: {exc}"]
    # NFR: normalize CRLF to LF before splitting so behavior matches
    # across OSes.
    for idx, raw_line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"{path}:{idx}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(obj, dict):
            findings.append(f"{path}:{idx}: line is not a JSON object")
            continue
        if not isinstance(obj.get("event_type"), str):
            findings.append(f"{path}:{idx}: missing string field 'event_type'")
        if not isinstance(obj.get("ts"), str):
            findings.append(f"{path}:{idx}: missing string field 'ts'")
    return findings
```

Wire into `_validate_arm_dir` after the config.json check, guarded by `(arm_dir / "telemetry.jsonl").is_file()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): validate telemetry.jsonl per-line JSON with event_type/ts"
```

---

## Task 7: Placeholder-token detection in report.md and config.json (REQ-12)

REQ-12 forbids unresolved four-letter bracketed placeholder tokens. We detect any `[XXXX]` pattern where `XXXX` is exactly four uppercase ASCII letters between square brackets. Examples that must fail: `[TODO]`, `[FIXM]`, `[TBDX]`. Examples that must pass: `[link](url)`, `[citation needed]`, `[1234]`.

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_soak_format.py`:

```python
class PlaceholderTokenTests(unittest.TestCase):
    def test_placeholder_in_report_md_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n"
                "Body with [TODO] left in it.\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_placeholder_in_config_json_fails(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "config.json").write_text(
                '{"arm":"control","seed":1,"model":"m","concurrency":1,"notes":"[FIXM]"}',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_markdown_link_is_not_a_placeholder(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "report.md").write_text(
                "---\n"
                "arm: control\n"
                "date: 2026-06-13\n"
                "run_id: r1\n"
                "git_sha: abc1234\n"
                "started_at: 2026-06-13T00:00:00Z\n"
                "ended_at: 2026-06-13T01:00:00Z\n"
                "---\n"
                "See [link](https://example.com) and [1234] for details.\n",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_soak_format.PlaceholderTokenTests -v`
Expected: fails.

- [ ] **Step 3: Implement placeholder detection**

Add to `scripts/verify_soak_format.py`:

```python
PLACEHOLDER_RE = re.compile(r"\[[A-Z]{4}\]")


def _check_placeholders(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for idx, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        match = PLACEHOLDER_RE.search(line)
        if match is not None:
            findings.append(
                f"{path}:{idx}: unresolved four-letter placeholder token {match.group(0)!r}"
            )
    return findings
```

In `_validate_report_md`, before returning, call `findings.extend(_check_placeholders(path, text))`.
In `_validate_config_json`, before returning, call `findings.extend(_check_placeholders(path, raw))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): reject unresolved four-letter placeholder tokens"
```

---

## Task 8: Deterministic sorted output (NFR determinism)

**Files:**
- Modify: `tests/test_soak_format.py`
- (Verifier already sorts; this task adds a regression guard.)

- [ ] **Step 1: Add the regression test**

Append to `tests/test_soak_format.py`:

```python
import contextlib
import io


class DeterministicOutputTests(unittest.TestCase):
    def _run_capture(self, root: Path) -> list[str]:
        from scripts.verify_soak_format import main

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = main([str(root)])
        self.assertEqual(rc, 1)
        return [line for line in buf.getvalue().split("\n") if line]

    def test_findings_are_sorted_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            for arm in ("zeta", "alpha", "mid"):
                arm_dir = root / "2026-06-13" / arm
                arm_dir.mkdir(parents=True)
                # All three missing files → three findings per arm.
            findings = self._run_capture(root)
            self.assertEqual(findings, sorted(findings))
```

- [ ] **Step 2: Run to verify it passes**

Run: `python -m unittest tests.test_soak_format.DeterministicOutputTests -v`
Expected: PASS (verifier already calls `sorted(findings)` before printing).

If it fails, fix the verifier to sort before printing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin deterministic sorted finding output"
```

---

## Task 9: CRLF line-ending portability (NFR)

The verifier must treat `\r\n` and `\n` as equivalent when reading `report.md` and `telemetry.jsonl`.

**Files:**
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write tests**

Append to `tests/test_soak_format.py`:

```python
class LineEndingTests(unittest.TestCase):
    def test_crlf_report_md_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            crlf_report = (
                "---\r\n"
                "arm: control\r\n"
                "date: 2026-06-13\r\n"
                "run_id: r1\r\n"
                "git_sha: abc1234\r\n"
                "started_at: 2026-06-13T00:00:00Z\r\n"
                "ended_at: 2026-06-13T01:00:00Z\r\n"
                "---\r\n"
                "Body.\r\n"
            )
            (arm_dir / "report.md").write_text(crlf_report, encoding="utf-8", newline="")
            self.assertEqual(main([str(root)]), 0)

    def test_crlf_telemetry_jsonl_is_accepted(self) -> None:
        from scripts.verify_soak_format import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            root.mkdir()
            arm_dir = _write_minimal_arm(root)
            (arm_dir / "telemetry.jsonl").write_text(
                '{"event_type":"X","ts":"2026-06-13T00:00:00Z"}\r\n',
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 0)
```

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_soak_format.LineEndingTests -v`
Expected: PASS (verifier already normalizes CRLF→LF before parsing).

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin CRLF/LF portability in verifier reads"
```

---

## Task 10: Import-allowlist guard test (REQ-07, Quality gate)

REQ-07 and the quality-gate "Import-allowlist grep" pin the verifier to stdlib-only: `__future__`, `json`, `pathlib`, `datetime`, `argparse`, `sys`, `re`. The test below makes this an in-suite regression guard so a future edit can't silently add `os` or `subprocess`.

**Files:**
- Modify: `tests/test_soak_format.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_soak_format.py`:

```python
import re as stdlib_re


class ImportAllowlistTests(unittest.TestCase):
    def test_verifier_only_imports_allowlisted_stdlib(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "verify_soak_format.py"
        text = path.read_text(encoding="utf-8")
        allowed = {"__future__", "json", "pathlib", "datetime", "argparse", "sys", "re"}
        import_lines = [
            ln for ln in text.split("\n")
            if ln.startswith("import ") or ln.startswith("from ")
        ]
        for line in import_lines:
            match = stdlib_re.match(r"^(?:from|import)\s+([A-Za-z_][A-Za-z_0-9.]*)", line)
            self.assertIsNotNone(match, line)
            top = match.group(1).split(".")[0]
            self.assertIn(
                top,
                allowed,
                f"verify_soak_format.py imports non-allowlisted module {top!r} ({line})",
            )

    def test_verifier_does_not_import_story_automator(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "verify_soak_format.py"
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("story_automator", text)
```

- [ ] **Step 2: Run the test**

Run: `python -m unittest tests.test_soak_format.ImportAllowlistTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin verifier stdlib-only import allowlist"
```

---

## Task 11: Quality gates — ruff, line counts, import grep

The M1 milestone description in `.claude/workflow.json` requires: `ruff check`, `ruff format --check`, `unittest discover`, the import-allowlist grep gate, and the ≤500 LOC constraint. Coverage (`coverage report --fail-under=85`) is **M2 scope** ("coverage report --fail-under=85 across both scripts") and is NOT a gate for M1.

**Files:** none modified unless ruff finds issues.

- [ ] **Step 1: Lint**

Run: `python -m ruff check scripts/verify_soak_format.py tests/test_soak_format.py`
Expected: `All checks passed!` (no findings).

If any findings, fix them (typical: import ordering, unused imports). Re-run until clean.

- [ ] **Step 2: Format check**

Run: `python -m ruff format --check scripts/verify_soak_format.py tests/test_soak_format.py`
Expected: `2 files already formatted`.

If anything would reformat, run `python -m ruff format scripts/verify_soak_format.py tests/test_soak_format.py` and stage + commit as `style(m13): ruff format`.

- [ ] **Step 3: Line-count guard**

Run (bash):
```bash
wc -l scripts/verify_soak_format.py tests/test_soak_format.py
```

Expected: each ≤ 500 lines. If `scripts/verify_soak_format.py` exceeds 500, factor private helpers into a smaller second file under `scripts/` (and update the import-allowlist test accordingly). If the test file exceeds 500, split test classes across `tests/test_soak_format.py` and `tests/test_soak_format_extra.py`.

- [ ] **Step 4: Full unittest suite**

Run: `python -m unittest tests.test_soak_format -v`
Expected: all tests pass, zero failures, zero errors.

Also run the project-default test runner to confirm nothing else regressed:

```bash
npm run test:python
```

Expected: green.

- [ ] **Step 5: Import-allowlist grep gate**

Run (bash):
```bash
grep -E "^(from|import) " scripts/verify_soak_format.py | sort -u
```

Expected: only `__future__`, `argparse`, `datetime`, `json`, `pathlib`, `re`, `sys`. Anything else is a gate failure.

- [ ] **Step 6: No commit needed unless gates produced edits**

If ruff format or refactoring touched files, commit:

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(m13): ruff format / quality-gate touchups"
```

Otherwise: no commit.

---

## Self-Review Checklist

**1. Spec coverage (M1-scoped only — REQ-08, 09, 10, 11 are M2):**

| REQ | Task |
|---|---|
| REQ-01 (archive root + path pattern) | Tasks 2 (date dir + arm slug) |
| REQ-02 (three required files) | Task 3 |
| REQ-03 (verify `main(argv)` signature + exit codes 0/1/2) | Task 1 |
| REQ-04 (date dir + arm dir + missing-file reporting on stderr) | Tasks 2, 3 |
| REQ-05 (frontmatter keys + ISO datetime parsing — strict) | Task 4 |
| REQ-06 (config.json schema + arm equality) | Task 5 |
| REQ-07 (telemetry.jsonl JSON + event_type/ts + import allowlist) | Tasks 6, 10 |
| REQ-12 (placeholder-token detection in verifier) | Task 7 |
| REQ-13(a) valid arm passes | Task 3 |
| REQ-13(b) missing required file fails | Task 3 |
| REQ-13(c) malformed frontmatter fails | Task 4 |
| REQ-13(d) telemetry line lacking event_type fails | Task 6 |
| REQ-13(e), (f) | M2 — out of scope here |
| REQ-14 (`from __future__ import annotations`, `__main__` guard, PEP 604) | Conventions + Task 1 |
| NFR cross-platform `pathlib.Path` | Conventions + all tasks |
| NFR dependency floor (stdlib only) | Task 10 |
| NFR module size ≤ 500 LOC | Task 11 step 3 |
| NFR line-ending portability (CRLF≡LF on read) | Tasks 4 (helper), 6, 9 (test) |
| NFR typing posture (no Optional/Union) | Conventions |
| NFR determinism (sorted output) | Task 8 |
| Quality gate: ruff check | Task 11 step 1 |
| Quality gate: ruff format check | Task 11 step 2 |
| Quality gate: unittest passes | Task 11 step 4 |
| Quality gate: import-allowlist grep | Tasks 10, 11 step 5 |
| Quality gate: line count ≤ 500 | Task 11 step 3 |
| Quality gate: coverage ≥ 85% | M2 — out of scope here |
| Quality gate: self-verification seed→verify | M2 — out of scope here |
| Quality gate: CONTRIBUTING.md placeholder grep | M2 — out of scope here |

**2. Placeholder scan:** Every step shows complete code or exact commands. No `TBD`, no `add appropriate error handling`. The string `pending` appears only as the *literal frontmatter value* that the verifier rejects per REQ-05 in `test_unparseable_ended_at_fails` — not as a plan placeholder.

**3. Type / name consistency:**
- `REQUIRED_FILES`, `ARM_SLUG_RE`, `REQUIRED_FRONTMATTER_KEYS`, `CONFIG_SCHEMA`, `PLACEHOLDER_RE` are defined once at module scope.
- All `_validate_*` helpers return `list[str]` and consumers consistently use `findings.extend(...)`.
- `main(argv: list[str] | None = None) -> int` signature matches REQ-03.
- `_parse_iso_datetime` normalizes `'Z'` → `'+00:00'` so behavior is identical across Python 3.11/3.12/3.13/3.14 (CLAUDE.md tech-stack range).

**4. Out-of-scope guard:** No task creates `scripts/seed_soak_dir.py`, modifies `CONTRIBUTING.md`, or imports from `story_automator`. The verifier is a self-contained stdlib script. M2 (`integration-m2-seed-and-docs`) will add the seeder, the `CONTRIBUTING.md` "Soak archive" section, REQ-13(e)/(f) tests, the coverage gate, and the seed→verify self-verification gate.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-15-foundation-m1-verify-format.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review between tasks.
2. **Inline Execution** — batch execution with checkpoints.

Which approach?
