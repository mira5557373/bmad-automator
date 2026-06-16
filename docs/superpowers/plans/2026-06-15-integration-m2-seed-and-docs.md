# M13 Integration M2 — Seed + Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the second M13 wedge — `scripts/seed_soak_dir.py`, a CONTRIBUTING.md "Soak archive" section, the verifier's placeholder-token gate, and the CI self-verification step — so an operator can `seed → verify` an empty arm directory with zero hand-editing.

**Architecture:** `seed_soak_dir.py` is a single-file stdlib CLI that imports `iso_now`, `compact_json`, `write_atomic`, and `ensure_dir` from `story_automator.core.common` when the package is importable and falls back to inlined stdlib-only equivalents otherwise. It writes the three M13-required stub files with explicit `\n` line endings and refuses to overwrite any non-empty existing file (idempotence). The verifier (built in M1) gains a four-letter-bracket placeholder check applied to `report.md` and `config.json`; CONTRIBUTING.md picks up a "Soak archive" section and CI gets a grep gate plus a seed→verify smoke step that proves the two scripts agree on the schema.

**Tech Stack:** Python 3.11+ stdlib (`argparse`, `json`, `pathlib`, `re`, `sys`, `datetime`, `tempfile`, `os`), `unittest.TestCase`, GitHub Actions bash, `ruff`, `coverage`.

**Dependencies:** Builds on `foundation-m1-verify-format` — REQ-01..REQ-07 already pass; this plan adds REQ-08..REQ-14 plus the matching non-functional/quality gates.

**Spec:** `docs/superpowers/specs/2026-06-14-m13-soak-archive.md` (REQ-08..REQ-14, Non-functional requirements, Quality gates).

---

## File Map

- **Create:** `scripts/seed_soak_dir.py` — `main(argv) -> int` CLI; emits stub `telemetry.jsonl`, `config.json`, `report.md`.
- **Modify:** `scripts/verify_soak_format.py` — add `PLACEHOLDER_RE`, `_check_placeholders`, and a `pending` carve-out for `ended_at`.
- **Modify:** `tests/test_soak_format.py` — extend with `_write_minimal_arm` helper, frontmatter / config / telemetry edge cases, and seed-driven scenarios (REQ-13).
- **Create:** `tests/test_soak_format_extra.py` — placeholder-token, line-ending, import-allowlist, and CONTRIBUTING grep-gate tests (split out so neither test module exceeds 500 LOC).
- **Modify:** `CONTRIBUTING.md` — append a "Soak archive" section (layout, schema, slug rule, commands, placeholder rule).
- **Modify:** `.github/workflows/ci.yml` — add the CONTRIBUTING grep gate step and the seed→verify self-verification step.

---

## Task 1: Verifier — pending sentinel for `ended_at`

**Files:**
- Modify: `scripts/verify_soak_format.py` (around `_validate_report_md`)
- Modify: `tests/test_soak_format.py` (FrontmatterTests)

Why first: REQ-10 lets the seed leave `ended_at: pending` until the operator finalizes. Without the carve-out, the very first thing the seed script writes would fail verification.

- [ ] **Step 1: Write the failing test**

Append to `FrontmatterTests` in `tests/test_soak_format.py`:

```python
def test_ended_at_pending_sentinel_is_accepted(self) -> None:
    # REQ-10 carve-out: freshly seeded archives leave ended_at = "pending"
    # until the operator finalizes the run; verify must accept this.
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
        self.assertEqual(main([str(root)]), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.FrontmatterTests.test_ended_at_pending_sentinel_is_accepted -v`
Expected: FAIL — verifier currently rejects `ended_at: pending` because it does not parse as ISO datetime.

- [ ] **Step 3: Add the carve-out**

In `scripts/verify_soak_format.py`, replace the `ended_at` check inside `_validate_report_md` with:

```python
ended = fm.get("ended_at")
# REQ-10/Self-verification carve-out: ended_at may be the literal sentinel
# "pending" while the run is in flight. Any other non-ISO value is rejected.
if ended is not None and ended != "pending" and not _parse_iso_datetime(ended):
    findings.append(
        f"{path}: frontmatter 'ended_at' does not parse as ISO datetime: {ended!r}"
    )
```

