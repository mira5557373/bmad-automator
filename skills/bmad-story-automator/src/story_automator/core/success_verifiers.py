from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .artifact_paths import implementation_artifacts_dir, implementation_artifacts_glob, resolve_artifact_glob
from .frontmatter import find_frontmatter_value_case
from .runtime_policy import PolicyError, load_runtime_policy, step_contract
from .sprint import sprint_status_epic, sprint_status_get
from .story_keys import normalize_story_key
from .utils import read_text

ALLOWED_REVIEW_CONTRACT_KEYS = {"blockingSeverity", "doneValues", "inProgressValues", "sourceOrder", "syncSprintStatus"}
ALLOWED_REVIEW_SOURCES = {"sprint-status.yaml", "story-file"}
DEFAULT_REVIEW_CONTRACT = {
    "blockingSeverity": ["critical"],
    "doneValues": ["done"],
    "inProgressValues": ["in-progress", "in_progress", "review", "qa"],
    "sourceOrder": ["sprint-status.yaml", "story-file"],
    "syncSprintStatus": True,
}


def resolve_success_contract(project_root: str, step: str, *, state_file: str | Path | None = None) -> dict[str, Any]:
    policy = load_runtime_policy(project_root, state_file=state_file, resolve_assets=False)
    success = step_contract(policy, step).get("success") or {}
    if not isinstance(success, dict):
        raise PolicyError(f"invalid success contract for {step}")
    return success


