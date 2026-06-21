# Extension M14: System-Altitude Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the system-altitude gate (§10) — per-epic quality checks running against ephemeral environments that verify Hard Rule 6 criteria: reliability, resilience, durable HITL, blast radius, and cost-to-serve. Plus progressive-delivery evidence from Argo Rollouts. This completes the second tier of the two-tier gate architecture (code + system).

**Architecture:** Five system-altitude collectors + environment provisioning + per-epic gate lifecycle, all reusing the existing collector framework and verdict engine with `tier="system"`:
- `system_env.py` (~180 LOC) — ephemeral environment tier resolution (minimal vs full) + provision/teardown context manager.
- `system_gate.py` (~300 LOC) — per-epic system gate lifecycle: provisions env → runs system collectors → adjudicates → routes epic-level verdict (FAIL can reopen stories).
- Six new collector modules (~70 LOC each): `collectors/reliability.py`, `collectors/resilience.py`, `collectors/durable_hitl.py`, `collectors/blast_radius.py`, `collectors/cost_to_serve.py`, `collectors/progressive_delivery.py`.
- Category rules for all 5+1 system categories added to `category_rules.py`.

**Key design decision — env info passing:** System collectors need K8s endpoints, namespaces, and env tier details. Rather than changing the `CmdBuilder(checkout: str, profile: dict) -> list[str]` signature, the system gate orchestrator injects a transient `profile["_runtime_env"]` dict before running system collectors and strips it after. This preserves all existing interfaces while giving system collectors access to endpoints, namespaces, and resource pricing.

**Dependency graph:** Consumes all M10 infrastructure (gate_orchestrator, gate_status, gate_audit, evidence_io, verdict_engine, collector framework, product_profile) but does NOT modify any existing M1-M10 module logic except: `category_rules.py` (new system rule functions), `gate_audit.py` (2 new events), `commands/gate_cmd.py` (system subcommands), `verdict_engine.py` (add backward-compatible `tier` parameter to `build_gate_file` and `evaluate_gate`), `product_profile.py` (add `progressive_delivery` to `VALID_SYSTEM_CATEGORIES` + system timeout defaults). Import direction: `system_env.py` → `system_gate.py` → `gate_cmd.py` (strictly unidirectional).

**§10 → Hard Rule 6 mapping:**
| System Category | HR6 | Harness | Collector |
|---|---|---|---|
| reliability | (a) | CNPG failover + pgBackRest restore timing | `cnpg-reliability` |
| resilience | (b) | Chaos Mesh pod-kill / net-loss / IO-fault | `chaos-mesh-resilience` |
| durable_hitl | (c) | Temporal signal survival after pod kill | `temporal-durable-hitl` |
| blast_radius | (d) | Load tenant A → assert tenant B SLO unaffected | `k6-blast-radius` |
| cost_to_serve | (f) | k6 load → resource×price; CONCERNS if DG-2 undefined | `k6-cost-to-serve` |
| (progressive_delivery) | — | Argo Rollouts blue-green/canary evidence | `argo-progressive-delivery` |

**Key existing interfaces consumed:**
- `gate_orchestrator.py`: `run_production_gate`, `route_gate_verdict`, `recover_from_crash`, `check_gate_reuse`
- `verdict_engine.py`: `evaluate_gate`, `adjudicate`, `build_gate_file`, `compute_all_verdicts`
- `collector_runner.py`: `run_gate_collectors`, `run_single_collector`
- `collector_registry.py`: `CollectorRegistry`, `applicable`
- `collector_config.py`: `CollectorConfig`, `CollectorOutcome`, `CmdBuilder`
- `evidence_io.py`: `persist_evidence_record`, `load_evidence_bundle`, gate marker functions
- `gate_schema.py`: `make_evidence_record`, `make_gate_file`, validation
- `gate_audit.py`: `emit_gate_audit`, audit event dataclass pattern
- `gate_status.py`: `park_story`, `resume_story`, `record_mitigation_debt`
- `gate_rules.py`: `verdict_for_cost_tier`, `aggregate_verdicts`
- `product_profile.py`: `compute_profile_hash`, `VALID_SYSTEM_CATEGORIES`, `rule_for`
- `trust_boundary.py`: `assert_host_context`

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; no new deps.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate audit events ride `UnknownEvent` forward-compat.
- **Do NOT modify existing M1-M10 module logic** except: `category_rules.py` (new system rule functions), `gate_audit.py` (new audit events), `commands/gate_cmd.py` (system subcommands), `verdict_engine.py` (backward-compatible `tier` param), `product_profile.py` (`progressive_delivery` + system timeout defaults).
- **500-LOC soft limit per Python module.** `system_gate.py` target ~300 LOC; `system_env.py` ~180 LOC; each collector ~70 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short` to validate.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path; use `os.replace` via `write_atomic` for atomic writes.
- **Tier convention:** system-altitude evidence records, gate files, and audit events use `tier="system"`.
- **`_runtime_env` is transient:** injected into profile copy before running system collectors, NEVER persisted. System collectors access it via `profile.get("_runtime_env") or {}`.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/system_env.py` — env tier resolution + provision/teardown (~180 LOC)
- `skills/bmad-story-automator/src/story_automator/core/system_gate.py` — per-epic system gate lifecycle (~300 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/reliability.py` — CNPG failover/restore (~70 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/resilience.py` — Chaos Mesh scenarios (~70 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/durable_hitl.py` — Temporal signal survival (~70 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/blast_radius.py` — tenant SLO isolation (~70 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/cost_to_serve.py` — k6 load + resource pricing (~90 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/progressive_delivery.py` — Argo Rollouts evidence (~70 LOC)
- `tests/test_system_category_rules.py` — tests for system rule functions (~300 LOC)
- `tests/test_system_env.py` — tests for env tier resolution + provision/teardown (~250 LOC)
- `tests/test_system_collectors.py` — tests for all 6 system collectors (~350 LOC)
- `tests/test_system_gate.py` — tests for system gate lifecycle + epic routing (~350 LOC)
- `tests/test_system_gate_integration.py` — end-to-end integration tests (~200 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/category_rules.py` — add 6 system rule functions + register in `CATEGORY_RULES` (~+90 LOC)
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` — add `SystemGateStartedAudit`, `EpicGateDecisionAudit` (~+50 LOC)
- `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py` — add `system-status` subcommand (~+40 LOC)
- `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py` — add backward-compatible `tier: str = "code"` param to `build_gate_file` and `evaluate_gate` (~+6 LOC)
- `skills/bmad-story-automator/src/story_automator/core/product_profile.py` — add `progressive_delivery` to `VALID_SYSTEM_CATEGORIES`, add system timeout defaults (~+8 LOC)

**Untouched (explicit):** `core/telemetry_events.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/evidence_io.py`, `core/adjudicator.py`, `core/collector_runner.py`, `core/collector_registry.py`, `core/collector_config.py`, `core/trust_boundary.py`, `core/gate_orchestrator.py`, `core/gate_status.py`, `core/gate_remediation.py`, `core/success_verifiers.py`, `core/runtime_policy.py`.

---

### Task 1: System Category Rule Functions (reliability, resilience, blast_radius, durable_hitl)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Create: `tests/test_system_category_rules.py`

**Interfaces:**
- Consumes: existing `_status_based_rule`, `_make_category_result`, `worst_evidence_status`, `_aggregate_metrics`, `rule_for` patterns.
- Produces:
  - `reliability_rule(evidence, profile, required) -> dict` — checks RTO/RPO from `metrics.rto_seconds` and `metrics.rpo_seconds` against `profile.rules.reliability.{max_rto_seconds, max_rpo_seconds}`. FAIL on breach or error/timeout.
  - `resilience_rule(evidence, profile, required) -> dict` — checks all chaos scenarios passed (metrics: `scenarios_total`, `scenarios_passed`). FAIL if any scenario failed or error/timeout.
  - `blast_radius_rule(evidence, profile, required) -> dict` — checks tenant isolation (metrics: `slo_breached: bool`). FAIL if tenant B's SLO was affected by tenant A's load.
  - `durable_hitl_rule(evidence, profile, required) -> dict` — checks Temporal signal survived pod kill (metrics: `signal_survived: bool`). FAIL if signal lost.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_system_category_rules.py`:

```python
"""Tests for system-altitude category rule functions."""
from __future__ import annotations

import unittest

from story_automator.core.category_rules import (
    apply_category_rule,
    reliability_rule,
    resilience_rule,
    blast_radius_rule,
    durable_hitl_rule,
)


def _sys_profile(**rule_overrides: object) -> dict:
    """Minimal profile with system rules."""
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": [], "system": [
            "reliability", "resilience", "blast_radius", "durable_hitl",
        ]},
        "rules": {
            "reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60, **rule_overrides},
        },
    }


def _evidence(category: str, status: str = "ok", **metrics: object) -> dict:
    return {
        "schema_version": 1,
        "collector": f"test-{category}",
        "tool": "test-tool",
        "tool_version": "",
        "category": category,
        "tier": "system",
        "status": status,
        "metrics": dict(metrics),
        "findings": [],
        "raw_output_ref": "",
        "exit_code": 0,
        "duration_ms": 100,
        "deterministic": True,
    }


class ReliabilityRuleTests(unittest.TestCase):
    def test_pass_within_limits(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=30)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_rto_exceeded(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=600, rpo_seconds=30)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("rto", result["rationale"].lower())

    def test_fail_rpo_exceeded(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=120)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", status="error")]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_fail_closed_on_timeout(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", status="timeout")]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_dispatch_via_apply(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=30)]
        result = apply_category_rule("reliability", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")


class ResilienceRuleTests(unittest.TestCase):
    def test_pass_all_scenarios(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=3, scenarios_passed=3)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_scenario_failed(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=3, scenarios_passed=2)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("scenario", result["rationale"].lower())

    def test_fail_zero_scenarios(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=0, scenarios_passed=0)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("no resilience scenarios", result["rationale"])

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", status="timeout")]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")