- [ ] **Step 4: Run the new test plus existing FrontmatterTests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.FrontmatterTests -v`
Expected: all pass, including the prior `test_unparseable_ended_at_fails` (which uses `"not-a-date"`, not `"pending"`).

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): accept pending sentinel for report.md ended_at"
```

---

## Task 2: Seed CLI scaffold — arg parser + exit codes

**Files:**
- Create: `scripts/seed_soak_dir.py`
- Modify: `tests/test_soak_format.py` (new `SeedSoakDirTests` class)

- [ ] **Step 1: Write failing tests for the exit-code contract**

Append to `tests/test_soak_format.py`:

```python
class SeedSoakDirTests(unittest.TestCase):
    # REQ-13(e), REQ-13(f), REQ-09 (idempotence).

    def test_seed_rejects_invalid_date(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            rc = seed_main(["--date", "2026/06/13", "--arm", "control", "--root", tmp])
            self.assertEqual(rc, 2)

    def test_seed_rejects_invalid_arm_slug(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            rc = seed_main(["--date", "2026-06-13", "--arm", "BAD ARM!", "--root", tmp])
            self.assertEqual(rc, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests -v`
Expected: ImportError / ModuleNotFoundError — `scripts/seed_soak_dir.py` does not exist yet.

- [ ] **Step 3: Create the scaffold**

Write `scripts/seed_soak_dir.py`:

```python
# scripts/seed_soak_dir.py
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARM_SLUG_RE = re.compile(r"^[a-z0-9._-]+$")
DEFAULT_ROOT = "_bmad-output/soak/"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_soak_dir.py",
        description="Seed a soak-archive arm directory with stub files.",
    )
    parser.add_argument("--date", required=True, help="ISO calendar date YYYY-MM-DD.")
    parser.add_argument("--arm", required=True, help="Arm slug matching [a-z0-9._-]+.")
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"Soak archive root (default: {DEFAULT_ROOT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not DATE_RE.match(args.date):
        print(f"--date must be YYYY-MM-DD: {args.date!r}", file=sys.stderr)
        return 2
    if not ARM_SLUG_RE.match(args.arm):
        print(f"--arm must match [a-z0-9._-]+: {args.arm!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify the contract**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests -v`
Expected: both `test_seed_rejects_invalid_*` pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_soak_dir.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): scaffold seed_soak_dir CLI with date/arm validation"
```

---

## Task 3: Seed CLI — wire story_automator helpers with stdlib fallback

**Files:**
- Modify: `scripts/seed_soak_dir.py` (top of file)
- Create later in Task 11: `tests/test_soak_format_extra.py` will pin this; for now, satisfy REQ-09 in place.

REQ-09 says: prefer the shared helpers (`iso_now`, `compact_json`, `write_atomic`, `ensure_dir`) when `story_automator` is importable; otherwise inline pure-stdlib equivalents.

- [ ] **Step 1: Add the import block with fallback**

Insert between `import sys` and the regex constants:

```python
try:  # REQ-09: prefer story_automator helpers when available.
    from story_automator.core.common import (
        compact_json,
        ensure_dir,
        iso_now,
        write_atomic,
    )
