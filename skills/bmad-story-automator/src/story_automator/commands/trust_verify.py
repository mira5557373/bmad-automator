"""``trust_verify`` CLI subcommand chaining the three M06a verification layers.

Thin shell-callable wrapper around the M06a trust-but-verify stack
(M06b REQ-01, REQ-04, REQ-05). Runs Layer 1 (``core.gap_validator``),
Layer 2 (``core.spec_compliance``), and Layer 3 (``core.feature_tester``)
in order, derives a single ``pass``/``warn``/``block`` decision, writes the
five-key result document to ``.claude/trust-verify-output/result.json``, and
prints a compact JSON status line to stdout so BMAD step markdown can branch
on the outcome via ``jq``.

The frozen M06a dataclasses define no ``to_dict`` serializer, so this module
provides small local ``_*_to_dict`` helpers; it does not import or modify the
core modules' types (respects the core guardrail). Uses only stdlib plus the
existing ``core.common`` helpers — no new third-party imports.
"""

from __future__ import annotations

from pathlib import Path

from ..core.common import (
    compact_json,
    iso_now,
    print_json,
    project_root,
    read_text,
    write_atomic,
)
from ..core.feature_tester import TestPlanEntry, plan_feature_tests
from ..core.gap_validator import (
    GapStatus,
    ValidationReport,
    parse_gap_list,
    validate_gaps,
)
from ..core.spec_compliance import (
    ComplianceError,
    ComplianceReport,
    ReqVerdict,
    check_compliance,
)

# Layer-1 aggregate confidence at or above this floor does not, on its own,
# warrant a warn (step-03ab REQ-09 #1).
_LAYER1_CONFIDENCE_FLOOR = 0.6


def _flag_map(args: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and index + 1 < len(args):
            output[token[2:]] = args[index + 1]
            index += 2
            continue
        index += 1
    return output


def _gap_to_dict(gap: object) -> dict:
    return {
        "file_path": gap.file_path,
        "line": gap.line,
        "symbol": gap.symbol,
        "description": gap.description,
        "severity": gap.severity,
    }


def _status_to_dict(status: GapStatus) -> dict:
    return {
        "gap": _gap_to_dict(status.gap),
        "path_exists": status.path_exists,
        "line_in_range": status.line_in_range,
        "symbol_present": status.symbol_present,
        "confidence": status.confidence,
        "notes": list(status.notes),
    }


def _report1_to_dict(report: ValidationReport) -> dict:
    return {
        "statuses": [_status_to_dict(s) for s in report.statuses],
        "overall_confidence": report.overall_confidence,
        "validated_at": report.validated_at,
    }


def _verdict_to_dict(verdict: ReqVerdict) -> dict:
    return {
        "req_id": verdict.req_id,
        "status": verdict.status,
        "evidence": verdict.evidence,
        "confidence": verdict.confidence,
    }


def _report2_to_dict(report: ComplianceReport) -> dict:
    return {
        "verdicts": [_verdict_to_dict(v) for v in report.verdicts],
        "spec_path": report.spec_path,
        "diff_sha": report.diff_sha,
        "model_invocation_ms": report.model_invocation_ms,
    }


def _entry_to_dict(entry: TestPlanEntry) -> dict:
    return {
        "req_id": entry.req_id,
        "existing_test_path": entry.existing_test_path,
        "created_test_path": entry.created_test_path,
        "action": entry.action,
    }


def _decide(
    report1: ValidationReport,
    report2: ComplianceReport,
    plan: list[TestPlanEntry],
) -> str:
    """Derive the chain decision (step-03ab REQ-09; block > warn > pass).

    - Any Layer-2 ``missing`` verdict -> ``block`` (REQ-09 #2).
    - Layer-1 aggregate confidence below the floor -> ``warn`` (REQ-09 #1).
    - Any Layer-3 skeleton freshly ``created`` -> ``warn`` (REQ-09 #3).
    - Otherwise ``pass``.
    """
    if any(v.status == "missing" for v in report2.verdicts):
        return "block"
    warn = report1.overall_confidence < _LAYER1_CONFIDENCE_FLOOR
    warn = warn or any(e.action == "created" for e in plan)
    return "warn" if warn else "pass"


def cmd_trust_verify(args: list[str]) -> int:
    """Entry point for ``story-automator trust_verify`` (M06b REQ-04).

    Required flags:
        --gaps <path-to-gaps.json>
        --spec <path-to-spec.md>
        --diff <path-to-diff>

    Writes ``.claude/trust-verify-output/result.json`` with exactly the five
    keys ``layer1``, ``layer2``, ``layer3``, ``decision``, ``verified_at`` and
    prints ``{"ok": true, "decision": ..., "result_path": ...}`` to stdout.
    Returns 0 on ``pass``/``warn``, 2 on ``block`` so step-03ab can halt, and
    1 on a structured error.
    """
    params = _flag_map(args)
    gaps_path = params.get("gaps", "")
    spec_path = params.get("spec", "")
    diff_path = params.get("diff", "")
    if not gaps_path:
        print_json({"ok": False, "error": "missing_gaps"})
        return 1
    if not spec_path:
        print_json({"ok": False, "error": "missing_spec"})
        return 1
    if not diff_path:
        print_json({"ok": False, "error": "missing_diff"})
        return 1

    root = project_root()

    # Layer 1: deterministic gap validation.
    try:
        gaps = parse_gap_list(read_text(gaps_path))
    except FileNotFoundError:
        print_json({"ok": False, "error": "gaps_file_not_found"})
        return 1
    except ValueError as exc:
        # parse_gap_list raises ValueError (incl. JSONDecodeError) on bad shape.
        print_json({"ok": False, "error": "invalid_gaps", "detail": str(exc)})
        return 1
    try:
        report1 = validate_gaps(gaps, repo_root=root)
    except NotADirectoryError as exc:
        print_json({"ok": False, "error": "invalid_repo_root", "detail": str(exc)})
        return 1

    # Layer 2: spec compliance. The SKILL passes --diff as a FILE path, so the
    # diff text is read here before invoking check_compliance(diff_text=...).
    try:
        diff_text = read_text(diff_path)
    except FileNotFoundError:
        print_json({"ok": False, "error": "diff_file_not_found"})
        return 1
    try:
        report2 = check_compliance(spec_path=Path(spec_path), diff_text=diff_text)
    except FileNotFoundError:
        print_json({"ok": False, "error": "spec_file_not_found"})
        return 1
    except ComplianceError as exc:
        # REQ-09 #5: subprocess non-zero / timeout / parse failure. Mirror the
        # ceiling_check io_error precedent: surface a structured stdout error
        # and do NOT persist a partial result.json (malformed/halt semantics).
        print_json({"ok": False, "error": "layer2_failed", "detail": str(exc)})
        return 1

    # Layer 3: feature-test planning. dry_run=False writes skeletons for any
    # implemented REQ lacking a feature test (SKILL Output contract).
    plan = plan_feature_tests(report2.verdicts, tests_dir=root / "tests", dry_run=False)

    decision = _decide(report1, report2, plan)
    result = {
        "layer1": _report1_to_dict(report1),
        "layer2": _report2_to_dict(report2),
        "layer3": [_entry_to_dict(e) for e in plan],
        "decision": decision,
        "verified_at": iso_now(),
    }
    out_path = root / ".claude" / "trust-verify-output" / "result.json"
    write_atomic(out_path, compact_json(result))
    print_json({"ok": True, "decision": decision, "result_path": str(out_path)})
    return 0 if decision != "block" else 2