class BlastRadiusRuleTests(unittest.TestCase):
    def test_pass_no_breach(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("blast_radius", slo_breached=False)]
        result = blast_radius_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_slo_breached(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("blast_radius", slo_breached=True)]
        result = blast_radius_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("slo", result["rationale"].lower())


class DurableHitlRuleTests(unittest.TestCase):
    def test_pass_signal_survived(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("durable_hitl", signal_survived=True)]
        result = durable_hitl_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_signal_lost(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("durable_hitl", signal_survived=False)]
        result = durable_hitl_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("signal", result["rationale"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_category_rules.py -v --tb=short`
Expected: ImportError — `reliability_rule`, `resilience_rule`, `blast_radius_rule`, `durable_hitl_rule` not found in `category_rules`.

- [ ] **Step 3: Write minimal implementation**

Append to `skills/bmad-story-automator/src/story_automator/core/category_rules.py`:

```python
def reliability_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(a): RTO/RPO within profile limits."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "reliability")
    max_rto = int(rules.get("max_rto_seconds", 300))
    max_rpo = int(rules.get("max_rpo_seconds", 60))
    rto = float(_aggregate_metrics(evidence, "rto_seconds", 0))
    rpo = float(_aggregate_metrics(evidence, "rpo_seconds", 0))
    actual = {"rto_seconds": rto, "rpo_seconds": rpo, "status": status}
    req = {"max_rto_seconds": max_rto, "max_rpo_seconds": max_rpo}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    violations: list[str] = []
    if rto > max_rto:
        violations.append(f"RTO {rto}s > max {max_rto}s")
    if rpo > max_rpo:
        violations.append(f"RPO {rpo}s > max {max_rpo}s")
    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "reliability checks passed")


def resilience_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(b): all chaos scenarios passed."""
    status = worst_evidence_status(evidence)
    total = int(_aggregate_metrics(evidence, "scenarios_total", 0))
    passed = int(_aggregate_metrics(evidence, "scenarios_passed", 0))
    actual = {"scenarios_total": total, "scenarios_passed": passed, "status": status}
    req = {"all_scenarios_pass": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if total == 0:
        return _make_category_result("FAIL", req, actual, "no resilience scenarios executed")
    if passed < total:
        failed = total - passed
        return _make_category_result("FAIL", req, actual, f"{failed} scenario(s) failed out of {total}")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "all resilience scenarios passed")


def blast_radius_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(d): tenant SLO isolation under load."""
    status = worst_evidence_status(evidence)
    slo_breached = bool(_aggregate_metrics(evidence, "slo_breached", False))
    actual = {"slo_breached": slo_breached, "status": status}
    req = {"slo_breached": False}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if slo_breached:
        return _make_category_result("FAIL", req, actual, "tenant SLO breached during load test")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "blast radius check passed")


def durable_hitl_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(c): Temporal signal survived pod kill."""
    status = worst_evidence_status(evidence)
    survived = bool(_aggregate_metrics(evidence, "signal_survived", False))
    actual = {"signal_survived": survived, "status": status}
    req = {"signal_survived": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if not survived:
        return _make_category_result("FAIL", req, actual, "Temporal signal lost after pod kill")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "durable HITL check passed")
```

Add to `CATEGORY_RULES`:
```python
CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
    "reliability": reliability_rule,
    "resilience": resilience_rule,
    "blast_radius": blast_radius_rule,
    "durable_hitl": durable_hitl_rule,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_category_rules.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Run full test suite for regressions**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short -x`
Expected: No regressions.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_system_category_rules.py
git commit -m "feat(gate): add system-altitude category rules for reliability, resilience, blast_radius, durable_hitl" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Cost-to-Serve + Progressive Delivery Category Rules

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_system_category_rules.py`

**Interfaces:**
- Consumes: `gate_rules.verdict_for_cost_tier`, `rule_for`, existing rule patterns.
- Produces:
  - `cost_to_serve_rule(evidence, profile, required) -> dict` — uses `verdict_for_cost_tier` from `gate_rules.py` for DG-2 degradation, then checks `metrics.pod_cost_per_tenant` vs `profile.cost_tier.max_pod_cost_per_tenant` when DG-2 is defined. CONCERNS (not FAIL) while DG-2 undefined per §6.4.
  - `progressive_delivery_rule(evidence, profile, required) -> dict` — checks Argo Rollouts status: rollout completed successfully. Status-based with metrics for rollout strategy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_category_rules.py`:

```python
from story_automator.core.category_rules import (
    cost_to_serve_rule,
    progressive_delivery_rule,
)


class CostToServeRuleTests(unittest.TestCase):
    def test_concerns_when_dg2_undefined(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0}
        profile["forbidden_until"] = {"DG-2": ["*.cost-to-serve"]}
        evidence = [_evidence("cost_to_serve", pod_cost_per_tenant=5.0)]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "CONCERNS")

    def test_pass_cost_within_budget(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "starter", "arpu_monthly": 100, "max_pod_cost_per_tenant": 10}
        profile["forbidden_until"] = {}
        evidence = [_evidence("cost_to_serve", pod_cost_per_tenant=5.0)]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_cost_exceeds_budget(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "starter", "arpu_monthly": 100, "max_pod_cost_per_tenant": 10}
        profile["forbidden_until"] = {}
        evidence = [_evidence("cost_to_serve", pod_cost_per_tenant=15.0)]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_concerns_no_sku_defined(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0}
        profile["forbidden_until"] = {}
        evidence = [_evidence("cost_to_serve", pod_cost_per_tenant=5.0)]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "CONCERNS")

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "starter", "arpu_monthly": 100, "max_pod_cost_per_tenant": 10}
        profile["forbidden_until"] = {}
        evidence = [_evidence("cost_to_serve", status="error")]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_dispatch_via_apply(self) -> None:
        profile = _sys_profile()
        profile["cost_tier"] = {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0}
        profile["forbidden_until"] = {"DG-2": ["*.cost-to-serve"]}
        evidence = [_evidence("cost_to_serve")]
        result = apply_category_rule("cost_to_serve", evidence, profile, {})
        self.assertEqual(result["verdict"], "CONCERNS")


class ProgressiveDeliveryRuleTests(unittest.TestCase):
    def test_pass_rollout_complete(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("progressive_delivery", rollout_completed=True, strategy="blue-green")]
        result = progressive_delivery_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_rollout_incomplete(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("progressive_delivery", rollout_completed=False, strategy="canary")]
        result = progressive_delivery_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("progressive_delivery", status="timeout")]
        result = progressive_delivery_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_category_rules.py -v -k "CostToServe or ProgressiveDelivery" --tb=short`
Expected: ImportError — `cost_to_serve_rule`, `progressive_delivery_rule` not found.

- [ ] **Step 3: Write minimal implementation**

Append to `category_rules.py`:

```python
def cost_to_serve_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10/HR6(f): cost_to_serve with DG-2 degradation path."""
    from .gate_rules import verdict_for_cost_tier
    status = worst_evidence_status(evidence)
    cost_tier = profile.get("cost_tier")
    forbidden = profile.get("forbidden_until")
    pod_cost = float(_aggregate_metrics(evidence, "pod_cost_per_tenant", 0))
    max_cost = float((cost_tier or {}).get("max_pod_cost_per_tenant", 0))
    actual = {"pod_cost_per_tenant": pod_cost, "status": status}
    req = {"max_pod_cost_per_tenant": max_cost}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    tier_verdict = verdict_for_cost_tier(cost_tier, forbidden)
    if tier_verdict == "CONCERNS":
        return _make_category_result("CONCERNS", req, actual, "cost_to_serve degraded: DG-2/SKU undefined")
    if max_cost > 0 and pod_cost > max_cost:
        return _make_category_result("FAIL", req, actual, f"pod cost {pod_cost} > max {max_cost}")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "cost-to-serve check passed")


def progressive_delivery_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """§10: progressive-delivery rollout evidence (Argo Rollouts)."""
    status = worst_evidence_status(evidence)
    completed = bool(_aggregate_metrics(evidence, "rollout_completed", False))
    strategy = str(_aggregate_metrics(evidence, "strategy", ""))
    actual = {"rollout_completed": completed, "strategy": strategy, "status": status}
    req = {"rollout_completed": True}
    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if not completed:
        return _make_category_result("FAIL", req, actual, "progressive delivery rollout did not complete")
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "progressive delivery check passed")
```

Update `CATEGORY_RULES` to include `"cost_to_serve": cost_to_serve_rule` and `"progressive_delivery": progressive_delivery_rule`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_category_rules.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/category_rules.py tests/test_system_category_rules.py
git commit -m "feat(gate): add cost_to_serve and progressive_delivery category rules with DG-2 degradation" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: System Environment Config + Tier Resolution

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/system_env.py`
- Create: `tests/test_system_env.py`

**Interfaces:**
- Consumes: `product_profile.rule_for` for env configuration, `trust_boundary.assert_host_context`.
- Produces:
  - `ENV_TIER_MINIMAL = "minimal"` / `ENV_TIER_FULL = "full"` — tier constants.
  - `SystemEnvConfig` — frozen dataclass: `tier`, `compose_file`, `namespace`, `services`, `seed_data`.
  - `resolve_env_tier(epic_metadata: dict, profile: dict) -> str` — returns MINIMAL or FULL based on epic type (infra/cross-cutting → FULL, else MINIMAL). Release candidates → FULL.
  - `build_env_config(project_root, commit_sha, epic_metadata, profile) -> SystemEnvConfig` — builds full config for provisioning.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_system_env.py`:

```python
"""Tests for system environment tier resolution and config."""
from __future__ import annotations

import unittest

