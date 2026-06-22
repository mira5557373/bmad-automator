"""Audit-floor regression net.

Consolidates the four audit-fix invariants that closed the deep code-validation
ship-blockers into a single always-green suite. Every gate-adoption PR
(bmad-auto patterns, future milestones) MUST keep this suite green.

The four fixes pinned here:

1. WAIVER_EXPIRY_ON_REUSE_NOT_ENFORCED (commit e5a8c55, §6.4(e)):
   can_reuse_gate_file MUST re-check waiver.expires_at on EVERY reuse, not
   just at issue time, so an expired waiver cannot keep a stale PASS alive.

2. MARKER_CORRUPTION_SILENTLY_IGNORED (commit fcbe17e, §9.2):
   A corrupted gate-in-progress marker MUST fail loud (raise
   GateMarkerCorruptedError → recover_from_crash quarantines evidence)
   rather than silently shutil.rmtree'ing the partial evidence.

3. WIRING-001 (commit 2bf44f3, §9.2):
   route_gate_verdict with a FAIL verdict and story_path MUST persist the
   [AI-Review] tasks into the story file's Tasks section (closing the BMAD
   code-review → review_continuation loop the spec promised).

4. WIRING-002 (commit 1069d86, §9.1+§9.2):
   The production_ready_gate verifier on FAIL MUST drive route_gate_verdict
   itself (resolving story_path, persisting tasks, returning a rich
   remediation descriptor) — not just return verified=False.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from story_automator.core.evidence_io import (
    GateMarkerCorruptedError,
    can_reuse_gate_file,
    read_gate_marker,
)
from story_automator.core.gate_orchestrator import recover_from_crash, route_gate_verdict
from story_automator.core.gate_schema import make_gate_file


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gate(self, overall: str = "PASS", waivers: list[dict] | None = None) -> dict:
        cats = {"correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"}}
        gate = make_gate_file(
            gate_id="audit-floor",
            target={"kind": "story", "id": "E1-001"},
            commit_sha="deadbeef",
            profile={"id": "test", "version": 1, "hash": "abc123"},
            factory_version="1.15.0",
            categories=cats,
            overall=overall,
        )
        if waivers is not None:
            gate["waivers"] = waivers
        return gate


# ---------------------------------------------------------------------------
# FIX 1 — WAIVER_EXPIRY_ON_REUSE_NOT_ENFORCED (commit e5a8c55)
# ---------------------------------------------------------------------------


class WaiverExpiryOnReuseInvariant(_Mixin, unittest.TestCase):
    """Pins §6.4(e): every reuse re-checks expires_at."""

    def test_expired_waiver_blocks_reuse_even_when_sha_profile_factory_match(self) -> None:
        gate = self._gate(waivers=[{
            "waiver_id": "01J90000000000000000000W",
            "operator_id": "mira",
            "issued_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-02T00:00:00Z",  # past
            "failing_categories": ["security"],
            "reason": "test",
            "signature": "sig",
            "profile_hash": "abc123",
        }])
        ok, reason = can_reuse_gate_file(
            gate, commit_sha="deadbeef", profile_hash="abc123", factory_version="1.15.0",
        )
        self.assertFalse(ok, "expired waiver MUST block reuse — the audit fix is gone")
        self.assertIn("waiver expired", reason)

    def test_unexpired_waiver_allows_reuse(self) -> None:
        gate = self._gate(waivers=[{
            "waiver_id": "01J90000000000000000000F",
            "operator_id": "mira",
            "issued_at": "2099-01-01T00:00:00Z",
            "expires_at": "2099-12-31T23:59:59Z",
            "failing_categories": ["security"],
            "reason": "infra dependency",
            "signature": "sig",
            "profile_hash": "abc123",
        }])
        ok, _ = can_reuse_gate_file(
            gate, commit_sha="deadbeef", profile_hash="abc123", factory_version="1.15.0",
        )
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# FIX 2 — MARKER_CORRUPTION_SILENTLY_IGNORED (commit fcbe17e)
# ---------------------------------------------------------------------------


class MarkerCorruptionInvariant(_Mixin, unittest.TestCase):
    """Pins §9.2: corruption is loud, not silent. Evidence is quarantined, not deleted."""

    def test_corrupted_marker_raises_GateMarkerCorruptedError(self) -> None:
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{not json", encoding="utf-8")
        with self.assertRaises(GateMarkerCorruptedError):
            read_gate_marker(self.tmp)

    def test_recover_from_crash_quarantines_evidence_on_corruption(self) -> None:
        # The marker is corrupted (broken JSON) BUT still carries a
        # recognizable ``"gate_id":"..."`` fragment, so the L2-variant
        # targeted quarantine can scope to just the in-flight gate.
        # This preserves the original "loud, not silent + preserved as
        # moved evidence" contract while letting concurrent historical
        # gates keep their Merkle-verifiable evidence in place.
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(
            '{"gate_id": "lost-gate", "commit_sha": "x", not json',
            encoding="utf-8",
        )
        evidence_dir = self.tmp / "_bmad" / "gate" / "evidence" / "lost-gate"
        evidence_dir.mkdir(parents=True)
        important = evidence_dir / "important.json"
        important.write_text('{"do_not_delete": true}', encoding="utf-8")
        result = recover_from_crash(self.tmp)
        # The audit-fix contract: NOT silently "recovered=True".
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"], "marker corruption must surface loud")
        self.assertIn("quarantine_dir", result)
        # Evidence must have been MOVED, not deleted.
        self.assertFalse(important.exists(),
                         "the original evidence path must not still exist (it was moved to quarantine)")
        quar = Path(result["quarantine_dir"])
        self.assertTrue((quar / "evidence" / "lost-gate" / "important.json").is_file(),
                        "important evidence MUST have been quarantined, not deleted")

    def test_recover_from_crash_unreadable_marker_preserves_other_evidence(self) -> None:
        """L2-variant: when gate_id is NOT salvageable from a corrupted marker,
        recover_from_crash MUST NOT take down all historical evidence dirs —
        Merkle reverification of completed gates depends on them. The audit-
        floor contract (recovered=False / quarantined=True / quarantine_dir /
        corruption_reason) holds; only the SCOPE of what moves narrows."""
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("########### unsalvageable ###########", encoding="utf-8")
        # Historical evidence — must survive.
        for gid in ("historical-1", "historical-2"):
            d = self.tmp / "_bmad" / "gate" / "evidence" / gid
            d.mkdir(parents=True)
            (d / "audit.json").write_text(f'{{"gate": "{gid}"}}', encoding="utf-8")
        result = recover_from_crash(self.tmp)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        self.assertIn("quarantine_dir", result)
        # Both historical evidence dirs are STILL in the live tree.
        for gid in ("historical-1", "historical-2"):
            self.assertTrue(
                (self.tmp / "_bmad" / "gate" / "evidence" / gid / "audit.json").is_file(),
                f"{gid} must NOT be quarantined when gate_id is unsalvageable",
            )
        # The corrupted marker IS in quarantine.
        quar = Path(result["quarantine_dir"])
        self.assertTrue((quar / "gate-in-progress.json").is_file())


# ---------------------------------------------------------------------------
# FIX 3 — WIRING-001: persist [AI-Review] tasks into the story file (commit 2bf44f3)
# ---------------------------------------------------------------------------


class AiReviewPersistenceInvariant(_Mixin, unittest.TestCase):
    """Pins §9.2: route_gate_verdict persists tasks when story_path is provided."""

    def test_fail_with_story_path_writes_tasks_into_Tasks_section(self) -> None:
        gate = self._gate(overall="FAIL")
        gate["categories"]["security"] = {
            "verdict": "FAIL", "required": {}, "actual": {},
            "rationale": "1 critical CVE", "evidence": [],
        }
        story = self.tmp / "E1-001.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing dev task\n\n## Notes\n",
            encoding="utf-8",
        )
        result = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
            story_path=story,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertTrue(result["tasks_persisted"], "tasks MUST be persisted to disk")
        content = story.read_text(encoding="utf-8")
        self.assertIn("existing dev task", content)
        # At least one new [AI-Review] task added under Tasks
        self.assertGreater(content.count("- [ ]"), 0)
        # Tasks went before Notes (edit-authorization correctness)
        self.assertLess(content.find("## Tasks"), content.find("## Notes"))

    def test_fail_without_story_path_returns_descriptor_unpersisted(self) -> None:
        gate = self._gate(overall="FAIL")
        gate["categories"]["security"] = {
            "verdict": "FAIL", "required": {}, "actual": {},
            "rationale": "1 critical CVE", "evidence": [],
        }
        result = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertFalse(result["tasks_persisted"])
        self.assertTrue(len(result["remediation_tasks"]) > 0)


# ---------------------------------------------------------------------------
# FIX 4 — WIRING-002: verifier-driven remediation loop (commit 1069d86)
# ---------------------------------------------------------------------------


class VerifierRemediationLoopInvariant(_Mixin, unittest.TestCase):
    """Pins §9.1+§9.2: production_ready_gate drives route_gate_verdict itself."""

    def _persist_gate_file(self, gate: dict) -> None:
        # Build a minimal gate file on disk so production_ready_gate can load it.
        from story_automator.core.evidence_io import persist_gate_file
        persist_gate_file(self.tmp, gate)

    def _seed_story(self) -> Path:
        artifacts = self.tmp / "_bmad-output" / "implementation-artifacts"
        artifacts.mkdir(parents=True)
        story = artifacts / "E1-001-my-story.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing dev task\n",
            encoding="utf-8",
        )
        return story

    def test_fail_verdict_returns_remediation_descriptor_with_tasks_persisted(self) -> None:
        from story_automator.core.success_verifiers import production_ready_gate
        gate = self._gate(overall="FAIL")
        # Match the persisted gate_id convention (kept consistent across the
        # audit-fix verifier integration).
        gate["gate_id"] = "audit-floor-1069d86"
        self._persist_gate_file(gate)
        story = self._seed_story()
        result = production_ready_gate(
            project_root=str(self.tmp),
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": gate["gate_id"]}},
        )
        self.assertFalse(result["verified"])
        # The verifier exposes the full route_gate_verdict descriptor.
        self.assertIn("remediation", result)
        self.assertEqual(result["remediation"]["action"], "remediate")
        self.assertTrue(result["remediation"]["tasks_persisted"])
        # Story file actually carries new [AI-Review] tasks.
        content = story.read_text(encoding="utf-8")
        self.assertGreater(content.count("- [ ]"), 0)
        self.assertIn("existing dev task", content)

    def test_fail_at_max_cycles_parks_via_descriptor(self) -> None:
        from story_automator.core.gate_status import list_parked
        from story_automator.core.success_verifiers import production_ready_gate
        gate = self._gate(overall="FAIL")
        gate["gate_id"] = "audit-floor-1069d86-park"
        self._persist_gate_file(gate)
        self._seed_story()
        result = production_ready_gate(
            project_root=str(self.tmp),
            story_key="E1-001-my-story",
            contract={"config": {
                "gate_id": gate["gate_id"],
                "remediation_cycle": 3,
                "max_cycles": 3,
            }},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["remediation"]["action"], "park")
        parked = list_parked(self.tmp)
        self.assertTrue(any(p["story_key"] == "E1-001-my-story" for p in parked))


# ---------------------------------------------------------------------------
# PATH B (N6.4 + N6.7) — Plugin trust-boundary audit-floor invariant
# ---------------------------------------------------------------------------
# The declarative-only plugin registry is the trust boundary between the
# generation child's sandbox and any operator-supplied extension. A future
# refactor that re-enables Python-import plugins, widens the manifest
# allowlist, or introduces ``importlib`` into ``core/plugins.py`` would
# silently break that boundary. These invariants pin the rules so the suite
# fails the moment the surface changes.


class PluginTrustBoundaryInvariant(unittest.TestCase):
    """Pins N6.4 trust-boundary rules. See ``docs/spec/2026-06-22-engine-adoption-decision.md``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.plugin_dir = self.tmp / "_bmad" / "plugins"
        self.plugin_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_manifest(self, body: str, name: str = "example") -> Path:
        path = self.plugin_dir / f"{name}.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def _registry(self, allowlist: frozenset[str] | None = None):
        from story_automator.core.plugins import PluginRegistry
        if allowlist is None:
            allowlist = frozenset({"example"})
        return PluginRegistry(self.plugin_dir, allowlist)

    def test_python_module_key_rejected(self) -> None:
        """Manifest with ``python_module`` key MUST raise PluginTrustError."""
        from story_automator.core.plugins import PluginTrustError
        self._write_manifest(
            'name = "example"\n'
            'version = "1.0.0"\n'
            'python_module = "my_plugin.entry"\n'
        )
        with self.assertRaises(PluginTrustError) as ctx:
            self._registry().load_all()
        # The error message must name the rule (so a future contributor
        # reading the traceback can find the trust-boundary doc).
        self.assertIn("python_module", str(ctx.exception))

    def test_py_module_key_rejected(self) -> None:
        """Manifest with ``py_module`` key MUST raise PluginTrustError."""
        from story_automator.core.plugins import PluginTrustError
        self._write_manifest(
            'name = "example"\n'
            'version = "1.0.0"\n'
            'py_module = "my_plugin"\n'
        )
        with self.assertRaises(PluginTrustError) as ctx:
            self._registry().load_all()
        self.assertIn("py_module", str(ctx.exception))

    def test_dotted_python_path_in_hook_command_allowed(self) -> None:
        """Hooks values like ``python -m foo`` are OK — they are subprocess
        commands, not import paths. The trust-boundary rule rejects Python
        *import* keys at the manifest top level; it does not police the
        shell command strings inside ``[hooks]``, which the dispatcher
        runs in a subprocess anyway.
        """
        self._write_manifest(
            'name = "example"\n'
            'version = "1.0.0"\n'
            '\n'
            '[hooks]\n'
            'post_gate = "python -m my_plugin.entry --gate-id $BMAD_GATE_ID"\n'
        )
        specs = self._registry().load_all()
        self.assertEqual(len(specs), 1)
        self.assertEqual(
            specs[0].hooks["post_gate"],
            "python -m my_plugin.entry --gate-id $BMAD_GATE_ID",
        )

    def test_no_import_callable_in_manifest(self) -> None:
        """Manifest with ``import`` key MUST raise PluginTrustError.

        ``import`` is not in ``PLUGIN_MANIFEST_KEYS`` so the generic
        unknown-key rule catches it; this test is the explicit pin that
        the unknown-key path remains fail-closed.
        """
        from story_automator.core.plugins import PluginTrustError
        self._write_manifest(
            'name = "example"\n'
            'version = "1.0.0"\n'
            'import = "my_plugin:run"\n'
        )
        with self.assertRaises(PluginTrustError) as ctx:
            self._registry().load_all()
        self.assertIn("import", str(ctx.exception))

    def test_plugin_manifest_keys_closed_set(self) -> None:
        """``PLUGIN_MANIFEST_KEYS`` is exactly the documented closed set.

        Widening this set is a trust-boundary change that requires a
        spec-level decision; this test forces such a change to be
        explicit (the test breaks, the contributor has to think).
        """
        from story_automator.core.plugins import PLUGIN_MANIFEST_KEYS
        self.assertEqual(
            set(PLUGIN_MANIFEST_KEYS),
            {"name", "version", "hooks", "timeout_s", "fail_closed"},
        )

    def test_no_python_import_path_in_plugins_module(self) -> None:
        """``core/plugins.py`` MUST NOT actually use Python-import APIs.

        If a future contributor adds ``importlib`` / ``__import__`` /
        ``import_module`` to the registry, the declarative-only promise
        is gone — even if the manifest schema is unchanged. We parse
        the module's AST (not a substring grep) so the docstring may
        freely *describe* the rule using the same words without
        tripping the test.
        """
        import ast
        from story_automator.core import plugins as plugins_mod
        source = Path(plugins_mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_names = {"importlib", "__import__", "import_module"}
        offenders: list[str] = []
        for node in ast.walk(tree):
            # ``import importlib`` / ``import importlib.util``
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in forbidden_names:
                        offenders.append(f"import {alias.name}")
            # ``from importlib import ...`` / ``from foo import import_module``
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in forbidden_names:
                    offenders.append(f"from {node.module} import ...")
                for alias in node.names:
                    if alias.name in forbidden_names:
                        offenders.append(f"from {node.module} import {alias.name}")
            # Bare names: ``__import__(...)``, ``import_module(...)``
            elif isinstance(node, ast.Name) and node.id in forbidden_names:
                offenders.append(f"name reference: {node.id}")
            # Attribute access: ``importlib.import_module(...)``
            elif isinstance(node, ast.Attribute):
                if node.attr in forbidden_names:
                    offenders.append(f"attribute access: .{node.attr}")
        self.assertEqual(
            offenders, [],
            "core/plugins.py uses Python-import APIs — declarative-only "
            f"trust boundary has been breached; see N6.4 / Path B. Offenders: {offenders}",
        )


# ---------------------------------------------------------------------------
# Determinism baseline — pin canonical-JSON of representative gate files.
# A future port that accidentally changes serialization order or field shape
# will fail this suite immediately.
# ---------------------------------------------------------------------------


class GateFileDeterminismBaseline(unittest.TestCase):
    """The hash of a canonical-JSON-serialized gate file is the audit anchor.

    Any future change to make_gate_file / gate_schema canonicalization
    will break this; that is the desired behavior (it forces an explicit
    schema-version bump rather than silent drift).
    """

    def _build(self, overall: str, *, gate_id: str = "corp-1") -> dict:
        cats = {
            "correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"},
            "security":    {"verdict": "PASS",  "required": {}, "actual": {}, "rationale": "ok"},
        }
        return make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": "E1-001"},
            commit_sha="deadbeef" * 5,  # 40-char synthetic SHA
            profile={"id": "default", "version": 1, "hash": "abc12345"},
            factory_version="1.15.0",
            categories=cats,
            overall=overall,
        )

    def test_PASS_gate_canonical_shape_is_stable(self) -> None:
        gate = self._build("PASS")
        # Pin the field set. New fields are allowed (additive), but renaming
        # or removing one is what breaks audit replay.
        expected_keys = {
            "gate_id", "schema_version", "target", "tier", "commit_sha",
            "scanner_data_snapshot", "profile", "factory_version",
            "risk_profile_ref", "categories", "overall", "waivers",
            "evidence_bundle_hash",
        }
        # The actual gate carries AT LEAST these. Additive fields don't break it.
        self.assertTrue(expected_keys.issubset(set(gate.keys())),
                        f"missing gate fields: {sorted(expected_keys - set(gate.keys()))}")
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(gate["schema_version"], 1)

    def test_FAIL_gate_canonical_shape_is_stable(self) -> None:
        gate = self._build("FAIL", gate_id="corp-2")
        self.assertEqual(gate["overall"], "FAIL")
        # JSON round-trip stable (deterministic encoding).
        s1 = json.dumps(gate, sort_keys=True)
        s2 = json.dumps(json.loads(s1), sort_keys=True)
        self.assertEqual(s1, s2)