except ImportError:  # Fallback: pure-stdlib equivalents.
    import datetime as _dt
    import os as _os
    import tempfile as _tempfile
    from typing import Any as _Any

    def iso_now() -> str:
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def compact_json(value: _Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    def ensure_dir(path: str | Path) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def write_atomic(path: str | Path, data: str | bytes) -> None:
        target = Path(path)
        ensure_dir(target.parent)
        fd, tmp_name = _tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with _os.fdopen(fd, "wb") as handle:
                payload = data.encode("utf-8") if isinstance(data, str) else data
                handle.write(payload)
                handle.flush()
                _os.fsync(handle.fileno())
            _os.replace(tmp_name, target)
        finally:
            try:
                _os.unlink(tmp_name)
            except FileNotFoundError:
                pass
```

Notes:
- `write_atomic` uses `_os.replace` for cross-platform atomicity (Windows allows replace over an existing file).
- The fallback `iso_now` uses UTC `Z` suffix to match `story_automator.core.common.iso_now`.
- `ensure_ascii=False` matches the shared helper's compact-json convention.

- [ ] **Step 2: Run the existing seed tests to confirm no regression**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests -v`
Expected: pass (no behavior change yet; we only added unused helpers).

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_soak_dir.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): wire story_automator helpers into seed with stdlib fallback"
```

---

## Task 4: Seed CLI — emit the three stub files

**Files:**
- Modify: `scripts/seed_soak_dir.py`
- Modify: `tests/test_soak_format.py` (`SeedSoakDirTests`)

REQ-08 / REQ-10: seed must create the arm dir plus `telemetry.jsonl` (empty), `config.json` (with `arm/seed/model/concurrency/notes` defaults), and `report.md` (frontmatter with `started_at` from `iso_now()` and `ended_at: pending`).

- [ ] **Step 1: Write the failing integration test**

Append to `SeedSoakDirTests`:

```python
def test_seed_then_verify_passes(self) -> None:
    from scripts.seed_soak_dir import main as seed_main
    from scripts.verify_soak_format import main as verify_main

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "soak"
        rc_seed = seed_main(
            ["--date", "2026-06-13", "--arm", "gate-check", "--root", str(root)]
        )
        self.assertEqual(rc_seed, 0)
        arm_dir = root / "2026-06-13" / "gate-check"
        self.assertTrue((arm_dir / "telemetry.jsonl").is_file())
        self.assertTrue((arm_dir / "config.json").is_file())
        self.assertTrue((arm_dir / "report.md").is_file())
        self.assertEqual(verify_main([str(root)]), 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests.test_seed_then_verify_passes -v`
Expected: FAIL — files are not created.

- [ ] **Step 3: Implement file emission**

Add to `scripts/seed_soak_dir.py` (above `main`):

```python
def _config_defaults(arm: str) -> dict[str, object]:
    return {
        "arm": arm,
        "seed": 0,
        "model": "unset",
        "concurrency": 1,
        "notes": "",
    }


def _report_frontmatter(arm: str, date_str: str, started_at: str) -> str:
    # NFR: explicit \n joins so output is byte-identical on Windows and Linux.
    lines = (
        "---",
        f"arm: {arm}",
        f"date: {date_str}",
        "run_id: pending",
        "git_sha: pending",
        f"started_at: {started_at}",
        "ended_at: pending",
        "---",
        "",
    )
    return "\n".join(lines)


def _seed_if_absent(path: Path, contents: str) -> bool:
    # REQ-09: idempotent. Never clobber an existing non-empty file.
    if path.exists() and path.stat().st_size > 0:
        return False
    write_atomic(path, contents)
    return True
```

Replace the trailing `return 0` block of `main` with:

```python
    arm_dir = Path(args.root) / args.date / args.arm
    ensure_dir(arm_dir)

    started_at = iso_now()
    config_text = compact_json(_config_defaults(args.arm))
    report_text = _report_frontmatter(args.arm, args.date, started_at)

    _seed_if_absent(arm_dir / "telemetry.jsonl", "")
    _seed_if_absent(arm_dir / "config.json", config_text)
    _seed_if_absent(arm_dir / "report.md", report_text)
    return 0
```

- [ ] **Step 4: Run the seed→verify integration test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests.test_seed_then_verify_passes -v`
Expected: PASS. The seed produces an arm that the verifier accepts (proving the two scripts agree on the schema, per the Self-verification quality gate).

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_soak_dir.py tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): seed emits telemetry.jsonl, config.json, report.md stubs"
```

---

## Task 5: Seed CLI — idempotence (REQ-13(f), REQ-09)

**Files:**
- Modify: `tests/test_soak_format.py` (`SeedSoakDirTests`)

- [ ] **Step 1: Write the failing test**

Append to `SeedSoakDirTests`:

```python
def test_seed_is_idempotent(self) -> None:
    from scripts.seed_soak_dir import main as seed_main

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "soak"
        args = ["--date", "2026-06-13", "--arm", "control", "--root", str(root)]
        self.assertEqual(seed_main(args), 0)
        arm_dir = root / "2026-06-13" / "control"
        # Operator-edited content the second seed must not clobber.
        edited_report = (
            "---\n"
            "arm: control\n"
            "date: 2026-06-13\n"
            "run_id: r-final\n"
            "git_sha: deadbee\n"
            "started_at: 2026-06-13T00:00:00Z\n"
            "ended_at: 2026-06-13T01:00:00Z\n"
            "---\n"
            "Operator notes.\n"
        )
        (arm_dir / "report.md").write_text(
            edited_report, encoding="utf-8", newline=""
        )
        edited_telemetry = (
            '{"event_type":"StoryStarted","ts":"2026-06-13T00:00:00Z"}\n'
        )
        (arm_dir / "telemetry.jsonl").write_text(
            edited_telemetry, encoding="utf-8", newline=""
        )
        self.assertEqual(seed_main(args), 0)
        self.assertEqual(
            (arm_dir / "report.md").read_text(encoding="utf-8"),
            edited_report,
        )
        self.assertEqual(
            (arm_dir / "telemetry.jsonl").read_text(encoding="utf-8"),
            edited_telemetry,
        )
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format.SeedSoakDirTests.test_seed_is_idempotent -v`
Expected: PASS — `_seed_if_absent` already enforces this; the test pins the behavior so it cannot regress.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin seed idempotence against operator-edited content"
```

