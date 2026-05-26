from __future__ import annotations

from pathlib import Path

from story_automator.core.diagnostics import redact_actual
from story_automator.core.runtime_policy import PolicyError
from story_automator.core.success_verifiers import resolve_success_contract, run_success_verifier
from story_automator.core.utils import print_json


def parse_monitor_int_option(flag: str, value: str, json_output: bool, *, minimum: int = 1) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return _invalid_numeric_option(flag, value, json_output)
    if parsed < minimum:
        return _invalid_numeric_option(flag, value, json_output)
    return parsed


def parse_monitor_value_option(flag: str, args: list[str], idx: int, json_output: bool) -> str | None:
    if idx + 1 >= len(args) or not args[idx + 1].strip() or args[idx + 1].startswith("--"):
        return _missing_value_option(flag, json_output)
    return args[idx + 1]


def verify_monitor_completion(
    workflow: str,
    *,
    project_root: str,
    story_key: str,
    output_file: str,
    state_file: str | Path | None = None,
) -> tuple[dict[str, object], str] | None:
    try:
        contract = resolve_success_contract(project_root, workflow, state_file=state_file)
    except (FileNotFoundError, OSError, PolicyError, ValueError):
        return ({"verified": False, "reason": "verifier_contract_invalid"}, "")
    verifier_name = str(contract.get("verifier") or "").strip()
    if not verifier_name:
        return ({"verified": False, "reason": "verifier_contract_invalid"}, "")
    if verifier_name in {"create_story_artifact", "review_completion", "epic_complete"} and not story_key.strip():
        return ({"verified": False, "reason": "story_key_required", "verifier": verifier_name}, verifier_name)
    try:
        result = run_success_verifier(
            verifier_name,
            project_root=project_root,
            story_key=story_key,
            output_file=output_file,
            contract=contract,
        )
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, OSError, PolicyError, ValueError):
        return ({"verified": False, "reason": "verifier_contract_invalid"}, verifier_name)
    return (result, verifier_name)


def _invalid_numeric_option(flag: str, value: str, json_output: bool) -> None:
    if json_output:
        print_json({"ok": False, "error": "invalid_numeric_option", "flag": flag, "value": redact_actual(value)})
    else:
        print(f"{flag} requires a positive integer", file=__import__("sys").stderr)
    return None


def _missing_value_option(flag: str, json_output: bool) -> None:
    if json_output:
        print_json({"ok": False, "error": "missing_option_value", "flag": flag})
    else:
        print(f"{flag} requires a value", file=__import__("sys").stderr)
    return None
