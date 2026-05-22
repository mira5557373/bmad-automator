from __future__ import annotations

import json

from story_automator.core.diagnostics import issues_from_exception
from story_automator.core.parse_contracts import ParseContractError, load_parse_contract, parse_failure_payload, validate_payload
from story_automator.core.runtime_policy import PolicyError, load_runtime_policy, parser_runtime_config, step_contract
from story_automator.core.utils import COMMAND_TIMEOUT_EXIT, extract_json_line, print_json, read_text, run_cmd, trim_lines


def parse_output_action(args: list[str]) -> int:
    if len(args) < 2:
        print_json(parse_failure_payload("output file not found or empty"))
        return 1
    output_file, step = args[:2]
    state_file = ""
    idx = 2
    while idx < len(args):
        if args[idx] == "--state-file":
            if idx + 1 >= len(args) or not args[idx + 1].strip() or args[idx + 1].startswith("--"):
                print_json(parse_failure_payload("parse_contract_invalid", issues_from_exception(ValueError("--state-file requires a value"), source="parse-output", field="--state-file")))
                return 1
            state_file = args[idx + 1]
            idx += 2
            continue
        idx += 1
    try:
        content = read_text(output_file)
    except FileNotFoundError as exc:
        print_json(parse_failure_payload("output file not found or empty", issues_from_exception(exc, source="parse-output", field="output_file")))
        return 1
    if not content.strip():
        print_json(parse_failure_payload("output file not found or empty", issues_from_exception(ValueError("output file empty"), source="parse-output", field="output_file")))
        return 1
    lines = trim_lines(content)[:150]
    try:
        policy = load_runtime_policy(state_file=state_file)
    except PolicyError as exc:
        message = str(exc)
        if "parse schema" in message or "policy data file missing" in message:
            print_json(parse_failure_payload("parse_contract_invalid", issues_from_exception(exc, source="parse-contract", field="parse.schemaPath")))
        else:
            print_json(parse_failure_payload("runtime_policy_invalid", issues_from_exception(exc, source="runtime-policy", field="runtime.policy")))
        return 1
    try:
        contract = step_contract(policy, step)
    except PolicyError as exc:
        print_json(parse_failure_payload("step_contract_invalid", issues_from_exception(exc, source="step-contract", field="step")))
        return 1
    try:
        parse_contract = load_parse_contract(contract)
    except ParseContractError as exc:
        print_json(parse_failure_payload("parse_contract_invalid", exc.issues))
        return 1
    try:
        parser_cfg = parser_runtime_config(policy)
    except PolicyError as exc:
        print_json(parse_failure_payload("runtime_policy_invalid", issues_from_exception(exc, source="runtime-policy", field="runtime.parser")))
        return 1
    prompt = _build_parse_prompt(contract, parse_contract, "\n".join(lines))
    result = run_cmd(
        str(parser_cfg["provider"]),
        "-p",
        "--model",
        str(parser_cfg["model"]),
        prompt,
        env={"STORY_AUTOMATOR_CHILD": "true", "CLAUDECODE": ""},
        timeout=int(parser_cfg["timeoutSeconds"]),
    )
    if result.exit_code != 0:
        reason = "sub-agent call timed out" if result.exit_code == COMMAND_TIMEOUT_EXIT else "sub-agent call failed"
        print_json(parse_failure_payload(reason, issues_from_exception(result.error or RuntimeError(reason), source="parse-output", field="sub_agent")))
        return 1
    json_line = extract_json_line(result.output)
    if not json_line:
        print_json(parse_failure_payload("sub-agent returned invalid json", issues_from_exception(ValueError("no json object found"), source="parse-output", field="payload")))
        return 1
    try:
        payload = json.loads(json_line)
    except json.JSONDecodeError as exc:
        print_json(parse_failure_payload("sub-agent returned invalid json", issues_from_exception(exc, source="parse-output", field="payload")))
        return 1
    issues = validate_payload(payload, parse_contract)
    if issues:
        print_json(parse_failure_payload("sub-agent returned invalid json", issues))
        return 1
    print(json.dumps(payload, separators=(",", ":")))
    return 0


def _build_parse_prompt(contract: dict[str, object], parse_contract: dict[str, object], content: str) -> str:
    label = str(contract.get("label") or "session")
    schema = json.dumps(parse_contract.get("schema") or {}, separators=(",", ":"))
    return f"Analyze this {label} session output. Return JSON only:\n{schema}\n\nSession output:\n---\n{content}\n---"