---

## Task 6: Verifier — reject unresolved `[ABCD]` placeholder tokens (REQ-12)

**Files:**
- Modify: `scripts/verify_soak_format.py`
- Create: `tests/test_soak_format_extra.py` (split so `test_soak_format.py` stays under 500 LOC)

- [ ] **Step 1: Create `tests/test_soak_format_extra.py` with the failing test**

```python
# tests/test_soak_format_extra.py
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.test_soak_format import _write_minimal_arm  # noqa: E402

# REQ-12: literal tokens kept out of CONTRIBUTING.md and verifier source
# (which is grep-gated in CI) and live only inside this test module.
_PLACEHOLDER_TOKEN = "[" + "T" + "O" + "D" + "O" + "]"
_FIXME_TOKEN = "[" + "F" + "I" + "X" + "M" + "]"


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
                f"Body with {_PLACEHOLDER_TOKEN} left in it.\n",
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
                '{"arm":"control","seed":1,"model":"m","concurrency":1,'
                f'"notes":"{_FIXME_TOKEN}"' + "}",
                encoding="utf-8",
                newline="",
            )
            self.assertEqual(main([str(root)]), 1)

    def test_markdown_link_is_not_a_placeholder(self) -> None:
        # Numeric brackets like [1234] are footnote-style references and must
        # not be flagged; only uppercase four-letter bracketed tokens are.
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

Note: `_write_minimal_arm` already exists in `tests/test_soak_format.py` from Task 1; re-using it here keeps both modules small.

- [ ] **Step 2: Run to verify the placeholder tests fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.PlaceholderTokenTests -v`
Expected: `test_placeholder_in_report_md_fails` and `test_placeholder_in_config_json_fails` FAIL (verifier currently does not check); `test_markdown_link_is_not_a_placeholder` PASSes vacuously.

- [ ] **Step 3: Add the placeholder check to the verifier**

In `scripts/verify_soak_format.py`, add near the top constants:

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

Then in `_validate_report_md` (end of function, before `return findings`) and in `_validate_config_json` (end, before `return findings`):

```python
findings.extend(_check_placeholders(path, text))  # report.md uses normalized text
findings.extend(_check_placeholders(path, raw))   # config.json uses raw read
```

The literal tokens never appear in the verifier source — the regex `\[[A-Z]{4}\]` matches them at runtime, which keeps the verifier itself clean for the CONTRIBUTING grep gate (Task 9).

- [ ] **Step 4: Run all placeholder tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.PlaceholderTokenTests -v`
Expected: all three pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_soak_format.py tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m13): reject unresolved four-letter placeholder tokens"
```

---

## Task 7: Pin LF line endings on seeded files (NFR portability)

**Files:**
- Modify: `tests/test_soak_format_extra.py` (add `SeedSoakDirExtraTests`)

The seed already uses explicit `\n` joins (Task 4); this task pins it with a test so a future refactor can't silently regress.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_soak_format_extra.py`:

