from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_policy import PolicyError
from .success_verifiers import resolve_success_contract, review_completion


def verify_code_review_completion(
    project_root: str,
    story_key: str,
    *,
    success_contract: dict[str, Any] | None = None,
    state_file: str | Path | None = None,
) -> dict[str, object]:
    try:
        contract = resolve_success_contract(project_root, "review", state_file=state_file) if success_contract is None else success_contract
        return review_completion(project_root=project_root, story_key=story_key, contract=contract)
    except (OSError, ValueError, PolicyError) as exc:
        # OSError (covers FileNotFoundError/PermissionError/IsADirectoryError)
        # so an existing-but-unreadable story file or policy/override file
        # degrades to a controlled {verified: false} result instead of
        # crashing the helper with a traceback. Matches the OSError handling
        # in _verify_step and _verify_monitor_completion.
        return {"verified": False, "reason": "review_contract_invalid", "input": story_key, "error": str(exc)}
