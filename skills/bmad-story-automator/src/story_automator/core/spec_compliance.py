"""Layer 2 of the M06a trust-but-verify stack: spec compliance via `claude -p`.

This module exposes two frozen dataclasses (`ReqVerdict`,
`ComplianceReport`), one exception (`ComplianceError`), and one
entry-point function (`check_compliance`). `check_compliance` spawns
`claude -p` via `subprocess.run` (list args, never `shell=True`),
injects the spec text and diff text into the prompt as fenced code
blocks, and returns a `ComplianceReport` whose per-REQ verdict
classifies each requirement as `"implemented"`, `"missing"`, or
`"partial"`.

Layer 2 is intentionally decoupled from Layer 1 (`gap_validator.py`) and
Layer 3 (`feature_tester.py`): no cross-layer imports, no shared state,
no HTTP/MCP/API clients. The only external boundary is the single
subprocess invocation. The child process inherits a clean environment
overlay that pins `LANG=C.UTF-8` for deterministic locale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = [
    "ComplianceError",
    "ComplianceReport",
    "ReqVerdict",
    "check_compliance",
]

logger = logging.getLogger(__name__)


class ComplianceError(Exception):
    """Raised when `check_compliance` cannot return a meaningful report.

    Preconditions: caller supplies a single human-readable message.
    Postconditions: instance is a plain `Exception` carrying the message.
    Raises: nothing — this is the exception type itself.

    Raised by `check_compliance` when:
      - the `claude -p` subprocess exits non-zero
      - the subprocess times out (TimeoutExpired)
      - the subprocess stdout cannot be parsed as the expected JSON envelope

    The function MUST NOT silently downgrade a parse failure into a
    `"missing"` verdict — REQ-10 forbids that.
    """


@dataclass(frozen=True, kw_only=True)
class ReqVerdict:
    """Verdict for one REQ from the spec compared against the diff.

    Preconditions: `req_id` is a non-empty string (e.g. "REQ-07");
        `status` is exactly one of "implemented", "missing", "partial";
        `evidence` is a human-readable string (may be empty);
        `confidence` lies in `[0.0, 1.0]`. The dataclass itself does not
        enforce these constraints — `_parse_envelope` (Task 7) does so
        before constructing instances.
    Postconditions: instance is frozen; all four fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    req_id: str
    status: Literal["implemented", "missing", "partial"]
    evidence: str
    confidence: float