```python
class SeedSoakDirExtraTests(unittest.TestCase):
    """Coverage and NFR pin-down tests for seed_soak_dir; supplements REQ-13."""

    def test_seed_missing_required_arg_returns_two(self) -> None:
        from scripts.seed_soak_dir import main as seed_main

        self.assertEqual(seed_main([]), 2)

    def test_seed_writes_lf_line_endings(self) -> None:
        # NFR line-ending portability: report.md bytes must be LF on all OSes.
        from scripts.seed_soak_dir import main as seed_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "soak"
            self.assertEqual(
                seed_main(
                    ["--date", "2026-06-13", "--arm", "control", "--root", str(root)]
                ),
                0,
            )
            arm_dir = root / "2026-06-13" / "control"
            report_bytes = (arm_dir / "report.md").read_bytes()
            self.assertNotIn(b"\r\n", report_bytes)
            self.assertIn(b"\n", report_bytes)

    def test_seed_uses_story_automator_helpers_when_importable(self) -> None:
        # REQ-09: prefer story_automator helpers; only fall back on ImportError.
        import scripts.seed_soak_dir as seed_module
        from story_automator.core.common import iso_now as expected_iso_now

        self.assertIs(seed_module.iso_now, expected_iso_now)
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.SeedSoakDirExtraTests -v`
Expected: PASS — the seed already uses `write_atomic` + explicit `\n` joins, and is imported with `story_automator.core.common.iso_now` when `PYTHONPATH` includes `skills/bmad-story-automator/src`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin LF line endings + helper preference in seed"
```

---

## Task 8: CONTRIBUTING.md — "Soak archive" section (REQ-11)

**Files:**
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Append the new section above "Reporting Bugs"**

Insert before the existing `## Reporting Bugs` heading:

```markdown
## Soak archive

The repository preserves paired A/B soak runs under `_bmad-output/soak/` for
downstream calibration and review. The canonical layout is:

\`\`\`
_bmad-output/soak/<YYYY-MM-DD>/<arm>/
  telemetry.jsonl  # M02 emitter output, line-delimited JSON events
  report.md        # human-readable narrative, YAML frontmatter required
  config.json      # arm parameters (arm, seed, model, concurrency, notes)
\`\`\`

- `<YYYY-MM-DD>` is an ISO-8601 calendar date that parses via
  `datetime.date.fromisoformat`.
- `<arm>` is a non-empty slug matching the regular expression
  `[a-z0-9._-]+`; the verifier rejects anything else.
- `telemetry.jsonl` is the immutable per-run event log; every non-empty line
  must be a JSON object with at least `event_type` (string) and `ts` (string).
- `report.md` must begin with a YAML frontmatter block delimited by `---`
  lines containing the keys `arm`, `date`, `run_id`, `git_sha`, `started_at`,
  and `ended_at`. `started_at` must be ISO-8601; `ended_at` may temporarily
  be the literal `pending` between seeding and finalization.
- `config.json` is a JSON object containing the keys `arm` (str), `seed`
  (int), `model` (str), `concurrency` (int), and `notes` (str). The
  top-level `arm` value must equal the directory name.

### Commands

- Seed a new arm directory:

  \`\`\`
  python scripts/seed_soak_dir.py --date 2026-06-13 --arm control
  \`\`\`

  Re-running the command against an existing populated arm is a no-op: the
  seeder never overwrites a non-empty file.

- Verify an archive:

  \`\`\`
  python scripts/verify_soak_format.py _bmad-output/soak/
  \`\`\`

  Exit code is 0 on success, 1 on validation failure (one finding per line on
  stderr, sorted by path), and 2 on usage error.

### Placeholder tokens

Soak archives committed to this repository must not contain unresolved
uppercase four-letter bracketed placeholder tokens (the conventional review
markers of the form `\[[A-Z]{4}\]`) inside `report.md` or `config.json`.
`scripts/verify_soak_format.py` flags any such occurrence as a validation
failure, and CI additionally greps `CONTRIBUTING.md` to keep this guidance
itself free of the same markers.
```