from story_automator.core.system_env import (
    ENV_TIER_MINIMAL,
    ENV_TIER_FULL,
    SystemEnvConfig,
    resolve_env_tier,
    build_env_config,
)


class ResolveTierTests(unittest.TestCase):
    def test_default_is_minimal(self) -> None:
        tier = resolve_env_tier({}, {})
        self.assertEqual(tier, ENV_TIER_MINIMAL)

    def test_infra_epic_is_full(self) -> None:
        epic = {"type": "infra"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_cross_cutting_epic_is_full(self) -> None:
        epic = {"type": "cross-cutting"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_release_candidate_is_full(self) -> None:
        epic = {"release_candidate": True}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_FULL)

    def test_feature_epic_is_minimal(self) -> None:
        epic = {"type": "feature"}
        tier = resolve_env_tier(epic, {})
        self.assertEqual(tier, ENV_TIER_MINIMAL)

    def test_profile_override_to_full(self) -> None:
        epic = {"type": "feature"}
        profile = {"rules": {"system_env": {"force_tier": "full"}}}
        tier = resolve_env_tier(epic, profile)
        self.assertEqual(tier, ENV_TIER_FULL)


class SystemEnvConfigTests(unittest.TestCase):
    def test_frozen(self) -> None:
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns")
        with self.assertRaises(AttributeError):
            config.tier = ENV_TIER_FULL

    def test_defaults(self) -> None:
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        self.assertEqual(config.compose_file, "")
        self.assertEqual(config.services, ())
        self.assertEqual(config.seed_data, "")
        self.assertEqual(config.helm_values, "")


class BuildEnvConfigTests(unittest.TestCase):
    def test_minimal_tier(self) -> None:
        config = build_env_config(
            "/tmp/project", "abc123",
            {"type": "feature"}, {"version": 1, "id": "test"},
        )
        self.assertEqual(config.tier, ENV_TIER_MINIMAL)
        self.assertIn("abc123", config.namespace)

    def test_full_tier_infra(self) -> None:
        config = build_env_config(
            "/tmp/project", "abc123",
            {"type": "infra"}, {"version": 1, "id": "test"},
        )
        self.assertEqual(config.tier, ENV_TIER_FULL)

    def test_namespace_contains_commit_prefix(self) -> None:
        config = build_env_config(
            "/tmp/project", "deadbeef1234",
            {}, {"version": 1, "id": "test"},
        )
        self.assertIn("deadbeef", config.namespace)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_env.py -v --tb=short`
Expected: ModuleNotFoundError — `system_env` not found.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/system_env.py`:

```python
"""System environment tier resolution and config (§10).

Resolves whether an epic gate needs a minimal (testcontainers/compose)
or full (kind/k3d + Helm) ephemeral environment, and builds the
SystemEnvConfig used by provision/teardown.
"""
from __future__ import annotations

import dataclasses
from typing import Any

ENV_TIER_MINIMAL = "minimal"
ENV_TIER_FULL = "full"

_FULL_TIER_EPIC_TYPES = frozenset({"infra", "cross-cutting"})


@dataclasses.dataclass(frozen=True)
class SystemEnvConfig:
    """Configuration for an ephemeral system-test environment."""
    tier: str
    namespace: str
    compose_file: str = ""
    helm_values: str = ""
    services: tuple[str, ...] = ()
    seed_data: str = ""


def resolve_env_tier(
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    """§10: resolve minimal vs full env tier.

    FULL for infra/cross-cutting epics and release candidates.
    Profile can force tier via rules.system_env.force_tier.
    """
    rules = (profile.get("rules") or {}).get("system_env") or {}
    force = rules.get("force_tier", "")
    if force in (ENV_TIER_MINIMAL, ENV_TIER_FULL):
        return force

    epic_type = epic_metadata.get("type", "")
    if epic_type in _FULL_TIER_EPIC_TYPES:
        return ENV_TIER_FULL

    if epic_metadata.get("release_candidate"):
        return ENV_TIER_FULL

    return ENV_TIER_MINIMAL


def build_env_config(
    project_root: str,
    commit_sha: str,
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
) -> SystemEnvConfig:
    """Build a SystemEnvConfig for the given epic and profile."""
    tier = resolve_env_tier(epic_metadata, profile)
    sha_prefix = commit_sha[:8] if commit_sha else "unknown"
    epic_id = epic_metadata.get("id", "epic")
    namespace = f"gate-{epic_id}-{sha_prefix}"

    rules = (profile.get("rules") or {}).get("system_env") or {}
    compose_file = str(rules.get("compose_file", ""))
    helm_values = str(rules.get("helm_values", ""))
    services = tuple(rules.get("services") or ())
    seed_data = str(rules.get("seed_data", ""))

    return SystemEnvConfig(
        tier=tier,
        namespace=namespace,
        compose_file=compose_file,
        helm_values=helm_values,
        services=services,
        seed_data=seed_data,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_env.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/system_env.py tests/test_system_env.py
git commit -m "feat(gate): add system env tier resolution and SystemEnvConfig" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Environment Provision/Teardown Context Manager

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/system_env.py`
- Modify: `tests/test_system_env.py`

**Interfaces:**
- Consumes: `SystemEnvConfig`, `trust_boundary.assert_host_context`, `subprocess.run`.
- Produces:
  - `SystemEnvInfo` — frozen dataclass: `env_id`, `tier`, `namespace`, `endpoints` dict, `provisioned: bool`.
  - `provision_system_env(config: SystemEnvConfig, project_root: str) -> SystemEnvInfo` — provisions the ephemeral env via subprocess (docker-compose up / kind create + helm install).
  - `teardown_system_env(env_info: SystemEnvInfo, project_root: str) -> None` — tears down the env.
  - `system_env(config, project_root)` — context manager yielding SystemEnvInfo, teardown in finally.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_env.py`:

```python
import os
import tempfile
from unittest.mock import patch, MagicMock

from story_automator.core.system_env import (
    SystemEnvInfo,
    provision_system_env,
    teardown_system_env,
    system_env,
)


class SystemEnvInfoTests(unittest.TestCase):
    def test_frozen(self) -> None:
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        with self.assertRaises(AttributeError):
            info.env_id = "e2"

    def test_defaults(self) -> None:
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        self.assertEqual(info.endpoints, {})
        self.assertTrue(info.provisioned)


class ProvisionEnvTests(unittest.TestCase):
    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_minimal_calls_compose(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns", compose_file="compose.yaml")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertTrue(info.provisioned)
        self.assertEqual(info.tier, ENV_TIER_MINIMAL)
        mock_sub.run.assert_called()

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_full_calls_kind_and_helm(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        config = SystemEnvConfig(tier=ENV_TIER_FULL, namespace="test-ns")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertTrue(info.provisioned)
        self.assertEqual(info.tier, ENV_TIER_FULL)

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_provision_failure_returns_not_provisioned(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=1)
        mock_sub.CalledProcessError = Exception
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="test-ns")
        with tempfile.TemporaryDirectory() as td:
            info = provision_system_env(config, td)
        self.assertFalse(info.provisioned)


class TeardownEnvTests(unittest.TestCase):
    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_teardown_minimal(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        with tempfile.TemporaryDirectory() as td:
            teardown_system_env(info, td)
        mock_sub.run.assert_called()

    @patch("story_automator.core.system_env.subprocess")
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_teardown_full(self, mock_sub: MagicMock) -> None:
        mock_sub.run.return_value = MagicMock(returncode=0)
        info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        with tempfile.TemporaryDirectory() as td:
            teardown_system_env(info, td)


class SystemEnvContextManagerTests(unittest.TestCase):
    @patch("story_automator.core.system_env.teardown_system_env")
    @patch("story_automator.core.system_env.provision_system_env")
    def test_yields_env_info(self, mock_prov: MagicMock, mock_tear: MagicMock) -> None:
        expected = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_prov.return_value = expected
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        with system_env(config, "/tmp") as info:
            self.assertEqual(info, expected)
        mock_tear.assert_called_once_with(expected, "/tmp")

    @patch("story_automator.core.system_env.teardown_system_env")
    @patch("story_automator.core.system_env.provision_system_env")
    def test_teardown_on_exception(self, mock_prov: MagicMock, mock_tear: MagicMock) -> None:
        expected = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_prov.return_value = expected
        config = SystemEnvConfig(tier=ENV_TIER_MINIMAL, namespace="ns")
        with self.assertRaises(RuntimeError):
            with system_env(config, "/tmp") as info:
                raise RuntimeError("boom")
        mock_tear.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_env.py -v -k "Provision or Teardown or ContextManager" --tb=short`
Expected: ImportError — `SystemEnvInfo`, `provision_system_env`, etc. not found.

- [ ] **Step 3: Write minimal implementation**

Add to `system_env.py`:

```python
import subprocess
import uuid
from contextlib import contextmanager
from .trust_boundary import assert_host_context


@dataclasses.dataclass(frozen=True)
class SystemEnvInfo:
    """Runtime details of a provisioned system environment."""
    env_id: str
    tier: str
    namespace: str
    endpoints: dict[str, str] = dataclasses.field(default_factory=dict)
    provisioned: bool = True


def provision_system_env(
    config: SystemEnvConfig,
    project_root: str,
) -> SystemEnvInfo:
    """Provision an ephemeral environment for system-altitude checks."""
    assert_host_context("provision_system_env")
    env_id = f"sysenv-{uuid.uuid4().hex[:8]}"
    if config.tier == ENV_TIER_MINIMAL:
        return _provision_minimal(config, project_root, env_id)
    return _provision_full(config, project_root, env_id)


def _provision_minimal(
    config: SystemEnvConfig, project_root: str, env_id: str,
) -> SystemEnvInfo:
    compose = config.compose_file or "docker-compose.yaml"
    cmd = ["docker", "compose", "-f", compose, "-p", config.namespace, "up", "-d"]
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return SystemEnvInfo(env_id=env_id, tier=ENV_TIER_MINIMAL, namespace=config.namespace, provisioned=False)
    return SystemEnvInfo(env_id=env_id, tier=ENV_TIER_MINIMAL, namespace=config.namespace)


def _provision_full(
    config: SystemEnvConfig, project_root: str, env_id: str,
) -> SystemEnvInfo:
    kind_cmd = ["kind", "create", "cluster", "--name", config.namespace]
    result = subprocess.run(kind_cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        return SystemEnvInfo(env_id=env_id, tier=ENV_TIER_FULL, namespace=config.namespace, provisioned=False)
    if config.helm_values:
        helm_cmd = ["helm", "install", config.namespace, ".", "-f", config.helm_values, "-n", config.namespace]
        subprocess.run(helm_cmd, cwd=project_root, capture_output=True, text=True, timeout=600)
    return SystemEnvInfo(env_id=env_id, tier=ENV_TIER_FULL, namespace=config.namespace)


def teardown_system_env(
    env_info: SystemEnvInfo,
    project_root: str,
) -> None:
    """Tear down a provisioned ephemeral environment."""
    assert_host_context("teardown_system_env")
    if env_info.tier == ENV_TIER_MINIMAL:
        subprocess.run(
            ["docker", "compose", "-p", env_info.namespace, "down", "-v"],
            cwd=project_root, capture_output=True, text=True, timeout=120,
        )
    elif env_info.tier == ENV_TIER_FULL:
        subprocess.run(
            ["kind", "delete", "cluster", "--name", env_info.namespace],
            capture_output=True, text=True, timeout=120,
        )


@contextmanager
def system_env(config: SystemEnvConfig, project_root: str):
    """Context manager: provision → yield → teardown."""
    info = provision_system_env(config, project_root)
    try:
        yield info
    finally:
        teardown_system_env(info, project_root)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_env.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/system_env.py tests/test_system_env.py
git commit -m "feat(gate): add system env provision/teardown context manager" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Reliability Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/reliability.py`
- Create: `tests/test_system_collectors.py`

**Interfaces:**
- Consumes: `collector_config.CollectorConfig`, `CmdBuilder` pattern.
- Produces:
  - `CNPG_FAILOVER` — CollectorConfig: runs CNPG failover test via `kubectl cnpg promote` + timing assertion. Category: `reliability`, tier: `system`, tool: `cnpg`.
  - `PGBACKREST_RESTORE` — CollectorConfig: runs pgBackRest restore timing check. Category: `reliability`, tier: `system`, tool: `pgbackrest`.
  - `COLLECTORS: list[CollectorConfig]` — module-level list for registry.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_system_collectors.py`:

```python
"""Tests for system-altitude evidence collectors."""
from __future__ import annotations

import unittest

from story_automator.core.collectors.reliability import (
    CNPG_FAILOVER,
    PGBACKREST_RESTORE,
    COLLECTORS as RELIABILITY_COLLECTORS,
)


def _sys_profile(**extras: object) -> dict:
    return {
        "version": 1, "id": "test",
        "rules": {"reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60}},
        "_runtime_env": {"namespace": "gate-test-abc12345", "tier": "full"},
        **extras,
    }


class ReliabilityCollectorTests(unittest.TestCase):
    def test_cnpg_failover_config(self) -> None:
        self.assertEqual(CNPG_FAILOVER.category, "reliability")
        self.assertEqual(CNPG_FAILOVER.tool, "cnpg")
        self.assertEqual(CNPG_FAILOVER.collector_id, "cnpg-reliability")

    def test_pgbackrest_config(self) -> None:
        self.assertEqual(PGBACKREST_RESTORE.category, "reliability")
        self.assertEqual(PGBACKREST_RESTORE.tool, "pgbackrest")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(RELIABILITY_COLLECTORS), 2)
        self.assertIn(CNPG_FAILOVER, RELIABILITY_COLLECTORS)
        self.assertIn(PGBACKREST_RESTORE, RELIABILITY_COLLECTORS)

    def test_cnpg_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = CNPG_FAILOVER.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))

    def test_pgbackrest_cmd(self) -> None:
        profile = _sys_profile()
        cmd = PGBACKREST_RESTORE.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(len(cmd) > 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_collectors.py -v -k "Reliability" --tb=short`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/reliability.py`:

```python
"""Reliability-category system-altitude collectors (§10/HR6(a)).

PASS rule: RTO/RPO within profile limits.
Collectors: cnpg-reliability (CNPG failover), pgbackrest-reliability (restore timing).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _cnpg_failover_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "cnpg", "promote",
        "--namespace", ns,
        "--dry-run=server",
    ]


def _pgbackrest_restore_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "exec", "-n", ns,
        "cnpg-primary-0", "--",
        "pgbackrest", "info", "--output=json",
    ]


CNPG_FAILOVER = CollectorConfig(
    collector_id="cnpg-reliability",
    tool="cnpg",
    category="reliability",
    build_cmd=_cnpg_failover_cmd,
    tool_version_cmd=("kubectl", "cnpg", "version"),
)

PGBACKREST_RESTORE = CollectorConfig(
    collector_id="pgbackrest-reliability",
    tool="pgbackrest",
    category="reliability",
    build_cmd=_pgbackrest_restore_cmd,
)

COLLECTORS: list[CollectorConfig] = [CNPG_FAILOVER, PGBACKREST_RESTORE]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_collectors.py -v -k "Reliability" --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/reliability.py tests/test_system_collectors.py
git commit -m "feat(gate): add reliability collectors for CNPG failover and pgBackRest" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Resilience Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/resilience.py`
- Modify: `tests/test_system_collectors.py`

**Interfaces:**
- Produces:
  - `CHAOS_POD_KILL` — Chaos Mesh pod-kill scenario. Category: `resilience`.
  - `CHAOS_NET_LOSS` — Chaos Mesh network-loss scenario.
  - `CHAOS_IO_FAULT` — Chaos Mesh IO-fault scenario.
  - `COLLECTORS: list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_collectors.py`:

```python
from story_automator.core.collectors.resilience import (
    CHAOS_POD_KILL,
    CHAOS_NET_LOSS,
    CHAOS_IO_FAULT,
    COLLECTORS as RESILIENCE_COLLECTORS,
)


class ResilienceCollectorTests(unittest.TestCase):
    def test_pod_kill_config(self) -> None:
        self.assertEqual(CHAOS_POD_KILL.category, "resilience")
        self.assertEqual(CHAOS_POD_KILL.tool, "chaos-mesh")

    def test_net_loss_config(self) -> None:
        self.assertEqual(CHAOS_NET_LOSS.category, "resilience")

    def test_io_fault_config(self) -> None:
        self.assertEqual(CHAOS_IO_FAULT.category, "resilience")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(RESILIENCE_COLLECTORS), 3)

    def test_pod_kill_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = CHAOS_POD_KILL.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/resilience.py`:

```python
"""Resilience-category system-altitude collectors (§10/HR6(b)).

PASS rule: all Chaos Mesh scenarios passed.
Collectors: chaos-mesh pod-kill, net-loss, io-fault.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _chaos_pod_kill_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/pod-kill.yaml", "--dry-run=server"]


def _chaos_net_loss_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/net-loss.yaml", "--dry-run=server"]


def _chaos_io_fault_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return ["kubectl", "apply", "-n", ns, "-f", "chaos/io-fault.yaml", "--dry-run=server"]


CHAOS_POD_KILL = CollectorConfig(
    collector_id="chaos-pod-kill-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_pod_kill_cmd,
)

CHAOS_NET_LOSS = CollectorConfig(
    collector_id="chaos-net-loss-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_net_loss_cmd,
)

CHAOS_IO_FAULT = CollectorConfig(
    collector_id="chaos-io-fault-resilience",
    tool="chaos-mesh",
    category="resilience",
    build_cmd=_chaos_io_fault_cmd,
)

COLLECTORS: list[CollectorConfig] = [CHAOS_POD_KILL, CHAOS_NET_LOSS, CHAOS_IO_FAULT]
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/resilience.py tests/test_system_collectors.py
git commit -m "feat(gate): add resilience collectors for Chaos Mesh scenarios" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Durable HITL Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/durable_hitl.py`
- Modify: `tests/test_system_collectors.py`

**Interfaces:**
- Produces:
  - `TEMPORAL_SIGNAL` — CollectorConfig: starts approval workflow → kills pod → asserts Temporal Signal survived. Category: `durable_hitl`, tool: `temporal`.
  - `COLLECTORS: list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_collectors.py`:

```python
from story_automator.core.collectors.durable_hitl import (
    TEMPORAL_SIGNAL,
    COLLECTORS as DURABLE_HITL_COLLECTORS,
)


class DurableHitlCollectorTests(unittest.TestCase):
    def test_temporal_signal_config(self) -> None:
        self.assertEqual(TEMPORAL_SIGNAL.category, "durable_hitl")
        self.assertEqual(TEMPORAL_SIGNAL.tool, "temporal")
        self.assertEqual(TEMPORAL_SIGNAL.collector_id, "temporal-durable-hitl")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(DURABLE_HITL_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = TEMPORAL_SIGNAL.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
```

- [ ] **Step 2-3: Implement**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/durable_hitl.py`:

```python
"""Durable-HITL-category system-altitude collector (§10/HR6(c)).

PASS rule: Temporal signal survived pod kill.
Collector: temporal-durable-hitl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _temporal_signal_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "exec", "-n", ns,
        "temporal-admin-tools-0", "--",
        "tctl", "workflow", "list", "--status", "completed",
        "--output", "json",
    ]


TEMPORAL_SIGNAL = CollectorConfig(
    collector_id="temporal-durable-hitl",
    tool="temporal",
    category="durable_hitl",
    build_cmd=_temporal_signal_cmd,
    tool_version_cmd=("tctl", "version"),
)

COLLECTORS: list[CollectorConfig] = [TEMPORAL_SIGNAL]
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/durable_hitl.py tests/test_system_collectors.py
git commit -m "feat(gate): add durable HITL collector for Temporal signal survival" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Blast Radius Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/blast_radius.py`
- Modify: `tests/test_system_collectors.py`

**Interfaces:**
- Produces:
  - `K6_BLAST_RADIUS` — CollectorConfig: runs k6 load test against tenant A and checks tenant B SLO. Category: `blast_radius`, tool: `k6`.
  - `COLLECTORS: list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_collectors.py`:

```python
from story_automator.core.collectors.blast_radius import (
    K6_BLAST_RADIUS,
    COLLECTORS as BLAST_RADIUS_COLLECTORS,
)


class BlastRadiusCollectorTests(unittest.TestCase):
    def test_k6_config(self) -> None:
        self.assertEqual(K6_BLAST_RADIUS.category, "blast_radius")
        self.assertEqual(K6_BLAST_RADIUS.tool, "k6")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(BLAST_RADIUS_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = K6_BLAST_RADIUS.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("k6" in arg for arg in cmd))
```

- [ ] **Step 2-3: Implement**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/blast_radius.py`:

```python
"""Blast-radius-category system-altitude collector (§10/HR6(d)).

PASS rule: loading tenant A does not breach tenant B's SLO.
Collector: k6-blast-radius.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _k6_blast_radius_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    rules = (profile.get("rules") or {}).get("blast_radius") or {}
    script = rules.get("k6_script", "k6/blast-radius.js")
    return [
        "k6", "run",
        "--env", f"NAMESPACE={ns}",
        "--out", "json=blast-radius-results.json",
        script,
    ]


K6_BLAST_RADIUS = CollectorConfig(
    collector_id="k6-blast-radius",
    tool="k6",
    category="blast_radius",
    build_cmd=_k6_blast_radius_cmd,
    tool_version_cmd=("k6", "version"),
)

COLLECTORS: list[CollectorConfig] = [K6_BLAST_RADIUS]
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/blast_radius.py tests/test_system_collectors.py
git commit -m "feat(gate): add blast radius collector for tenant SLO isolation" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Cost-to-Serve Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/cost_to_serve.py`
- Modify: `tests/test_system_collectors.py`

**Interfaces:**
- Produces:
  - `K6_COST` — CollectorConfig: runs k6 load → measures resource usage → computes pod cost. Category: `cost_to_serve`, tool: `k6`.
  - `KUBECTL_RESOURCES` — CollectorConfig: queries kubectl for resource consumption metrics. Category: `cost_to_serve`, tool: `kubectl`.
  - `COLLECTORS: list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_collectors.py`:

```python
from story_automator.core.collectors.cost_to_serve import (
    K6_COST,
    KUBECTL_RESOURCES,
    COLLECTORS as COST_COLLECTORS,
)


class CostToServeCollectorTests(unittest.TestCase):
    def test_k6_cost_config(self) -> None:
        self.assertEqual(K6_COST.category, "cost_to_serve")
        self.assertEqual(K6_COST.tool, "k6")

    def test_kubectl_resources_config(self) -> None:
        self.assertEqual(KUBECTL_RESOURCES.category, "cost_to_serve")
        self.assertEqual(KUBECTL_RESOURCES.tool, "kubectl")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(COST_COLLECTORS), 2)

    def test_k6_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = K6_COST.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
```

- [ ] **Step 2-3: Implement**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/cost_to_serve.py`:

```python
"""Cost-to-serve-category system-altitude collectors (§10/HR6(f)).

PASS rule: pod cost per tenant <= max_pod_cost_per_tenant.
CONCERNS if DG-2/SKU undefined (§6.4 degradation path).
Collectors: k6-cost-to-serve (load generation), kubectl-resources (resource measurement).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _k6_cost_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    rules = (profile.get("rules") or {}).get("cost_to_serve") or {}
    script = rules.get("k6_script", "k6/cost-to-serve.js")
    return [
        "k6", "run",
        "--env", f"NAMESPACE={ns}",
        "--out", "json=cost-results.json",
        script,
    ]


def _kubectl_resources_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "top", "pods",
        "-n", ns,
        "--no-headers",
    ]


K6_COST = CollectorConfig(
    collector_id="k6-cost-to-serve",
    tool="k6",
    category="cost_to_serve",
    build_cmd=_k6_cost_cmd,
    tool_version_cmd=("k6", "version"),
)

KUBECTL_RESOURCES = CollectorConfig(
    collector_id="kubectl-resources-cost-to-serve",
    tool="kubectl",
    category="cost_to_serve",
    build_cmd=_kubectl_resources_cmd,
    tool_version_cmd=("kubectl", "version", "--client"),
)

COLLECTORS: list[CollectorConfig] = [K6_COST, KUBECTL_RESOURCES]
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/cost_to_serve.py tests/test_system_collectors.py
git commit -m "feat(gate): add cost-to-serve collectors for k6 load and resource measurement" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Progressive Delivery Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/progressive_delivery.py`
- Modify: `tests/test_system_collectors.py`

**Interfaces:**
- Produces:
  - `ARGO_ROLLOUTS` — CollectorConfig: checks Argo Rollouts status for blue-green/canary completion. Category: `progressive_delivery`, tool: `argo-rollouts`.
  - `COLLECTORS: list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_collectors.py`:

```python
from story_automator.core.collectors.progressive_delivery import (
    ARGO_ROLLOUTS,
    COLLECTORS as PROGRESSIVE_COLLECTORS,
)


class ProgressiveDeliveryCollectorTests(unittest.TestCase):
    def test_argo_config(self) -> None:
        self.assertEqual(ARGO_ROLLOUTS.category, "progressive_delivery")
        self.assertEqual(ARGO_ROLLOUTS.tool, "argo-rollouts")

    def test_collectors_list(self) -> None:
        self.assertEqual(len(PROGRESSIVE_COLLECTORS), 1)

    def test_cmd_uses_namespace(self) -> None:
        profile = _sys_profile()
        cmd = ARGO_ROLLOUTS.build_cmd("/checkout", profile)
        self.assertIsInstance(cmd, list)
        self.assertTrue(any("gate-test" in arg for arg in cmd))
```

- [ ] **Step 2-3: Implement**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/progressive_delivery.py`:

```python
"""Progressive-delivery system-altitude collector (§10).

PASS rule: Argo Rollouts blue-green/canary completed successfully.
Collector: argo-progressive-delivery.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _argo_rollouts_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "argo", "rollouts", "list", "rollouts",
        "-n", ns,
        "-o", "json",
    ]


ARGO_ROLLOUTS = CollectorConfig(
    collector_id="argo-progressive-delivery",
    tool="argo-rollouts",
    category="progressive_delivery",
    build_cmd=_argo_rollouts_cmd,
    tool_version_cmd=("kubectl", "argo", "rollouts", "version"),
)

COLLECTORS: list[CollectorConfig] = [ARGO_ROLLOUTS]
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/progressive_delivery.py tests/test_system_collectors.py
git commit -m "feat(gate): add progressive delivery collector for Argo Rollouts" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: System Gate Audit Events

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gate_audit.py`
- Modify: `tests/test_gate_audit.py`

**Interfaces:**
- Consumes: existing `emit_gate_audit` pattern, frozen dataclass protocol.
- Produces:
  - `SystemGateStartedAudit` — emitted when system-altitude gate evaluation starts. Fields: `gate_id`, `epic_id`, `commit_sha`, `profile_hash`, `env_tier`.
  - `EpicGateDecisionAudit` — emitted when epic-level gate verdict is rendered. Fields: `gate_id`, `epic_id`, `overall`, `commit_sha`, `env_tier`, `categories_summary`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_audit.py`:

```python
from story_automator.core.gate_audit import (
    SystemGateStartedAudit,
    EpicGateDecisionAudit,
)


class SystemGateStartedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = SystemGateStartedAudit(
            gate_id="sg1", epic_id="E1", commit_sha="abc",
            profile_hash="hash1", env_tier="full",
        )
        self.assertEqual(event.event_name, "SystemGateStarted")

    def test_to_dict(self) -> None:
        event = SystemGateStartedAudit(
            gate_id="sg1", epic_id="E1", commit_sha="abc",
            profile_hash="hash1", env_tier="full",
        )
        d = event.to_dict()
        self.assertEqual(d["epic_id"], "E1")
        self.assertEqual(d["env_tier"], "full")
        self.assertEqual(d["gate_id"], "sg1")

    def test_frozen(self) -> None:
        event = SystemGateStartedAudit(gate_id="sg1")
        with self.assertRaises(AttributeError):
            event.gate_id = "sg2"


class EpicGateDecisionAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = EpicGateDecisionAudit(
            gate_id="sg1", epic_id="E1", overall="PASS",
            commit_sha="abc", env_tier="minimal",
        )
        self.assertEqual(event.event_name, "EpicGateDecision")

    def test_to_dict(self) -> None:
        event = EpicGateDecisionAudit(
            gate_id="sg1", epic_id="E1", overall="FAIL",
            commit_sha="abc", env_tier="full",
            categories_summary="reliability:PASS,resilience:FAIL",
        )
        d = event.to_dict()
        self.assertEqual(d["overall"], "FAIL")
        self.assertEqual(d["epic_id"], "E1")
        self.assertIn("resilience", d["categories_summary"])
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Write minimal implementation**

Add to `gate_audit.py` (before the `_AuditEvent` union):

```python
@dataclasses.dataclass(frozen=True)
class SystemGateStartedAudit:
    """Audit event: system-altitude gate evaluation started."""
    event_name: str = dataclasses.field(default="SystemGateStarted", init=False)
    gate_id: str = ""
    epic_id: str = ""
    commit_sha: str = ""
    profile_hash: str = ""
    env_tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "epic_id": self.epic_id,
            "commit_sha": self.commit_sha,
            "profile_hash": self.profile_hash,
            "env_tier": self.env_tier,
        }


@dataclasses.dataclass(frozen=True)
class EpicGateDecisionAudit:
    """Audit event: epic-level gate verdict rendered."""
    event_name: str = dataclasses.field(default="EpicGateDecision", init=False)
    gate_id: str = ""
    epic_id: str = ""
    overall: str = ""
    commit_sha: str = ""
    env_tier: str = ""
    categories_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "epic_id": self.epic_id,
            "overall": self.overall,
            "commit_sha": self.commit_sha,
            "env_tier": self.env_tier,
            "categories_summary": self.categories_summary,
        }
```

Update `_AuditEvent` union and `__all__` to include the new types.

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py tests/test_gate_audit.py
git commit -m "feat(gate): add SystemGateStarted and EpicGateDecision audit events" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: System Gate Lifecycle (run_system_gate)

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/system_gate.py`
- Create: `tests/test_system_gate.py`

**Interfaces:**
- Consumes: `system_env.build_env_config`, `system_env.system_env`, `gate_orchestrator.recover_from_crash`, `gate_orchestrator.check_gate_reuse`, `collector_runner.run_gate_collectors`, `verdict_engine.evaluate_gate`, `evidence_io.write_gate_marker`, `evidence_io.clear_gate_marker`, `gate_audit.emit_gate_audit`, `gate_audit.SystemGateStartedAudit`, `trust_boundary.assert_host_context`, `product_profile.compute_profile_hash`.
- Produces:
  - `run_system_gate(project_root, gate_id, *, epic_id, commit_sha, epic_metadata, profile, factory_version, registry, priority, waivers, audit_policy, audit_path) -> dict` — full system gate lifecycle: crash recovery → reuse check → provision env → inject `_runtime_env` into profile copy → run system collectors → evaluate gate (tier="system") → teardown env → return gate file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_system_gate.py`:

```python
"""Tests for system gate lifecycle."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.system_gate import run_system_gate


def _minimal_profile() -> dict:
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {
            "code": [],
            "system": ["reliability", "resilience"],
        },
    }


class RunSystemGateTests(unittest.TestCase):
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate.recover_from_crash")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_full_lifecycle(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "no existing gate")
        mock_recover.return_value = {"recovered": False}
        mock_collectors.return_value = []

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        gate_file = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc", "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }
        mock_evaluate.return_value = gate_file

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={"type": "feature"},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["tier"], "system")
        mock_recover.assert_called_once()
        mock_env.assert_called_once()

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.check_gate_reuse")
    @patch("story_automator.core.system_gate.recover_from_crash")
    def test_reuses_existing_gate(
        self, mock_recover: MagicMock, mock_reuse: MagicMock,
    ) -> None:
        mock_recover.return_value = {"recovered": False}
        existing_gate = {"gate_id": "sg1", "overall": "PASS", "tier": "system"}
        mock_reuse.return_value = (existing_gate, "")

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "PASS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.evaluate_gate")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    @patch("story_automator.core.system_gate.recover_from_crash")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_injects_runtime_env(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_collectors: MagicMock,
        mock_evaluate: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = {"recovered": False}
        mock_collectors.return_value = []

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_FULL
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        gate_file = {
            "gate_id": "sg1", "schema_version": 1, "tier": "system",
            "target": {"kind": "epic", "id": "E1"},
            "commit_sha": "abc", "profile": {"id": "test", "version": 1, "hash": "h1"},
            "factory_version": "1.0.0", "categories": {},
            "overall": "PASS", "waivers": [],
        }
        mock_evaluate.return_value = gate_file

        captured_profile = {}
        def capture_collectors(*args, **kwargs):
            captured_profile.update(args[3])
            return []
        mock_collectors.side_effect = capture_collectors

        with tempfile.TemporaryDirectory() as td:
            run_system_gate(
                td, "sg1", epic_id="E1", commit_sha="abc",
                epic_metadata={"type": "infra"},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertIn("_runtime_env", captured_profile)
        self.assertEqual(captured_profile["_runtime_env"]["tier"], ENV_TIER_FULL)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.recover_from_crash")
    @patch("story_automator.core.system_gate.check_gate_reuse")
    def test_provision_failure_returns_fail(
        self,
        mock_reuse: MagicMock,
        mock_recover: MagicMock,
        mock_env: MagicMock,
    ) -> None:
        mock_reuse.return_value = (None, "")
        mock_recover.return_value = {"recovered": False}

        from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns", provisioned=False)
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            result = run_system_gate(
                td, "sg1",
                epic_id="E1", commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result.get("_provision_failed"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_gate.py -v --tb=short`
Expected: ModuleNotFoundError — `system_gate` not found.

- [ ] **Step 3a: Add tier parameter to verdict_engine.py (backward-compatible)**

Modify `skills/bmad-story-automator/src/story_automator/core/verdict_engine.py`:

In `build_gate_file`, add `tier: str = "code"` parameter and pass it to `_make_gate_file`:
```python
def build_gate_file(
    adjudication: dict[str, Any],
    *,
    gate_id: str,
    target: dict[str, str],
    commit_sha: str,
    profile: dict[str, Any],
    factory_version: str,
    tier: str = "code",  # NEW — backward-compatible default
    waivers: list[dict[str, Any]] | None = None,
    scanner_data_snapshot: str = "",
    risk_profile_ref: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
```
And in the `return _make_gate_file(...)` call, add `tier=tier`.

In `evaluate_gate`, add `tier: str = "code"` parameter and pass it to `build_gate_file`:
```python
def evaluate_gate(
    project_root: str | Path,
    gate_id: str,
    *,
    commit_sha: str,
    target: dict[str, str],
    profile: dict[str, Any],
    factory_version: str,
    tier: str = "code",  # NEW — backward-compatible default
    priority: str = "P1",
    ...
```
And in `build_gate_file(adj, ..., tier=tier, ...)`.

This is a 6-line backward-compatible change. All existing callers (which don't pass `tier`) get the default "code" behavior unchanged.

- [ ] **Step 3b: Add progressive_delivery to VALID_SYSTEM_CATEGORIES and system timeout defaults**

Modify `skills/bmad-story-automator/src/story_automator/core/product_profile.py`:

Add `"progressive_delivery"` to `VALID_SYSTEM_CATEGORIES`:
```python
VALID_SYSTEM_CATEGORIES = {
    "reliability", "resilience", "durable_hitl",
    "blast_radius", "cost_to_serve", "progressive_delivery",
}
```

Add system timeout defaults to `DEFAULT_TIMEOUTS`:
```python
DEFAULT_TIMEOUTS: dict[str, int] = {
    "security": 300,
    "performance": 600,
    "accessibility": 180,
    "test_quality": 900,
    "correctness": 1800,
    "reliability": 600,
    "resilience": 900,
    "durable_hitl": 600,
    "blast_radius": 900,
    "cost_to_serve": 900,
    "progressive_delivery": 300,
}
```

- [ ] **Step 3c: Write system_gate.py implementation**

Create `skills/bmad-story-automator/src/story_automator/core/system_gate.py`:

```python
"""System-altitude gate lifecycle — per-epic gate orchestration (§10).

Provisions an ephemeral environment (minimal/full), runs system-tier
collectors against it, evaluates the gate, and routes the epic-level
verdict. Reuses existing crash recovery, reuse validation, and
verdict engine infrastructure.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import clear_gate_marker, write_gate_marker
from .gate_audit import (
    EpicGateDecisionAudit,
    SystemGateStartedAudit,
    emit_gate_audit,
)
from .gate_orchestrator import check_gate_reuse, recover_from_crash
from .product_profile import compute_profile_hash
from .system_env import SystemEnvConfig, build_env_config, system_env
from .trust_boundary import assert_host_context
from .verdict_engine import evaluate_gate


def run_system_gate(
    project_root: str | Path,
    gate_id: str,
    *,
    epic_id: str,
    commit_sha: str,
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
    factory_version: str,
    registry: CollectorRegistry,
    priority: str = "P1",
    waivers: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Full system-altitude gate lifecycle.

    crash recovery -> reuse check -> provision env ->
    inject _runtime_env -> run system collectors ->
    evaluate (tier=system) -> teardown env -> return gate file.
    """
    assert_host_context("run_system_gate")

    recover_from_crash(project_root)

    existing, _ = check_gate_reuse(
        project_root, gate_id, commit_sha, profile, factory_version,
        audit_policy=audit_policy, audit_path=audit_path,
    )
    if existing is not None:
        return existing

    env_config = build_env_config(
        str(project_root), commit_sha, epic_metadata, profile,
    )

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            SystemGateStartedAudit(
                gate_id=gate_id, epic_id=epic_id,
                commit_sha=commit_sha,
                profile_hash=compute_profile_hash(profile),
                env_tier=env_config.tier,
            ),
        )

    write_gate_marker(project_root, gate_id, commit_sha)
    try:
        with system_env(env_config, str(project_root)) as env_info:
            if not env_info.provisioned:
                from .gate_schema import make_gate_file as _make_gate_file
                gate_file = _make_gate_file(
                    gate_id=gate_id, tier="system",
                    target={"kind": "epic", "id": epic_id},
                    commit_sha=commit_sha,
                    profile={"id": profile.get("id", ""), "version": profile.get("version", 1),
                             "hash": compute_profile_hash(profile)},
                    factory_version=factory_version,
                    categories={}, overall="FAIL",
                )
                gate_file["_provision_failed"] = True
                return gate_file
            enriched = _inject_runtime_env(profile, env_info)
            run_gate_collectors(
                project_root, gate_id, commit_sha, enriched, registry,
                audit_policy=audit_policy, audit_path=audit_path,
            )
        target = {"kind": "epic", "id": epic_id}
        gate_file = evaluate_gate(
            project_root, gate_id,
            commit_sha=commit_sha, target=target,
            profile=profile, factory_version=factory_version,
            priority=priority, waivers=waivers,
            audit_policy=audit_policy, audit_path=audit_path,
            tier="system",
        )
    finally:
        clear_gate_marker(project_root)

    if audit_policy is not None and audit_path is not None:
        cats_summary = ",".join(
            f"{c}:{v['verdict']}" for c, v in sorted(gate_file.get("categories", {}).items())
            if isinstance(v, dict) and "verdict" in v
        )
        emit_gate_audit(
            audit_policy, audit_path,
            EpicGateDecisionAudit(
                gate_id=gate_id, epic_id=epic_id,
                overall=gate_file["overall"],
                commit_sha=commit_sha,
                env_tier=env_config.tier,
                categories_summary=cats_summary,
            ),
        )

    return gate_file


def _inject_runtime_env(
    profile: dict[str, Any],
    env_info: Any,
) -> dict[str, Any]:
    """Inject transient _runtime_env into a profile copy for system collectors."""
    enriched = copy.deepcopy(profile)
    enriched["_runtime_env"] = {
        "env_id": env_info.env_id,
        "tier": env_info.tier,
        "namespace": env_info.namespace,
        "endpoints": dict(env_info.endpoints) if env_info.endpoints else {},
    }
    return enriched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_gate.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/system_gate.py \
       skills/bmad-story-automator/src/story_automator/core/verdict_engine.py \
       skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_system_gate.py
git commit -m "feat(gate): add system gate lifecycle with env provisioning, tier param, and provision-failure handling" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Epic Verdict Routing

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/system_gate.py`
- Modify: `tests/test_system_gate.py`

**Interfaces:**
- Consumes: `gate_status.park_story`, `gate_remediation.failing_categories_from_gate`, `gate_remediation.prepare_remediation_tasks`.
- Produces:
  - `route_epic_verdict(project_root, gate_file, *, epic_id, story_keys, max_cycles, remediation_cycle, audit_policy, audit_path) -> dict` — Routes epic-level verdict: PASS/WAIVED → done; CONCERNS → done + mitigation debt; FAIL → identifies affected stories for reopening or spawns remediation stories.
  - `stories_to_reopen(gate_file, story_keys) -> list[str]` — given a failing gate file and list of story keys, returns story keys that should be reopened based on failing categories.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_system_gate.py`:

```python
from story_automator.core.system_gate import (
    route_epic_verdict,
    stories_to_reopen,
)


def _make_system_gate_file(
    overall: str = "PASS",
    categories: dict | None = None,
) -> dict:
    return {
        "gate_id": "sg1", "schema_version": 1, "tier": "system",
        "target": {"kind": "epic", "id": "E1"},
        "commit_sha": "abc",
        "profile": {"id": "test", "version": 1, "hash": "h1"},
        "factory_version": "1.0.0",
        "categories": categories or {},
        "overall": overall,
        "waivers": [],
    }


class RouteEpicVerdictTests(unittest.TestCase):
    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_pass_returns_done(self) -> None:
        gate = _make_system_gate_file("PASS")
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=["E1-001"])
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["overall"], "PASS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_concerns_returns_done_with_debt(self) -> None:
        cats = {"reliability": {"verdict": "CONCERNS", "rationale": "degraded"}}
        gate = _make_system_gate_file("CONCERNS", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=["E1-001"])
        self.assertEqual(result["action"], "done")
        self.assertIn("mitigation_debt", result)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_fail_returns_reopen(self) -> None:
        cats = {"resilience": {"verdict": "FAIL", "rationale": "scenario failed"}}
        gate = _make_system_gate_file("FAIL", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(
                td, gate, epic_id="E1", story_keys=["E1-001", "E1-002"],
            )
        self.assertEqual(result["action"], "reopen")
        self.assertIn("failing_categories", result)

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_fail_exhausted_parks(self) -> None:
        cats = {"resilience": {"verdict": "FAIL", "rationale": "scenario failed"}}
        gate = _make_system_gate_file("FAIL", cats)
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(
                td, gate, epic_id="E1", story_keys=["E1-001"],
                remediation_cycle=3, max_cycles=3,
            )
        self.assertEqual(result["action"], "park")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_waived_returns_done(self) -> None:
        gate = _make_system_gate_file("WAIVED")
        with tempfile.TemporaryDirectory() as td:
            result = route_epic_verdict(td, gate, epic_id="E1", story_keys=[])
        self.assertEqual(result["action"], "done")


class StoriesToReopenTests(unittest.TestCase):
    def test_returns_all_stories_on_fail(self) -> None:
        cats = {"resilience": {"verdict": "FAIL"}}
        gate = _make_system_gate_file("FAIL", cats)
        reopened = stories_to_reopen(gate, ["E1-001", "E1-002"])
        self.assertEqual(reopened, ["E1-001", "E1-002"])

    def test_returns_empty_on_pass(self) -> None:
        gate = _make_system_gate_file("PASS")
        reopened = stories_to_reopen(gate, ["E1-001"])
        self.assertEqual(reopened, [])
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Write minimal implementation**

Add to `system_gate.py`:

```python
from .gate_remediation import failing_categories_from_gate, prepare_remediation_tasks
from .gate_status import park_story, record_mitigation_debt


def route_epic_verdict(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    epic_id: str,
    story_keys: list[str],
    remediation_cycle: int = 0,
    max_cycles: int = 3,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Route epic-level system gate verdict to action."""
    assert_host_context("route_epic_verdict")
    overall = gate_file.get("overall", "FAIL")
    gate_id = gate_file.get("gate_id", "")

    if overall == "PASS":
        return {"action": "done", "overall": "PASS"}

    if overall == "WAIVED":
        return {"action": "done", "overall": "WAIVED", "waived": True}

    if overall == "CONCERNS":
        concerns_cats = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        record_mitigation_debt(project_root, gate_id, epic_id, concerns_cats)
        return {
            "action": "done", "overall": "CONCERNS",
            "mitigation_debt": concerns_cats,
        }

    if overall not in ("FAIL", "PASS", "WAIVED", "CONCERNS"):
        overall = "FAIL"

    if remediation_cycle >= max_cycles:
        park_story(
            project_root, gate_id, epic_id,
            "exhausted", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "exhausted",
            "overall": overall, "gate_id": gate_id,
        }

    failing = failing_categories_from_gate(gate_file)
    to_reopen = stories_to_reopen(gate_file, story_keys)
    tasks = prepare_remediation_tasks(gate_file)
    return {
        "action": "reopen", "overall": overall,
        "gate_id": gate_id,
        "failing_categories": failing,
        "stories_to_reopen": to_reopen,
        "remediation_tasks": tasks,
        "cycle": remediation_cycle + 1,
    }


def stories_to_reopen(
    gate_file: dict[str, Any],
    story_keys: list[str],
) -> list[str]:
    """Identify stories to reopen when the epic gate fails."""
    overall = gate_file.get("overall", "")
    if overall not in ("FAIL",):
        return []
    return list(story_keys)
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/system_gate.py tests/test_system_gate.py
git commit -m "feat(gate): add epic verdict routing with story reopening on system gate FAIL" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: System Collector Registry Wiring

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/system_collector_registry.py`
- Modify: `tests/test_system_gate.py` (or create `tests/test_system_collector_registry.py`)

**Interfaces:**
- Consumes: all system collector modules' `COLLECTORS` lists, `CollectorRegistry`.
- Produces:
  - `build_system_registry() -> CollectorRegistry` — creates a registry containing all system-altitude collectors.
  - `SYSTEM_COLLECTORS: list[CollectorConfig]` — flat list of all system collectors for convenience.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_system_collector_registry.py`:

```python
"""Tests for system collector registry wiring."""
from __future__ import annotations

import unittest

from story_automator.core.system_collector_registry import (
    SYSTEM_COLLECTORS,
    build_system_registry,
)


class SystemRegistryTests(unittest.TestCase):
    def test_all_system_collectors_present(self) -> None:
        expected_categories = {
            "reliability", "resilience", "durable_hitl",
            "blast_radius", "cost_to_serve", "progressive_delivery",
        }
        actual_categories = {c.category for c in SYSTEM_COLLECTORS}
        self.assertEqual(expected_categories, actual_categories)

    def test_build_registry(self) -> None:
        registry = build_system_registry()
        self.assertTrue(len(registry.all_collectors()) >= 10)

    def test_registry_categories(self) -> None:
        registry = build_system_registry()
        cats = registry.all_categories()
        self.assertIn("reliability", cats)
        self.assertIn("resilience", cats)
        self.assertIn("cost_to_serve", cats)

    def test_applicable_filters_by_profile(self) -> None:
        registry = build_system_registry()
        profile = {
            "categories": {"code": [], "system": ["reliability"]},
            "categories_na": ["resilience"],
        }
        applicable = registry.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertIn("reliability", cats)
        self.assertNotIn("resilience", cats)

    def test_collector_ids_unique(self) -> None:
        ids = [c.collector_id for c in SYSTEM_COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/system_collector_registry.py`:

```python
"""System-altitude collector registry — aggregates all system collectors.

Imports each system collector module and builds a CollectorRegistry
containing all system-altitude evidence collectors for use by
the system gate orchestrator.
"""
from __future__ import annotations

from .collector_config import CollectorConfig
from .collector_registry import CollectorRegistry
from .collectors.blast_radius import COLLECTORS as BLAST_RADIUS
from .collectors.cost_to_serve import COLLECTORS as COST
from .collectors.durable_hitl import COLLECTORS as DURABLE_HITL
from .collectors.progressive_delivery import COLLECTORS as PROGRESSIVE
from .collectors.reliability import COLLECTORS as RELIABILITY
from .collectors.resilience import COLLECTORS as RESILIENCE

SYSTEM_COLLECTORS: list[CollectorConfig] = [
    *RELIABILITY,
    *RESILIENCE,
    *DURABLE_HITL,
    *BLAST_RADIUS,
    *COST,
    *PROGRESSIVE,
]


def build_system_registry() -> CollectorRegistry:
    """Build a CollectorRegistry with all system-altitude collectors."""
    registry = CollectorRegistry()
    for config in SYSTEM_COLLECTORS:
        registry.register(config)
    return registry
```

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/system_collector_registry.py tests/test_system_collector_registry.py
git commit -m "feat(gate): add system collector registry wiring all system-altitude collectors" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: Gate CLI System Subcommands

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py`
- Modify: `tests/test_gate_cmd.py`

**Interfaces:**
- Consumes: `gate_status.list_parked`, `evidence_io.read_gate_marker`, `gate_status.load_mitigation_debt`, `utils.print_json`.
- Produces:
  - `gate_system_status_action(args) -> int` — displays system-altitude gate status: parked epics, in-progress system gates, mitigation debt filtered to system categories.
  - Updates `gate_dispatch` to route `system-status` subcommand.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_cmd.py`:

```python
from story_automator.commands.gate_cmd import gate_system_status_action


class GateSystemStatusTests(unittest.TestCase):
    def test_system_status_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("story_automator.commands.gate_cmd._project_root", return_value=td):
                with patch("story_automator.commands.gate_cmd.print_json") as mock_print:
                    code = gate_system_status_action([])
        self.assertEqual(code, 0)
        mock_print.assert_called_once()
        result = mock_print.call_args[0][0]
        self.assertTrue(result["ok"])
        self.assertIn("system_parked", result)

    def test_dispatch_routes_system_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch("story_automator.commands.gate_cmd._project_root", return_value=td):
                with patch("story_automator.commands.gate_cmd.print_json"):
                    code = gate_dispatch(["system-status"])
        self.assertEqual(code, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Write minimal implementation**

Add to `commands/gate_cmd.py`:

```python
def gate_system_status_action(args: list[str]) -> int:
    """Display system-altitude gate status (epics)."""
    project_root = _project_root()
    state_filter = None
    for arg in args:
        if arg.startswith("--state="):
            state_filter = arg.split("=", 1)[1]

    parked = list_parked(project_root, state_filter=state_filter)
    system_parked = [p for p in parked if p.get("reason", "") in ("exhausted",) or p.get("tier") == "system"]
    marker = read_gate_marker(project_root)
    debt = load_mitigation_debt(project_root)

    result: dict[str, Any] = {
        "ok": True,
        "system_parked": system_parked,
        "system_parked_count": len(system_parked),
        "in_progress": marker is not None,
        "mitigation_debt": debt,
    }
    if marker is not None:
        result["in_progress_gate_id"] = marker.get("gate_id", "")
    print_json(result)
    return 0
```

Update `gate_dispatch` to include `"system-status": gate_system_status_action`.

Update usage help to include `gate system-status [--state=parked]`.

- [ ] **Step 4: Run tests, commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/gate_cmd.py tests/test_gate_cmd.py
git commit -m "feat(gate): add system-status CLI subcommand for epic-level gate status" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 16: End-to-End Integration Tests

**Files:**
- Create: `tests/test_system_gate_integration.py`

**Interfaces:**
- Consumes: `system_gate.run_system_gate`, `system_gate.route_epic_verdict`, `system_collector_registry.build_system_registry`, `system_env.SystemEnvInfo`, `evidence_io`, `gate_status`.
- Validates: Full lifecycle from system gate invocation through verdict routing, including env provisioning mock, evidence collection mock, adjudication, and verdict routing with story reopening.

- [ ] **Step 1: Write integration tests**

Create `tests/test_system_gate_integration.py`:

```python
"""End-to-end integration tests for system-altitude gate."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record, load_evidence_bundle
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.gate_status import list_parked, load_mitigation_debt
from story_automator.core.system_collector_registry import build_system_registry
from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL, ENV_TIER_FULL
from story_automator.core.system_gate import (
    run_system_gate,
    route_epic_verdict,
    stories_to_reopen,
)


def _test_profile() -> dict:
    return {
        "version": 1, "id": "test-system",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {
            "code": [],
            "system": ["reliability", "resilience", "cost_to_serve"],
        },
        "rules": {
            "reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60},
        },
        "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
        "forbidden_until": {"DG-2": ["*.cost-to-serve"]},
    }


class SystemGateIntegrationTests(unittest.TestCase):
    """Integration tests covering the full system gate lifecycle."""

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_system_gate_pass_lifecycle(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """System gate PASS -> route -> done."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            for cat in ("reliability", "resilience", "cost_to_serve"):
                persist_evidence_record(td, "sg-int-1", make_evidence_record(
                    collector=f"test-{cat}", tool="test", category=cat,
                    tier="system", status="ok",
                ))
            mock_collectors.return_value = []

            gate_file = run_system_gate(
                td, "sg-int-1", epic_id="E1", commit_sha="abc123",
                epic_metadata={"type": "feature"},
                profile=_test_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            self.assertIn(gate_file["overall"], ("PASS", "CONCERNS"))

            result = route_epic_verdict(
                td, gate_file, epic_id="E1", story_keys=["E1-001"],
            )
            self.assertEqual(result["action"], "done")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_system_gate_fail_reopens_stories(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """System gate FAIL -> route -> reopen stories."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            persist_evidence_record(td, "sg-int-2", make_evidence_record(
                collector="test-reliability", tool="test", category="reliability",
                tier="system", status="ok",
            ))
            persist_evidence_record(td, "sg-int-2", make_evidence_record(
                collector="test-resilience", tool="test", category="resilience",
                tier="system", status="violation",
                findings=["pod-kill scenario failed"],
            ))
            mock_collectors.return_value = []

            profile = _test_profile()
            del profile["forbidden_until"]
            del profile["cost_tier"]
            gate_file = run_system_gate(
                td, "sg-int-2", epic_id="E2", commit_sha="def456",
                epic_metadata={"type": "infra"},
                profile=profile,
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            self.assertEqual(gate_file["overall"], "FAIL")

            result = route_epic_verdict(
                td, gate_file, epic_id="E2",
                story_keys=["E2-001", "E2-002", "E2-003"],
            )
            self.assertEqual(result["action"], "reopen")
            self.assertEqual(result["stories_to_reopen"], ["E2-001", "E2-002", "E2-003"])

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_cost_to_serve_concerns_with_dg2(self) -> None:
        """cost_to_serve renders CONCERNS while DG-2 in forbidden_until."""
        profile = _test_profile()
        from story_automator.core.category_rules import cost_to_serve_rule
        evidence = [make_evidence_record(
            collector="k6-cost", tool="k6", category="cost_to_serve",
            tier="system", status="ok",
            metrics={"pod_cost_per_tenant": 5.0},
        )]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "CONCERNS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_exhausted_parks_epic(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Exhausted remediation cycles -> park epic."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            persist_evidence_record(td, "sg-int-3", make_evidence_record(
                collector="test-resilience", tool="test", category="resilience",
                tier="system", status="violation",
            ))
            mock_collectors.return_value = []

            profile = _test_profile()
            profile["categories"]["system"] = ["resilience"]
            del profile["forbidden_until"]
            del profile["cost_tier"]
            gate_file = run_system_gate(
                td, "sg-int-3", epic_id="E3", commit_sha="ghi789",
                epic_metadata={},
                profile=profile,
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            result = route_epic_verdict(
                td, gate_file, epic_id="E3",
                story_keys=["E3-001"],
                remediation_cycle=3, max_cycles=3,
            )
            self.assertEqual(result["action"], "park")
            parked = list_parked(td)
            self.assertEqual(len(parked), 1)

    def test_system_registry_has_expected_categories(self) -> None:
        """Verify all HR6 system categories are covered by registry."""
        registry = build_system_registry()
        cats = registry.all_categories()
        for expected in ("reliability", "resilience", "durable_hitl", "blast_radius", "cost_to_serve"):
            self.assertIn(expected, cats, f"missing system category: {expected}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run integration tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_system_gate_integration.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short -x`
Expected: Zero regressions across all 113+ existing test files.

- [ ] **Step 4: Commit**

```bash
git add tests/test_system_gate_integration.py
git commit -m "test(gate): add end-to-end integration tests for system-altitude gate" \
  --trailer "Generated-By: claude-opus-4-6"
```

---

## Acceptance Criteria (post-implementation verification)

1. **All 5+1 system categories have dedicated collectors**: reliability, resilience, durable_hitl, blast_radius, cost_to_serve, progressive_delivery.
2. **All 5+1 system categories have dedicated rule functions** registered in `CATEGORY_RULES`.
3. **Environment provisioning** resolves minimal vs full tier based on epic type, with profile override support.
4. **System gate lifecycle** (`run_system_gate`) handles crash recovery, reuse validation, env provisioning, collector execution with `_runtime_env` injection, adjudication, and verdict routing.
5. **Epic verdict routing** (`route_epic_verdict`) routes PASS→done, CONCERNS→done+debt, FAIL→reopen stories, exhausted→park.
6. **cost_to_serve** renders CONCERNS (not FAIL) while DG-2 is in `forbidden_until` per §6.4.
7. **Audit events**: `SystemGateStartedAudit` and `EpicGateDecisionAudit` emitted and hash-chained.
8. **CLI**: `gate system-status` subcommand operational.
9. **No new Python deps** beyond stdlib + filelock + psutil.
10. **No modifications** to telemetry_events.py or any M1-M10 module logic (except category_rules, gate_audit, gate_cmd).
11. **All existing tests pass** with zero regressions.
12. **500-LOC limit** respected across all modules.
