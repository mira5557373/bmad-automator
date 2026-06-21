from __future__ import annotations

"""TEA (Test Evidence Artifact) emitters.

Deterministic writers for the two M30 artifacts:
    * trace summary  — coverage of requirements by test level
    * gate decision  — pass/concerns/fail/waived verdict + per-category verdicts

Both writers emit canonical JSON (sorted keys) via the atomic-write helper in
``core.common`` so a re-emit on identical inputs produces a byte-identical file.
"""

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import write_atomic

VALID_VERDICTS = frozenset({"PASS", "CONCERNS", "FAIL", "WAIVED"})
VALID_CATEGORY_VERDICTS = frozenset({"PASS", "CONCERNS", "FAIL", "NA"})

DEFAULT_SCHEMA_VERSION = "0.1.0"


def _emit(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    write_atomic(target, body)
    return target


def write_trace_summary(
    path: str | Path,
    *,
    story_key: str,
    requirements: Sequence[Mapping[str, Any]],
    coverage_by_level: Mapping[str, Any],
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> Path:
    """Write a trace-summary artifact.

    Schema keys:
        schema_version, story_key, requirements (list of
        ``{id, covered, level}``), coverage_by_level.
    """

    payload = {
        "schema_version": schema_version,
        "story_key": story_key,
        "requirements": [dict(item) for item in requirements],
        "coverage_by_level": dict(coverage_by_level),
    }
    return _emit(path, payload)


def write_gate_decision(
    path: str | Path,
    *,
    story_key: str,
    verdict: str,
    categories: Mapping[str, str],
    commit_sha: str,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> Path:
    """Write a gate-decision artifact.

    Schema keys: schema_version, story_key, verdict, categories, commit_sha.
    ``verdict`` must be one of :data:`VALID_VERDICTS`; each value in
    ``categories`` must be one of :data:`VALID_CATEGORY_VERDICTS`.
    """

    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"invalid gate verdict {verdict!r}; expected one of {sorted(VALID_VERDICTS)}"
        )
    for category, value in categories.items():
        if value not in VALID_CATEGORY_VERDICTS:
            raise ValueError(
                f"invalid category verdict {value!r} for {category!r}; "
                f"expected one of {sorted(VALID_CATEGORY_VERDICTS)}"
            )
    payload = {
        "schema_version": schema_version,
        "story_key": story_key,
        "verdict": verdict,
        "categories": dict(categories),
        "commit_sha": commit_sha,
    }
    return _emit(path, payload)


__all__ = [
    "VALID_VERDICTS",
    "VALID_CATEGORY_VERDICTS",
    "DEFAULT_SCHEMA_VERSION",
    "write_trace_summary",
    "write_gate_decision",
]