**Important formatting note:** the triple-backticks above are shown as `\`\`\`` (with a leading backslash) only because this plan file is itself markdown — in the actual CONTRIBUTING.md you write **literal triple-backticks**, with no backslash, exactly as you would in any markdown code fence. Do not let a backslash leak into the committed file.

The single literal `\[[A-Z]{4}\]` regex is the only `[` `[A-Z]{4}` `]` pattern in CONTRIBUTING.md; verifier `PLACEHOLDER_RE` matches the four uppercase letters between brackets, so a regex containing `[A-Z]` does not match itself (because `A-Z` is three chars, not four). This keeps the grep gate green.

- [ ] **Step 2: Confirm the CONTRIBUTING grep gate would pass**

Run: `grep -nE '\[[A-Z]{4}\]' CONTRIBUTING.md`
Expected: exit 1 (no matches). If grep prints any line, edit it out — the only literal that should appear is the regex notation `\[[A-Z]{4}\]`, which contains three letters between brackets and does not match itself.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m13): document soak archive layout and seed/verify commands"
```

---

## Task 9: CONTRIBUTING grep-gate test (REQ-12 / Quality gate)

**Files:**
- Modify: `tests/test_soak_format_extra.py`

- [ ] **Step 1: Add the failing test (will pass given Task 8)**

Append to `tests/test_soak_format_extra.py`:

```python
import re as stdlib_re  # placed at top with other imports


class ContributingGrepGateTests(unittest.TestCase):
    """Mirrors the CI grep gate from the M13 quality gates."""

    def test_contributing_md_has_no_placeholder_tokens(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        text = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIsNone(
            stdlib_re.search(r"\[[A-Z]{4}\]", text),
            "CONTRIBUTING.md contains an unresolved four-letter placeholder token",
        )
```

(Move `import re as stdlib_re` to the top of the file with the other imports if not already there.)

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.ContributingGrepGateTests -v`
Expected: PASS — Task 8 left no four-letter bracketed tokens.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): mirror CONTRIBUTING placeholder grep gate"
```

---

## Task 10: CI gates — placeholder grep + seed→verify self-verification

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Insert the two new steps before `Run Python tests`**

```yaml
      - name: M13 placeholder gate (CONTRIBUTING.md)
        shell: bash
        run: |
          if grep -nE '\[[A-Z]{4}\]' CONTRIBUTING.md; then
            echo "CONTRIBUTING.md contains an unresolved four-letter placeholder token" >&2
            exit 1
          fi

      - name: M13 self-verification (seed + verify)
        shell: bash
        run: |
          ROOT="${RUNNER_TEMP:-/tmp}/m13-gate"
          rm -rf "$ROOT"
          PYTHONPATH=skills/bmad-story-automator/src \
            python scripts/seed_soak_dir.py --date 2026-06-13 --arm gate-check --root "$ROOT"
          python scripts/verify_soak_format.py "$ROOT"
```

Why `PYTHONPATH=skills/bmad-story-automator/src` on the seed but not the verifier: per REQ-07 the verifier must not import `story_automator`; per REQ-09 the seed must prefer those helpers when available. Without the PYTHONPATH the seed would fall back to inlined helpers and the test in Task 7 (`test_seed_uses_story_automator_helpers_when_importable`) would still pass locally but CI would silently exercise only the fallback path. Setting it on the seed step gives the same path that contributors use locally; leaving it off the verifier step also proves the verifier is fully stdlib.

- [ ] **Step 2: Local rehearsal of the CI commands**

Run (Windows git-bash):
```bash
ROOT="$(mktemp -d)/m13-gate"
PYTHONPATH=skills/bmad-story-automator/src python scripts/seed_soak_dir.py --date 2026-06-13 --arm gate-check --root "$ROOT"
python scripts/verify_soak_format.py "$ROOT"
echo "exit=$?"
```
Expected: `exit=0` and the directory tree `$ROOT/2026-06-13/gate-check/{telemetry.jsonl,config.json,report.md}` exists.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit --trailer "Generated-By: claude-opus-4-7" -m "ci(m13): add placeholder grep + seed/verify self-check gates"
```

---

## Task 11: Stdlib-import allowlist test (NFR — dependency floor)

**Files:**
- Modify: `tests/test_soak_format_extra.py`