@dataclass(frozen=True, kw_only=True)
class ComplianceReport:
    """Aggregate report from `check_compliance`.

    Preconditions: `verdicts` is a list (possibly empty); `spec_path` is
        the string form of the spec file path (typically the resolved
        absolute path); `diff_sha` is the SHA-256 hex digest of the diff
        text passed to `check_compliance`; `model_invocation_ms` is a
        non-negative integer reported by the subprocess.
    Postconditions: instance is frozen. Note: `frozen=True` does not
        deep-freeze `verdicts` — callers must treat it as read-only.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    verdicts: list[ReqVerdict]
    spec_path: str
    diff_sha: str
    model_invocation_ms: int


_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"\{\{([A-Z]{4})\}\}")


def _escape_placeholders(spec_text: str) -> str:
    """Replace four-letter uppercase `{{XXXX}}` tokens with `{{ESC:XXXX}}`.

    REQ-11: unresolved four-letter placeholder tokens in the spec must
    be escaped so the subprocess does not treat them as template
    directives intended for human authoring.
    """
    return _PLACEHOLDER_RE.sub(r"{{ESC:\1}}", spec_text)


_PROMPT_HEADER: str = (
    "You are verifying spec compliance. Compare the diff against the listed "
    "REQ-NN requirements in the spec. Output ONLY a single raw JSON object — "
    "no markdown fences, no preamble, no trailing prose — of shape: "
    '{"verdicts": [{"req_id": "...", "status": "implemented|missing|partial", '
    '"evidence": "...", "confidence": 0.0-1.0}], "model_invocation_ms": <int>}.'
)


def _render_prompt(*, spec_text: str, diff_text: str) -> str:
    """Render the `claude -p` prompt with fenced code blocks.

    Preconditions: `spec_text` and `diff_text` are strings (may be empty).
    Postconditions: returned string contains the prompt header, a fenced
        `## Spec` block holding `_escape_placeholders(spec_text)`, and a
        fenced `## Diff` block holding `diff_text` verbatim.
    Raises: nothing.
    """
    safe_spec = _escape_placeholders(spec_text)
    return (
        f"{_PROMPT_HEADER}\n\n"
        f"## Spec\n\n```text\n{safe_spec}\n```\n\n"
        f"## Diff\n\n```text\n{diff_text}\n```\n"
    )


_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"implemented", "missing", "partial"},
)
_REQUIRED_VERDICT_KEYS: tuple[str, ...] = (
    "req_id",
    "status",
    "evidence",
    "confidence",
)


def _parse_envelope(payload: str) -> tuple[list[ReqVerdict], int]:
    """Parse the subprocess stdout into `(verdicts, model_invocation_ms)`.

    Preconditions: `payload` is the raw stdout from the subprocess.
    Postconditions: returns a tuple of `(list[ReqVerdict], int)` whose
        verdicts preserve the input order and whose integer is the
        non-negative `model_invocation_ms` field.
    Raises: `ComplianceError` (REQ-10) when the payload is not valid
        JSON, when the top-level value is not an object, when a required
        key is missing or wrongly typed, when `status` is outside the
        allowed set, or when `model_invocation_ms` is negative or
        non-integer. The function NEVER silently substitutes a
        "missing" verdict on a parse failure.
    """
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ComplianceError(f"subprocess output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ComplianceError("subprocess output must be a top-level JSON object")
    if "verdicts" not in data:
        raise ComplianceError("envelope missing required key 'verdicts'")
    if "model_invocation_ms" not in data:
        raise ComplianceError("envelope missing required key 'model_invocation_ms'")
    raw_verdicts = data["verdicts"]
    if not isinstance(raw_verdicts, list):
        raise ComplianceError("'verdicts' must be a JSON array")
    ms = data["model_invocation_ms"]
    # `bool` is a subclass of `int`; reject explicitly so `true` does
    # not silently parse as `1`.
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise ComplianceError(
            f"model_invocation_ms must be an integer, got {type(ms).__name__}"
        )
    if ms < 0:
        raise ComplianceError(f"model_invocation_ms must be non-negative, got {ms}")

    verdicts: list[ReqVerdict] = []
    for index, raw in enumerate(raw_verdicts):
        if not isinstance(raw, dict):
            raise ComplianceError(f"verdicts[{index}] must be a JSON object")
        for key in _REQUIRED_VERDICT_KEYS:
            if key not in raw:
                raise ComplianceError(f"verdicts[{index}] missing required key {key!r}")
        status = raw["status"]
        if status not in _ALLOWED_STATUSES:
            raise ComplianceError(
                f"verdicts[{index}].status must be one of "
                f"{sorted(_ALLOWED_STATUSES)!r}, got {status!r}"
            )
        confidence_raw = raw["confidence"]
        if isinstance(confidence_raw, bool) or not isinstance(
            confidence_raw,
            (int, float),
        ):
            raise ComplianceError(
                f"verdicts[{index}].confidence must be a number, got "
                f"{type(confidence_raw).__name__}"
            )
        verdicts.append(
            ReqVerdict(
                req_id=str(raw["req_id"]),
                status=status,
                evidence=str(raw["evidence"]),
                confidence=float(confidence_raw),
            )
        )
    return verdicts, ms


_DEFAULT_TIMEOUT_S: int = 120


def check_compliance(
    *,
    spec_path: Path,
    diff_text: str,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    claude_binary: str = "claude",
    cwd: Path | None = None,
) -> ComplianceReport:
    """Verify a candidate diff against the REQs declared in `spec_path`.

    Preconditions: `spec_path` must point to a readable UTF-8 file
        (typically a Markdown spec containing REQ-NN sections);
        `diff_text` is the candidate diff as a string; `timeout_s` is a
        positive integer; `claude_binary` is the executable name (or
        path) of the `claude` CLI; `cwd`, when provided, is an existing
        directory used as the subprocess working directory — otherwise
        the current working directory is used.
    Postconditions: returns a `ComplianceReport` whose `verdicts` reflect
        the model's classification of each REQ; `spec_path` is the
        resolved absolute path as a string; `diff_sha` is the SHA-256
        hex digest of `diff_text` encoded as UTF-8; `model_invocation_ms`
        is propagated verbatim from the subprocess envelope.
    Raises: `ComplianceError` (REQ-10) when the subprocess exits
        non-zero, when it times out, or when its stdout cannot be parsed
        as the JSON envelope `_parse_envelope` expects. This function
        NEVER silently downgrades a parse failure into a "missing"
        verdict — REQ-10 forbids that.
    """
    resolved_spec = spec_path.resolve()
    spec_text = resolved_spec.read_text(encoding="utf-8")
    prompt = _render_prompt(spec_text=spec_text, diff_text=diff_text)

    effective_cwd = cwd if cwd is not None else Path.cwd()
    child_env = {**os.environ, "LANG": "C.UTF-8"}

    try:
        completed = subprocess.run(
            [claude_binary, "-p"],
            input=prompt,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=str(effective_cwd),
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ComplianceError(
            f"`{claude_binary} -p` timed out after {timeout_s}s"
        ) from exc

    if completed.returncode != 0:
        raise ComplianceError(
            f"`{claude_binary} -p` exited {completed.returncode}: "
            f"{(completed.stderr or '').strip()[:500]}"
        )

    verdicts, ms = _parse_envelope(completed.stdout)
    diff_sha = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    return ComplianceReport(
        verdicts=verdicts,
        spec_path=str(resolved_spec),
        diff_sha=diff_sha,
        model_invocation_ms=ms,
    )