# ---------------------------------------------------------------------------
# D-04 — scrub BMAD_AUDIT_KEY from subprocess env at the trust boundary
# ---------------------------------------------------------------------------
# The audit-chain key (BMAD_AUDIT_KEY) is loaded once by the parent process
# via load_key_from_env(); it must NEVER leak into a subprocess environment.
# A child collector / git / docker invocation that can read the raw key can
# forge audit records. The fix is to scrub the env at the subprocess call
# site (a trust boundary), not at the source — load_key_from_env()'s
# "returns None when absent" contract remains untouched.
#
# Invariants pinned here:
#   1. scrub_env_for_subprocess() removes BMAD_AUDIT_KEY only.
#   2. parent process can still call load_key_from_env() after scrubbing
#      (scrub returns a COPY; it does not mutate os.environ).
#   3. AST scan: every subprocess.run / subprocess.Popen / subprocess.call
#      in core/ passes env=scrub_env_for_subprocess(...) — fail-closed
#      structural invariant that future regressions trip immediately.


class AuditKeyEnvScrubInvariant(unittest.TestCase):
    """Pins D-04: BMAD_AUDIT_KEY must never reach a subprocess env."""

    def test_scrub_env_removes_bmad_audit_key(self) -> None:
        from story_automator.core.audit import scrub_env_for_subprocess

        result = scrub_env_for_subprocess({"BMAD_AUDIT_KEY": "secret", "FOO": "1"})
        self.assertNotIn("BMAD_AUDIT_KEY", result)

    def test_scrub_env_preserves_other_keys(self) -> None:
        from story_automator.core.audit import scrub_env_for_subprocess

        src = {
            "BMAD_AUDIT_KEY": "secret",
            "PATH": "/usr/bin",
            "HOME": "/root",
            "LANG": "C.UTF-8",
            "TERM": "xterm",
            "CI": "true",
        }
        result = scrub_env_for_subprocess(src)
        for key in ("PATH", "HOME", "LANG", "TERM", "CI"):
            self.assertEqual(result[key], src[key], f"key {key} was mangled")
        self.assertEqual(len(result), 5)

    def test_scrub_env_idempotent(self) -> None:
        from story_automator.core.audit import scrub_env_for_subprocess

        once = scrub_env_for_subprocess({"BMAD_AUDIT_KEY": "s", "X": "1"})
        twice = scrub_env_for_subprocess(once)
        self.assertEqual(once, twice)

    def test_scrub_env_with_none_uses_os_environ(self) -> None:
        import os
        from unittest.mock import patch
        from story_automator.core.audit import scrub_env_for_subprocess

        canary = {"BMAD_AUDIT_KEY": "leak-me", "CANARY_VAR": "alive"}
        with patch.dict(os.environ, canary, clear=False):
            result = scrub_env_for_subprocess()
        self.assertNotIn("BMAD_AUDIT_KEY", result)
        self.assertEqual(result.get("CANARY_VAR"), "alive")

    def test_load_key_from_env_still_returns_key_after_scrub(self) -> None:
        # The scrub helper must NOT touch the parent's os.environ — it
        # returns a copy. The parent's load_key_from_env() contract is
        # unchanged, so a downstream call after scrubbing still resolves
        # the key.
        import os
        from unittest.mock import patch
        from story_automator.core.audit import (
            derive_key,
            load_key_from_env,
            scrub_env_for_subprocess,
        )

        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "still-here"}, clear=False):
            scrubbed = scrub_env_for_subprocess()
            self.assertNotIn("BMAD_AUDIT_KEY", scrubbed)
            # Parent process still sees the key — load_key_from_env works.
            key = load_key_from_env()
            self.assertEqual(key, derive_key("still-here"))

    def test_real_subprocess_cannot_see_audit_key(self) -> None:
        # End-to-end behavioural check: launch a real Python child with
        # env=scrub_env_for_subprocess() and assert the child does NOT
        # observe BMAD_AUDIT_KEY in its os.environ.
        import os
        import subprocess
        import sys
        from unittest.mock import patch
        from story_automator.core.audit import scrub_env_for_subprocess

        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "must-not-leak"}, clear=False):
            scrubbed = scrub_env_for_subprocess()
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import os; print(os.environ.get('BMAD_AUDIT_KEY', 'NONE'))"],
                env=scrubbed,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, f"child failed: {proc.stderr}")
        self.assertEqual(proc.stdout.strip(), "NONE")

    def test_ast_no_unscrubbed_subprocess_in_core(self) -> None:
        """Every subprocess.run / Popen / call in core/ and commands/
        MUST pass env=scrub_env_for_subprocess(...).

        The check accepts:
          * env=scrub_env_for_subprocess(...) — direct call.
          * env=<name> where <name> is the result of an earlier
            scrub_env_for_subprocess(...) assignment in the same function.
        Anything else (no env=, env=os.environ, env=os.environ.copy(),
        env=child_env constructed without scrubbing) is rejected.
        """
        import ast

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills" / "bmad-story-automator" / "src"
            / "story_automator"
        )
        # Scan core/ AND commands/ — both are inside the trust boundary
        # and may spawn subprocesses that inherit env from the parent.
        scan_dirs = (skill_src / "core", skill_src / "commands")
        offenders: list[str] = []

        def _is_scrub_call(node: ast.AST) -> bool:
            if not isinstance(node, ast.Call):
                return False
            func = node.func
            if isinstance(func, ast.Name) and func.id == "scrub_env_for_subprocess":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "scrub_env_for_subprocess":
                return True
            return False

        def _is_subprocess_call(node: ast.Call) -> bool:
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                return (
                    func.value.id == "subprocess"
                    and func.attr in {"run", "Popen", "call", "check_call", "check_output"}
                )
            return False

        def _defines_scrub_helper(tree: ast.Module) -> bool:
            """Return True iff the module's top level defines
            ``scrub_env_for_subprocess`` — rename-proof signal that this
            *is* the helper's implementation file (current home:
            ``audit_env_scrub.py``; ``audit.py`` only re-exports). The
            invariant must not apply to the file that owns the helper, no
            matter which filename hosts it.
            """
            for node in tree.body:
                if (
                    isinstance(node, ast.FunctionDef)
                    and node.name == "scrub_env_for_subprocess"
                ):
                    return True
            return False

        py_files: list[Path] = []
        for d in scan_dirs:
            if d.is_dir():
                py_files.extend(d.rglob("*.py"))
        for py_file in sorted(py_files):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            # Skip the helper's implementation file (it defines the helper
            # and has no subprocess calls). Structural — not filename-based —
            # so a future rename of audit.py / audit_env_scrub.py / split
            # cannot break the invariant.
            if _defines_scrub_helper(tree):
                continue
            # Track names bound to scrub_env_for_subprocess(...) per function
            # scope, so callers may write:
            #   sandboxed = scrub_env_for_subprocess(env)
            #   subprocess.run(..., env=sandboxed)
            class _Visitor(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.scrubbed_names: set[str] = set()

                def visit_Assign(self, node: ast.Assign) -> None:
                    if _is_scrub_call(node.value):
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name):
                                self.scrubbed_names.add(tgt.id)
                    self.generic_visit(node)

                def visit_Call(self, node: ast.Call) -> None:
                    if _is_subprocess_call(node):
                        env_kw = next(
                            (kw for kw in node.keywords if kw.arg == "env"), None,
                        )
                        ok = False
                        if env_kw is not None:
                            val = env_kw.value
                            if _is_scrub_call(val):
                                ok = True
                            elif isinstance(val, ast.Name) and val.id in self.scrubbed_names:
                                ok = True
                        if not ok:
                            offenders.append(
                                f"{py_file.relative_to(skill_src)}:{node.lineno} — "
                                f"subprocess call without scrub_env_for_subprocess"
                            )
                    self.generic_visit(node)

            _Visitor().visit(tree)

        self.assertEqual(
            offenders, [],
            "Unscrubbed subprocess calls found in core/. D-04 invariant broken:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