REQ-07 already requires the verifier to import only `json`, `pathlib`, `datetime`, `argparse`, `sys`, `re` (plus `__future__`). The Quality gates section restates it as a CI grep. Pin it as a test so it fails fast under `npm run test:python`.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_soak_format_extra.py`:

```python
class ImportAllowlistTests(unittest.TestCase):
    def test_verifier_only_imports_allowlisted_stdlib(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "verify_soak_format.py"
        text = path.read_text(encoding="utf-8")
        allowed = {"__future__", "json", "pathlib", "datetime", "argparse", "sys", "re"}
        import_lines = [
            ln
            for ln in text.split("\n")
            if ln.startswith("import ") or ln.startswith("from ")
        ]
        for line in import_lines:
            match = stdlib_re.match(
                r"^(?:from|import)\s+([A-Za-z_][A-Za-z_0-9.]*)", line
            )
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

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.ImportAllowlistTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin verifier stdlib-only import allowlist"
```

---

## Task 12: CRLF/LF read-portability tests

**Files:**
- Modify: `tests/test_soak_format_extra.py`

NFR Line-ending portability: the verifier already does `text.replace("\r\n", "\n")`; pin the behavior so a refactor to `splitlines()` (which would mis-handle some corner cases) cannot pass review.

- [ ] **Step 1: Add the failing test**

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
            (arm_dir / "report.md").write_text(
                crlf_report, encoding="utf-8", newline=""
            )
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

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.LineEndingTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin CRLF/LF portability in verifier reads"
```

---

## Task 13: Deterministic sorted findings (NFR Determinism)

**Files:**
- Modify: `tests/test_soak_format_extra.py`

- [ ] **Step 1: Add the failing test**

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
                # All three required files missing → three findings per arm.
            findings = self._run_capture(root)
            self.assertEqual(findings, sorted(findings))
```

Move the `import contextlib` and `import io` to the top of the file with the other imports.

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format_extra.DeterministicOutputTests -v`
Expected: PASS — the verifier already does `for line in sorted(findings):` in `main`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soak_format_extra.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m13): pin deterministic sorted finding output"
```

---

## Task 14: Quality gates pass — ruff + coverage + line counts

**Files:** none modified; this task validates the whole milestone.

- [ ] **Step 1: ruff check + format**

Run:
```bash
python -m ruff check scripts/verify_soak_format.py scripts/seed_soak_dir.py tests/test_soak_format.py tests/test_soak_format_extra.py
python -m ruff format --check scripts/verify_soak_format.py scripts/seed_soak_dir.py tests/test_soak_format.py tests/test_soak_format_extra.py
```
Expected: both exit 0 with no findings.

- [ ] **Step 2: Full test run**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_soak_format tests.test_soak_format_extra -v`
Expected: all tests pass, zero failures, zero errors.

- [ ] **Step 3: Coverage ≥ 85% over both scripts**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=scripts -m unittest tests.test_soak_format tests.test_soak_format_extra
python -m coverage report --include="scripts/*" -m --fail-under=85
```

Use `--source=scripts` (package/directory) rather than comma-separated file paths — `coverage --source` accepts a directory but not always a list of files. `--include="scripts/*"` filters the report to just the two scripts so `__init__.py` does not skew the number.

Expected: aggregate ≥ 85%. With the helpers importable on CI's `PYTHONPATH`, `seed_soak_dir.py` shows lines 17–49 (the `except ImportError` fallback block) as uncovered; the aggregate still passes (~86%) because `verify_soak_format.py` is ~95%. If a future change pushes the aggregate below 85%, add the fallback test below before splitting helpers into a separate module:

```python
# tests/test_soak_format_extra.py — append to SeedSoakDirExtraTests
def test_seed_fallback_path_when_story_automator_missing(self) -> None:
    # REQ-09 fallback: force ImportError on story_automator.core.common
    # and confirm the inlined stdlib helpers still produce a valid arm.
    import importlib
    import sys as _sys

    saved = {
        name: mod
        for name, mod in list(_sys.modules.items())
        if name == "story_automator" or name.startswith("story_automator.")
    }
    # Sentinel value None makes a subsequent `import` raise ImportError.
    for name in saved:
        _sys.modules[name] = None
    _sys.modules.pop("scripts.seed_soak_dir", None)
    try:
        seed_module = importlib.import_module("scripts.seed_soak_dir")
        with tempfile.TemporaryDirectory() as tmp:
            rc = seed_module.main(
                ["--date", "2026-06-13", "--arm", "fallback", "--root", tmp]
            )
            self.assertEqual(rc, 0)
            arm_dir = Path(tmp) / "2026-06-13" / "fallback"
            self.assertTrue((arm_dir / "report.md").is_file())
    finally:
        for name, mod in saved.items():
            _sys.modules[name] = mod
        _sys.modules.pop("scripts.seed_soak_dir", None)
        importlib.import_module("scripts.seed_soak_dir")