def run_success_verifier(
    name: str,
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    verifier = VERIFIERS.get(name)
    if verifier is None:
        raise PolicyError(f"unknown success verifier: {name}")
    return verifier(project_root=project_root, story_key=story_key, output_file=output_file, contract=contract or {})


def session_exit(
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"verified": True, "source": "session_exit"}
    if story_key:
        payload["story"] = story_key
    if output_file:
        payload["outputFile"] = output_file
    return payload


def create_story_artifact(
    *,
    project_root: str,
    story_key: str,
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    norm = normalize_story_key(project_root, story_key)
    if norm is None:
        return {"verified": False, "reason": "could_not_normalize_key", "input": story_key}
    config = _success_config(contract)
    raw_glob = str(config.get("glob") or implementation_artifacts_glob(project_root, "{story_prefix}-*.md"))
    expected = _parse_int(config.get("expectedMatches", 1), "success.config.expectedMatches", minimum=0)
    pattern = _format_story_pattern(raw_glob, norm)
    try:
        root, safe_pattern = resolve_artifact_glob(project_root, pattern)
    except ValueError as exc:
        raise PolicyError(str(exc)) from exc
    matches = sorted(root.glob(safe_pattern))
    if _is_explicit_full_key(story_key, norm):
        matches = [match for match in matches if match.stem == norm.key]
    payload: dict[str, object] = {
        "verified": len(matches) == expected,
        "story": norm.key,
        "source": "artifact_glob",
        "pattern": safe_pattern,
        "expectedMatches": expected,
        "actualMatches": len(matches),
        "matches": [str(match) for match in matches],
    }
    if not bool(payload["verified"]):
        payload["reason"] = "unexpected_story_artifact_count"
    return payload


def review_completion(
    *,
    project_root: str,
    story_key: str,
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    norm = normalize_story_key(project_root, story_key)
    if norm is None:
        return {"verified": False, "reason": "could_not_normalize_key", "input": story_key}
    review_contract = _load_review_contract(project_root, contract or {})
    done_values = {value.lower() for value in review_contract["doneValues"]}
    sprint = sprint_status_get(project_root, story_key)
    selected_story = _selected_review_story(sprint.story, norm) if sprint.found else norm.key
    story_file = _story_artifact_path(
        project_root,
        norm.prefix,
        selected_story,
        allow_prefix_fallback=False,
    )
    story_status = find_frontmatter_value_case(story_file, "Status") if story_file else ""
    for source in review_contract["sourceOrder"]:
        if source == "sprint-status.yaml" and sprint.status.lower() in done_values:
            return {
                "verified": True,
                "story": selected_story,
                "sprint_status": sprint.status,
                "story_file_status": story_status or "unknown",
                "source": "sprint-status.yaml",
            }
        if source == "story-file" and story_status.lower() in done_values:
            payload: dict[str, object] = {
                "verified": True,
                "story": selected_story,
                "sprint_status": sprint.status,
                "story_file_status": story_status,
                "source": "story-file",
            }
            if review_contract["syncSprintStatus"] and sprint.status.lower() not in done_values:
                payload["note"] = "sprint_status_not_updated"
            return payload
    return {
        "verified": False,
        "story": selected_story,
        "sprint_status": sprint.status,
        "story_file_status": story_status or "unknown",
        "reason": "workflow_not_complete",
    }


def epic_complete(
    *,
    project_root: str,
    story_key: str,
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    epic = _epic_identifier(project_root, story_key)
    if not epic:
        return {"verified": False, "reason": "could_not_normalize_key", "input": story_key}
    norm = normalize_story_key(project_root, story_key)
    if norm is not None and _is_explicit_full_key(story_key, norm):
        sprint = sprint_status_get(project_root, story_key)
        if not sprint.found or not sprint.done:
            return {
                "verified": False,
                "epic": epic,
                "story": story_key,
                "sprint_status": sprint.status,
                "source": "sprint-status.yaml",
                "reason": "story_not_done",
            }
    stories, done = sprint_status_epic(project_root, epic)
    if not stories:
        return {"verified": False, "epic": epic, "reason": "no_stories_found", "source": "sprint-status.yaml"}
    return {
        "verified": done == len(stories),
        "epic": epic,
        "story": story_key,
        "totalStories": len(stories),
        "doneStories": done,
        "source": "sprint-status.yaml",
        **({} if done == len(stories) else {"reason": "epic_incomplete"}),
    }


def _success_config(contract: dict[str, Any] | None) -> dict[str, Any]:
    config = (contract or {}).get("config") or {}
    if not isinstance(config, dict):
        raise PolicyError("success.config must be an object")
    return config


def _format_story_pattern(pattern: str, story) -> str:
    return (
        pattern.replace("{story_prefix}", story.prefix)
        .replace("{story_id}", story.id)
        .replace("{story_key}", story.key)
    )


def _story_artifact_path(
    project_root: str,
    story_prefix: str,
    preferred_story: str = "",
    *,
    allow_prefix_fallback: bool = True,
) -> Path | None:
    artifacts = implementation_artifacts_dir(project_root)
    # preferred_story originates from sprint-status.yaml keys, which are not
    # trusted. Only accept a bare filename component so a crafted key like
    # "../../etc/passwd" cannot escape the implementation-artifacts dir; any
    # separator/".."-bearing value falls through to the safe prefix glob.
    if preferred_story and Path(preferred_story).name == preferred_story and preferred_story not in {".", ".."}:
        preferred = artifacts / f"{preferred_story}.md"
        if preferred.is_file():
            return preferred
        if not allow_prefix_fallback:
            return None
    matches = sorted(artifacts.glob(f"{story_prefix}-*.md"))
    return matches[0] if matches else None


def _selected_review_story(sprint_story: str, norm) -> str:
    if sprint_story in {norm.id, norm.prefix}:
        return norm.key
    return sprint_story

def _load_review_contract(project_root: str, contract: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_REVIEW_CONTRACT)
    contract_path = str(contract.get("contractPath") or "").strip()
    if contract_path:
        path = Path(contract_path)
        if not path.is_absolute():
            path = Path(project_root) / path
        try:
            payload = json.loads(read_text(path))
        except json.JSONDecodeError as exc:
            raise PolicyError(f"review contract json invalid: {path}") from exc
        if not isinstance(payload, dict):
            raise PolicyError(f"review contract must be an object: {path}")
        merged.update(payload)
    inline = _inline_review_contract(contract)
    merged.update(inline)
    _validate_review_contract(merged)
    return _sanitize_review_contract(merged)


def _inline_review_contract(contract: dict[str, Any]) -> dict[str, Any]:
    inline: dict[str, Any] = {}
    config = contract.get("config")
    if isinstance(config, dict):
        for key in ALLOWED_REVIEW_CONTRACT_KEYS:
            if key in config:
                inline[key] = config[key]
    for key in ALLOWED_REVIEW_CONTRACT_KEYS:
        if key in contract:
            inline[key] = contract[key]
    return inline


def _validate_review_contract(contract: dict[str, Any]) -> None:
    unknown_keys = sorted(set(contract) - ALLOWED_REVIEW_CONTRACT_KEYS)
    if unknown_keys:
        raise PolicyError(f"unknown review contract keys: {', '.join(unknown_keys)}")
    for key in ("blockingSeverity", "doneValues", "inProgressValues", "sourceOrder"):
        values = contract.get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise PolicyError(f"review contract {key} must be a string array")
    if not isinstance(contract.get("syncSprintStatus"), bool):
        raise PolicyError("review contract syncSprintStatus must be a boolean")
    if not _sanitize_string_list(contract["doneValues"]):
        raise PolicyError("review contract doneValues must not be empty")
    source_order = _sanitize_string_list(contract["sourceOrder"])
    if not source_order:
        raise PolicyError("review contract sourceOrder must not be empty")
    invalid_sources = sorted({value for value in source_order if value not in ALLOWED_REVIEW_SOURCES})
    if invalid_sources:
        raise PolicyError(f"review contract sourceOrder contains unknown sources: {', '.join(invalid_sources)}")


def _parse_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise PolicyError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{field} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise PolicyError(f"{field} must be >= {minimum}")
    return parsed


def _epic_identifier(project_root: str, story_key: str) -> str:
    if re.fullmatch(r"\d+", story_key):
        return story_key
    norm = normalize_story_key(project_root, story_key)
    if norm is not None:
        return norm.id.split(".", 1)[0]
    if re.fullmatch(r"[A-Za-z][\w-]*", story_key) and sprint_status_epic(project_root, story_key)[0]:
        return story_key
    return ""


def _is_explicit_full_key(value: str, norm) -> bool:
    return value == norm.key and value not in {norm.id, norm.prefix}


def _sanitize_review_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "blockingSeverity": _sanitize_string_list(contract["blockingSeverity"]),
        "doneValues": _sanitize_string_list(contract["doneValues"]),
        "inProgressValues": _sanitize_string_list(contract["inProgressValues"]),
        "sourceOrder": _sanitize_string_list(contract["sourceOrder"]),
        "syncSprintStatus": contract["syncSprintStatus"],
    }


def _sanitize_string_list(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def production_ready_gate(
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    """§9.1+§9.2: terminal verifier for review→done.

    On FAIL, drives the BMAD review_continuation loop (WIRING-001/-002):
    resolves the dev-story path from story_key, calls route_gate_verdict
    which persists [AI-Review] tasks into the story file's Tasks section
    (honoring edit-authorization). The verifier still returns
    verified=False so the orchestrator's existing review-cycle re-runs
    bmad-dev-story — which then picks up the new [AI-Review] tasks.
    """
    from .artifact_paths import resolve_story_artifact_path
    from .evidence_io import load_gate_file
    from .gate_orchestrator import route_gate_verdict
    from .gate_schema import GateSchemaError
    config = _success_config(contract)
    gate_id = str(config.get("gate_id") or "").strip()
    if not gate_id:
        return {"verified": False, "reason": "gate_file_absent", "source": "production_ready_gate"}
    try:
        gate_file = load_gate_file(project_root, gate_id)
    except (GateSchemaError, FileNotFoundError):
        return {"verified": False, "reason": "gate_file_absent", "source": "production_ready_gate"}
    overall = gate_file.get("overall", "FAIL")
    if overall == "FAIL":
        # WIRING: persist [AI-Review] tasks into the story file so the
        # next bmad-dev-story cycle picks them up. Best-effort — the
        # verifier still returns verified=False either way; the loud
        # state lives in remediation_descriptor for the orchestrator
        # and operator to inspect.
        remediation_descriptor: dict[str, Any] | None = None
        story_path = (
            resolve_story_artifact_path(project_root, story_key)
            if story_key else None
        )
        remediation_cycle = int(config.get("remediation_cycle") or 0)
        max_cycles = int(config.get("max_cycles") or 3)
        has_unmitigated_risk_9 = bool(config.get("has_unmitigated_risk_9") or False)
        try:
            remediation_descriptor = route_gate_verdict(
                project_root,
                gate_file,
                story_key=story_key,
                remediation_cycle=remediation_cycle,
                max_cycles=max_cycles,
                has_unmitigated_risk_9=has_unmitigated_risk_9,
                story_path=story_path,
            )
        except Exception as exc:  # noqa: BLE001 — verifier must not crash the orchestrator
            remediation_descriptor = {
                "action": "remediate",
                "tasks_persisted": False,
                "persist_error": str(exc),
            }
        payload_fail: dict[str, object] = {
            "verified": False,
            "reason": "gate_verdict_fail",
            "overall": overall,
            "source": "production_ready_gate",
            "gate_id": gate_id,
            "story": story_key,
        }
        if remediation_descriptor is not None:
            payload_fail["remediation"] = remediation_descriptor
        return payload_fail
    payload: dict[str, object] = {
        "verified": True,
        "overall": overall,
        "source": "production_ready_gate",
        "gate_id": gate_id,
        "story": story_key,
    }
    if overall == "CONCERNS":
        failing = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        payload["mitigation_debt"] = failing
    return payload


def readiness_gate(
    *,
    project_root: str,
    story_key: str = "",
    output_file: str = "",
    contract: dict[str, Any] | None = None,
) -> dict[str, object]:
    from .readiness_gate import load_readiness_result
    result = load_readiness_result(project_root, story_key)
    if result is None:
        return {
            "verified": False,
            "reason": "readiness_not_checked",
            "source": "readiness_gate",
        }
    verdict = result.get("verdict", "")
    if verdict == "READY":
        return {
            "verified": True,
            "verdict": verdict,
            "priority": result.get("priority", ""),
            "source": "readiness_gate",
        }
    if verdict == "BLOCKED":
        return {
            "verified": False,
            "reason": "readiness_blocked",
            "verdict": verdict,
            "blockers": result.get("blockers", []),
            "source": "readiness_gate",
        }
    return {
        "verified": False,
        "reason": f"readiness_{verdict.lower()}" if verdict else "readiness_unknown",
        "verdict": verdict,
        "source": "readiness_gate",
    }


VerifierFn = Callable[..., dict[str, object]]

VERIFIERS: dict[str, VerifierFn] = {
    "create_story_artifact": create_story_artifact,
    "session_exit": session_exit,
    "review_completion": review_completion,
    "epic_complete": epic_complete,
    "production_ready_gate": production_ready_gate,
    "readiness_gate": readiness_gate,
}