```

- [ ] **Step 4: Module size + import-allowlist grep gates**

Run (git-bash):
```bash
wc -l scripts/verify_soak_format.py scripts/seed_soak_dir.py tests/test_soak_format.py tests/test_soak_format_extra.py
grep -E "^(from|import) " scripts/verify_soak_format.py
```
Expected: every file ≤ 500 LOC; verifier imports only `__future__`, `json`, `pathlib`, `datetime`, `argparse`, `sys`, `re`.

- [ ] **Step 5: End-to-end self-verification**

Run (mirrors the CI step from Task 10):
```bash
ROOT="$(mktemp -d)/m13-gate"
PYTHONPATH=skills/bmad-story-automator/src python scripts/seed_soak_dir.py --date 2026-06-13 --arm gate-check --root "$ROOT"
python scripts/verify_soak_format.py "$ROOT"
```
Expected: both commands exit 0; the resulting `report.md` contains `ended_at: pending` (accepted), `config.json` decodes as the M13 schema, and `telemetry.jsonl` is empty (allowed by the verifier).

- [ ] **Step 6: Stage and verify the final state**

```bash
git status   # working tree clean — all M2 changes already committed
git log --oneline -15
```
Expected: clean tree; the M2 commit chain visible.

No commit for this task — quality-gate verification only.

---

## Self-Review Checklist

- **REQ-08** Seed CLI with `--date`, `--arm`, `--root` and three stub files: Task 2 (scaffold) + Task 4 (file emission).
- **REQ-09** Prefer `story_automator.core.common` helpers, fall back to stdlib, never clobber non-empty files: Task 3 (imports) + Task 5 (idempotence test) + Task 7 (helper-preference pin-down).
- **REQ-10** `started_at` from `iso_now()`, `ended_at: pending`: Task 1 (verifier carve-out) + Task 4 (frontmatter writer).
- **REQ-11** CONTRIBUTING "Soak archive" section: Task 8.
- **REQ-12** Forbid four-letter bracketed placeholder tokens in archives and verifier-flag them: Task 6 (verifier) + Task 8 (docs) + Task 9 (grep-gate test) + Task 10 (CI gate).
- **REQ-13** Test coverage (a–f): Task 1 (a, b, c via existing M1 tests + the pending sentinel), Tasks 2, 4, 5 (e, f); Task 6 covers placeholder rejection beyond REQ-13.
- **REQ-14** `from __future__ import annotations`, `if __name__ == "__main__": raise SystemExit(main())`, PEP 604 unions: Task 2 (scaffold) covers all three.
- **NFR cross-platform** `pathlib.Path`, CRLF/LF read-equivalence: Task 12.
- **NFR dependency floor** stdlib-only verifier: Task 11.
- **NFR module size** ≤ 500 LOC: Task 14 step 4; split into `test_soak_format_extra.py` (Task 6) preempts this.
- **NFR line-ending portability** LF output: Task 7 step 1 (`test_seed_writes_lf_line_endings`).
- **NFR typing posture** `from __future__ import annotations`, PEP 604: Task 2 scaffold + Task 3 fallback block.
- **NFR determinism** sorted findings: Task 13.
- **Quality gates** ruff, coverage, line count, grep gate, self-verification: Task 14.

No placeholders. Method names (`main`, `_write_minimal_arm`, `_seed_if_absent`, `_check_placeholders`) are consistent across tasks.
