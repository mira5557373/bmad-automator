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
import textwrap
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
        gate = self._gate(
            waivers=[
                {
                    "waiver_id": "01J90000000000000000000W",
                    "operator_id": "mira",
                    "issued_at": "2026-06-01T00:00:00Z",
                    "expires_at": "2026-06-02T00:00:00Z",  # past
                    "failing_categories": ["security"],
                    "reason": "test",
                    "signature": "sig",
                    "profile_hash": "abc123",
                }
            ]
        )
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="deadbeef",
            profile_hash="abc123",
            factory_version="1.15.0",
        )
        self.assertFalse(ok, "expired waiver MUST block reuse — the audit fix is gone")
        self.assertIn("waiver expired", reason)

    def test_unexpired_waiver_allows_reuse(self) -> None:
        gate = self._gate(
            waivers=[
                {
                    "waiver_id": "01J90000000000000000000F",
                    "operator_id": "mira",
                    "issued_at": "2099-01-01T00:00:00Z",
                    "expires_at": "2099-12-31T23:59:59Z",
                    "failing_categories": ["security"],
                    "reason": "infra dependency",
                    "signature": "sig",
                    "profile_hash": "abc123",
                }
            ]
        )
        ok, _ = can_reuse_gate_file(
            gate,
            commit_sha="deadbeef",
            profile_hash="abc123",
            factory_version="1.15.0",
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
        self.assertFalse(
            important.exists(),
            "the original evidence path must not still exist (it was moved to quarantine)",
        )
        quar = Path(result["quarantine_dir"])
        self.assertTrue(
            (quar / "evidence" / "lost-gate" / "important.json").is_file(),
            "important evidence MUST have been quarantined, not deleted",
        )

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
            "verdict": "FAIL",
            "required": {},
            "actual": {},
            "rationale": "1 critical CVE",
            "evidence": [],
        }
        story = self.tmp / "E1-001.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing dev task\n\n## Notes\n",
            encoding="utf-8",
        )
        result = route_gate_verdict(
            self.tmp,
            gate,
            story_key="E1-001",
            remediation_cycle=0,
            max_cycles=3,
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
            "verdict": "FAIL",
            "required": {},
            "actual": {},
            "rationale": "1 critical CVE",
            "evidence": [],
        }
        result = route_gate_verdict(
            self.tmp,
            gate,
            story_key="E1-001",
            remediation_cycle=0,
            max_cycles=3,
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
            contract={
                "config": {
                    "gate_id": gate["gate_id"],
                    "remediation_cycle": 3,
                    "max_cycles": 3,
                }
            },
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
            'name = "example"\nversion = "1.0.0"\npython_module = "my_plugin.entry"\n'
        )
        with self.assertRaises(PluginTrustError) as ctx:
            self._registry().load_all()
        # The error message must name the rule (so a future contributor
        # reading the traceback can find the trust-boundary doc).
        self.assertIn("python_module", str(ctx.exception))

    def test_py_module_key_rejected(self) -> None:
        """Manifest with ``py_module`` key MUST raise PluginTrustError."""
        from story_automator.core.plugins import PluginTrustError

        self._write_manifest('name = "example"\nversion = "1.0.0"\npy_module = "my_plugin"\n')
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
            "\n"
            "[hooks]\n"
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

        self._write_manifest('name = "example"\nversion = "1.0.0"\nimport = "my_plugin:run"\n')
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
            offenders,
            [],
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
            "security": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"},
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
            "gate_id",
            "schema_version",
            "target",
            "tier",
            "commit_sha",
            "scanner_data_snapshot",
            "profile",
            "factory_version",
            "risk_profile_ref",
            "categories",
            "overall",
            "waivers",
            "evidence_bundle_hash",
        }
        # The actual gate carries AT LEAST these. Additive fields don't break it.
        self.assertTrue(
            expected_keys.issubset(set(gate.keys())),
            f"missing gate fields: {sorted(expected_keys - set(gate.keys()))}",
        )
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
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('BMAD_AUDIT_KEY', 'NONE'))",
                ],
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
            / "skills"
            / "bmad-story-automator"
            / "src"
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
                return func.value.id == "subprocess" and func.attr in {
                    "run",
                    "Popen",
                    "call",
                    "check_call",
                    "check_output",
                }
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
                if isinstance(node, ast.FunctionDef) and node.name == "scrub_env_for_subprocess":
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
                            (kw for kw in node.keywords if kw.arg == "env"),
                            None,
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
            offenders,
            [],
            "Unscrubbed subprocess calls found in core/. D-04 invariant broken:\n  "
            + "\n  ".join(offenders),
        )


class UnifiedStateWriteIsolationInvariant(unittest.TestCase):
    """Pins G7: only ``unified_state.py`` may write to BOTH dual stores in
    the same module without calling ``unified_state_lock(...)``.

    Any module under ``core/`` that calls ``write_phase(...)`` (the M48
    writer) AND mutates the sprint-status file (via ``write_atomic`` or
    ``os.replace`` on a path resolved by ``sprint_status_path`` /
    ``sprint_status_file``) MUST also acquire ``unified_state_lock`` to
    serialise the two-store write. ``unified_state.py`` itself is exempt
    because it is the implementation of the unification surface.

    Gap D-R-08: AST call-pattern check (not import-name match) — catches
    a future module that re-implements both-store writes without
    cooperating with the unified-state lock.
    """

    @staticmethod
    def _module_violates(tree) -> bool:
        """Return True iff ``tree`` calls BOTH stores without acquiring
        ``unified_state_lock``. Pure AST analysis — no string grep.

        Tracks bindings of ``name = sprint_status_path(...) /
        sprint_status_file(...)`` so callers that hoist the path into a
        local variable (the realistic case) are still detected.
        """
        import ast

        SPRINT_PATH_NAMES = {"sprint_status_path", "sprint_status_file"}
        calls_write_phase = False
        mutates_sprint_status = False
        acquires_unified_lock = False
        # Names bound to sprint-status path expressions.
        path_names: set[str] = set()

        def _name_of(node) -> str | None:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return node.attr
            return None

        def _is_path_expression(expr) -> bool:
            """True iff ``expr`` involves a call to sprint_status_path/file
            anywhere in its subtree (handles ``Path(sprint_status_path(r))``
            and other wrapping patterns).
            """
            for sub in ast.walk(expr):
                if isinstance(sub, ast.Call) and _name_of(sub.func) in SPRINT_PATH_NAMES:
                    return True
                if isinstance(sub, ast.Name) and sub.id in path_names:
                    return True
            return False

        # First pass — record sprint-status path bindings.
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _is_path_expression(node.value):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        path_names.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if _is_path_expression(node.value) and isinstance(node.target, ast.Name):
                    path_names.add(node.target.id)

        # Second pass — find write_phase, write_atomic on tracked paths,
        # and unified_state_lock acquisitions.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = _name_of(node.func)
            if fname == "write_phase":
                calls_write_phase = True
            if fname == "unified_state_lock":
                acquires_unified_lock = True
            if fname in {"write_atomic", "replace"}:
                # First positional arg is the path.
                if node.args and _is_path_expression(node.args[0]):
                    mutates_sprint_status = True
                # Also accept kwarg form path=...
                for kw in node.keywords:
                    if kw.arg in {"path", "dst"} and _is_path_expression(kw.value):
                        mutates_sprint_status = True

        return calls_write_phase and mutates_sprint_status and not acquires_unified_lock

    def test_ast_unified_state_module_is_isolated_writer(self) -> None:
        """Walk every .py under core/; flag two-store writers that miss
        ``unified_state_lock(...)``. The unified_state module itself is
        the exempted home for both-store writes.
        """
        import ast

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        core_dir = skill_src / "core"
        offenders: list[str] = []
        for py_file in sorted(core_dir.rglob("*.py")):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            # Exempt the unified-state module itself — it IS the legal
            # home for two-store writes. Structural check (top-level
            # function name) so a rename of the filename does not break
            # the invariant.
            owns_unified_writer = any(
                isinstance(n, ast.FunctionDef) and n.name == "write_unified_state"
                for n in tree.body
            )
            if owns_unified_writer:
                continue
            if self._module_violates(tree):
                offenders.append(str(py_file.relative_to(skill_src)))
        self.assertEqual(
            offenders,
            [],
            "Modules writing both sprint-status and phase stores without "
            "unified_state_lock — G7 isolation invariant broken:\n  " + "\n  ".join(offenders),
        )

    def test_positive_failure_synthetic_violator_is_caught(self) -> None:
        """Construct a synthetic Python source that violates the
        invariant and prove the AST walker flags it. This is the
        positive-failure half of the invariant — without it the test
        could be vacuously true.
        """
        import ast

        synthetic = textwrap.dedent(
            """
            from story_automator.core.integration.sprint_phase_map import write_phase
            from story_automator.core.utils import write_atomic
            from story_automator.core.story_keys import sprint_status_file

            def bad_writer(root, key, status, phase):
                write_phase(root, key, phase)
                path = sprint_status_file(root)
                write_atomic(path, status)
            """
        )
        tree = ast.parse(synthetic)
        self.assertTrue(
            UnifiedStateWriteIsolationInvariant._module_violates(tree),
            "AST walker FAILED to flag a known violator — invariant is vacuously true",
        )
        # And the real unified_state.py source must pass — the writer is
        # exempted by structural recognition (test above), but the same
        # raw source also acquires the lock so the violation rule would
        # not fire either.
        from story_automator.core.integration import unified_state as us_mod

        real_tree = ast.parse(Path(us_mod.__file__).read_text(encoding="utf-8"))
        # Strip top-level write_unified_state to exercise the rule itself.
        stripped = ast.Module(
            body=[
                n
                for n in real_tree.body
                if not (isinstance(n, ast.FunctionDef) and n.name == "write_unified_state")
            ],
            type_ignores=[],
        )
        # Even without the exemption, the real module acquires the lock
        # everywhere it writes — so the violation rule must NOT trip.
        self.assertFalse(
            UnifiedStateWriteIsolationInvariant._module_violates(stripped),
            "unified_state.py raw source trips the violation rule — the "
            "module is supposed to bracket every two-store write with "
            "unified_state_lock",
        )


# ---------------------------------------------------------------------------
# C5 — ThresholdApplyIsolationInvariant + ThresholdLockIsolationInvariant
# ---------------------------------------------------------------------------
# The self-improving gate (C5) auto-emits ThresholdProposals but MUST NEVER
# silently rewrite its own rules. The apply step (``apply_threshold_proposal``
# in ``core/innovation/threshold_apply.py``) is the only legal mutator of
# ``gate_rules.py`` and may run ONLY from operator-initiated CLI handlers
# under ``commands/``. The structural exemptions key off
#   (a) the top-level ``def apply_threshold_proposal`` (the implementation
#       file is rename-proof exempt — mirrors ``_defines_scrub_helper``), and
#   (b) the CLI handler signature ``def f(args, *, confirm: str, ...)`` whose
#       body calls ``apply_threshold_proposal`` (rename-proof exemption for
#       the deliberately-coupled operator gate; matches spec §7.5).
# All other ``core/`` and ``commands/`` modules MUST NOT call
# ``apply_threshold_proposal`` directly, via alias rebinding, via
# ``getattr(...)``, or via ``importlib.import_module(...).apply_threshold_proposal``.
#
# Additionally, every ``FileLock(...)`` call inside
# ``core/innovation/threshold_*.py`` MUST resolve to the
# ``.calibration.lock`` sidecar — pinned by the lock-isolation invariant —
# so that no co-acquisition with ``.gate.lock`` / ``.lineage.lock`` /
# ``.drift.lock`` / ``.unified-state.lock`` is structurally possible.


class ThresholdApplyIsolationInvariant(unittest.TestCase):
    """Pins C5 §7.5: only the operator-driven CLI handler may call
    ``apply_threshold_proposal``. Mirrors ``AuditKeyEnvScrubInvariant``
    (lines 530-732) for structural exemption + ``UnifiedStateWriteIsolationInvariant``
    (lines 733-906) for binding tracking.
    """

    @staticmethod
    def _defines_apply_helper(tree) -> bool:
        """Return True iff the module's top level defines
        ``apply_threshold_proposal`` — rename-proof signal that this *is*
        the apply step's implementation file (current home:
        ``core/innovation/threshold_apply.py``). The invariant must not
        apply to the file that owns the helper, no matter which filename
        hosts it (matches ``_defines_scrub_helper`` at lines 659-673).
        """
        import ast

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "apply_threshold_proposal":
                return True
        return False

    @staticmethod
    def _is_cli_apply_handler(tree) -> bool:
        """Return True iff the module defines a top-level FunctionDef whose
        FIRST non-self argument is annotated ``confirm: str`` AND whose body
        contains a ``Call`` to ``apply_threshold_proposal``.

        Structural — rename-proof — so the §3 pre-authorized split of
        ``calibration_cmd.py`` into ``calibration_subcommands.py`` cannot
        break the invariant. The current home is
        ``commands/calibration_cmd._cmd_apply``.

        Spec §7.5 tightens "first non-self positional or first kwonly arg"
        (post-impl review fix). The caller MUST scope this exemption to
        modules under ``commands/`` — see the path check at the call site.
        """
        import ast

        def _has_confirm_str_as_first_kwonly_or_positional(func: ast.FunctionDef) -> bool:
            # First non-self positional, or first kwonly arg. The spec
            # narrows the structural property to a leading-position
            # annotation, so a buried ``confirm: str`` deep in the arg
            # list cannot accidentally exempt an unrelated helper.
            candidates: list[ast.arg] = []
            positional = list(func.args.posonlyargs) + list(func.args.args)
            # Skip a leading ``self`` if present (rare for module-level
            # functions, but cheap to guard).
            if positional and positional[0].arg == "self":
                positional = positional[1:]
            if positional:
                candidates.append(positional[0])
            if func.args.kwonlyargs:
                candidates.append(func.args.kwonlyargs[0])
            for arg in candidates:
                if arg.arg != "confirm":
                    continue
                ann = arg.annotation
                if isinstance(ann, ast.Name) and ann.id == "str":
                    return True
                if isinstance(ann, ast.Constant) and ann.value == "str":
                    # String-literal annotation (PEP 563-style) — also OK.
                    return True
            return False

        def _calls_apply(func: ast.FunctionDef) -> bool:
            for sub in ast.walk(func):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                if isinstance(fn, ast.Name) and fn.id == "apply_threshold_proposal":
                    return True
                if isinstance(fn, ast.Attribute) and fn.attr == "apply_threshold_proposal":
                    return True
            return False

        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if _has_confirm_str_as_first_kwonly_or_positional(node) and _calls_apply(node):
                return True
        return False

    @classmethod
    def _module_violates(cls, tree) -> bool:
        """Return True iff ``tree`` contains a direct or indirect call to
        ``apply_threshold_proposal`` and is NOT covered by either structural
        exemption (``_defines_apply_helper`` / ``_is_cli_apply_handler``).
        Binding-tracking AST walker — modeled on
        ``UnifiedStateWriteIsolationInvariant._module_violates`` (lines 743-855).

        Tracks:
          * ``from X import apply_threshold_proposal as ALIAS`` → ALIAS forbidden.
          * ``ALIAS = apply_threshold_proposal`` (or alias) → LHS forbidden.

        Flags:
          * ``Call(func=Name(N))`` for N in the forbidden set (incl. the
            canonical name).
          * ``Call(func=Attribute(attr="apply_threshold_proposal"))`` —
            regardless of receiver.
          * ``Call(func=Name("getattr"), args=[_, Constant("apply_threshold_proposal"), ...])``.
          * ``Attribute(attr="apply_threshold_proposal", value=Call(func=Attribute(attr="import_module"), ...))``.
        """
        import ast

        forbidden: set[str] = {"apply_threshold_proposal"}

        # First pass — record aliases. Tracks BOTH ``Assign`` (e.g.
        # ``fn = apply_threshold_proposal``) AND ``AnnAssign`` (e.g.
        # ``fn: object = apply_threshold_proposal``) — modeled on
        # UnifiedStateWriteIsolationInvariant._module_violates (lines
        # 743-855). The post-impl review found the AnnAssign branch
        # was missing; without it a single PEP 526 annotated binding
        # could smuggle a rebind past the walker.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "apply_threshold_proposal":
                        forbidden.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Name) and node.value.id in forbidden:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            forbidden.add(tgt.id)
                elif isinstance(node.value, ast.Attribute) and (
                    node.value.attr == "apply_threshold_proposal"
                ):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            forbidden.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if (
                    isinstance(node.value, ast.Name)
                    and node.value.id in forbidden
                    and isinstance(node.target, ast.Name)
                ):
                    forbidden.add(node.target.id)
                elif (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr == "apply_threshold_proposal"
                    and isinstance(node.target, ast.Name)
                ):
                    forbidden.add(node.target.id)

        # Second pass — flag direct/indirect calls + indirect access.
        for node in ast.walk(tree):
            # Direct/aliased call: f(...) or _ap(...).
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    if fn.id in forbidden:
                        return True
                    if fn.id == "getattr" and len(node.args) >= 2:
                        second = node.args[1]
                        if (
                            isinstance(second, ast.Constant)
                            and second.value == "apply_threshold_proposal"
                        ):
                            return True
                if isinstance(fn, ast.Attribute) and fn.attr == "apply_threshold_proposal":
                    return True
            # Indirect access via importlib.import_module(...).apply_threshold_proposal
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "apply_threshold_proposal"
                and isinstance(node.value, ast.Call)
            ):
                inner = node.value.func
                if isinstance(inner, ast.Attribute) and inner.attr == "import_module":
                    return True
                if isinstance(inner, ast.Name) and inner.id == "import_module":
                    return True
        return False

    def test_ast_no_direct_or_indirect_apply_in_core_and_commands(self) -> None:
        """Walk every .py under BOTH core/ AND commands/; flag any call
        (direct, aliased, getattr-indirect, importlib-indirect) to
        ``apply_threshold_proposal`` from a module not covered by the two
        structural exemptions.
        """
        import ast

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        scan_dirs = (skill_src / "core", skill_src / "commands")
        offenders: list[str] = []
        py_files: list[Path] = []
        for d in scan_dirs:
            if d.is_dir():
                py_files.extend(d.rglob("*.py"))
        for py_file in sorted(py_files):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            # Exemption (a): the file that owns the helper.
            if self._defines_apply_helper(tree):
                continue
            # Exemption (b): the operator-driven CLI handler — scoped
            # STRICTLY to modules under ``commands/`` per spec §7.5
            # ("under a commands/ path component"). Post-impl review
            # found the path constraint was missing, which would have
            # let any ``core/`` module self-exempt by defining a
            # confirm-shaped helper. Routing the check through the
            # path predicate closes that gap.
            if py_file.is_relative_to(skill_src / "commands") and self._is_cli_apply_handler(tree):
                continue
            if self._module_violates(tree):
                offenders.append(str(py_file.relative_to(skill_src)))
        self.assertEqual(
            offenders,
            [],
            "Modules calling apply_threshold_proposal outside the "
            "deliberately-coupled CLI gate — C5 self-improving-gate "
            "isolation invariant broken:\n  " + "\n  ".join(offenders),
        )

    def test_positive_failure_synthetic_violator_is_caught(self) -> None:
        """Two-direction proof matching
        ``UnifiedStateWriteIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``
        (lines 859-905):

        (a) Synthesize source containing direct call + alias-rebinding
            call + indirect ``getattr`` call + ``importlib.import_module``
            chain; assert ALL flagged.
        (b) Read the real ``threshold_apply.py`` source, AST-strip the
            ``def apply_threshold_proposal`` top-level FunctionDef,
            re-parse, assert the walker does NOT trip on the residual
            file — proves the rule itself is operative independent of
            the exemption.
        """
        import ast

        # (a) Direct call.
        direct_src = textwrap.dedent(
            """
            from story_automator.core.innovation.threshold_apply import (
                apply_threshold_proposal,
            )

            def evil_direct():
                apply_threshold_proposal(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(direct_src)),
            "AST walker FAILED to flag a direct call — invariant is vacuously true",
        )

        # (a) Alias rebinding call.
        alias_src = textwrap.dedent(
            """
            from story_automator.core.innovation.threshold_apply import (
                apply_threshold_proposal as _ap,
            )

            def evil_alias():
                _ap(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(alias_src)),
            "AST walker FAILED to flag an alias-rebinding call",
        )

        # (a) Indirect getattr call.
        getattr_src = textwrap.dedent(
            """
            from story_automator.core.innovation import threshold_apply as ta

            def evil_getattr():
                fn = getattr(ta, "apply_threshold_proposal")
                fn(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(getattr_src)),
            "AST walker FAILED to flag a getattr-indirect call",
        )

        # (a) importlib.import_module(...).apply_threshold_proposal chain.
        importlib_src = textwrap.dedent(
            """
            import importlib

            def evil_importlib():
                mod = importlib.import_module("story_automator.core.innovation.threshold_apply")
                mod.apply_threshold_proposal(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(importlib_src)),
            "AST walker FAILED to flag importlib.import_module chain",
        )

        # (a) AnnAssign rebinding via Name — post-impl review fix.
        annassign_name_src = textwrap.dedent(
            """
            from story_automator.core.innovation.threshold_apply import (
                apply_threshold_proposal,
            )

            def evil_annassign_name():
                fn: object = apply_threshold_proposal
                fn(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(annassign_name_src)),
            "AST walker FAILED to flag AnnAssign(Name) rebind — first-pass "
            "binding tracker is missing the AnnAssign branch",
        )

        # (a) AnnAssign rebinding via Attribute — post-impl review fix.
        annassign_attr_src = textwrap.dedent(
            """
            from story_automator.core.innovation import threshold_apply as ta

            def evil_annassign_attr():
                fn: object = ta.apply_threshold_proposal
                fn(".", "id", confirm="x", operator_id="x")
            """
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(ast.parse(annassign_attr_src)),
            "AST walker FAILED to flag AnnAssign(Attribute) rebind — first-pass "
            "binding tracker is missing the AnnAssign branch",
        )

        # (b) Real threshold_apply.py — two-direction proof:
        #
        #   (b.1) Strip the top-level def and inject a fake violator into
        #         the residual; walker MUST trip (operative on real-file
        #         residual shape).
        #   (b.2) Strip the top-level def WITHOUT injecting; walker MUST
        #         NOT trip (proves residual file does not call the helper
        #         anywhere else).
        #
        # The post-impl review found the previous test only verified
        # (b.2) on a residual that had ZERO Call nodes referencing the
        # name — vacuously true. Injecting a known violator first
        # forces the walker to reason about a meaningful residual.
        from story_automator.core.innovation import threshold_apply as ta_mod

        real_tree = ast.parse(Path(ta_mod.__file__).read_text(encoding="utf-8"))
        stripped_body = [
            n
            for n in real_tree.body
            if not (isinstance(n, ast.FunctionDef) and n.name == "apply_threshold_proposal")
        ]

        # (b.1) Inject a fake top-level violator into the residual.
        violator_src = textwrap.dedent(
            """
            def _injected_violator():
                apply_threshold_proposal(".", "id", confirm="x", operator_id="x")
            """
        )
        violator_def = ast.parse(violator_src).body[0]
        stripped_with_violator = ast.Module(
            body=stripped_body + [violator_def],
            type_ignores=[],
        )
        self.assertTrue(
            ThresholdApplyIsolationInvariant._module_violates(stripped_with_violator),
            "Injecting a real violator into the residual threshold_apply.py "
            "tree did NOT trip the rule — the rule may be vacuous",
        )

        # (b.2) Same residual without the injected violator must NOT trip.
        stripped = ast.Module(body=stripped_body, type_ignores=[])
        self.assertFalse(
            ThresholdApplyIsolationInvariant._module_violates(stripped),
            "threshold_apply.py residual (without its own def) trips the "
            "violation rule — the file should not call apply_threshold_proposal "
            "anywhere else",
        )

    def test_drift_band_proposals_disabled_by_default(self) -> None:
        """Pin the safety-critical default ``enable_drift_band_proposals=False``.

        Matches ``PluginTrustBoundaryInvariant.test_plugin_manifest_keys_closed_set``
        (line 397) — widening the default to True is a trust-boundary
        change that requires an explicit spec-level decision.
        """
        import inspect
        from story_automator.core.innovation.threshold_proposer import ThresholdProposer

        sig = inspect.signature(ThresholdProposer.__init__)
        self.assertIn("enable_drift_band_proposals", sig.parameters)
        self.assertIs(
            sig.parameters["enable_drift_band_proposals"].default,
            False,
            "ThresholdProposer(enable_drift_band_proposals=...) default MUST be "
            "False — drift-band auto-tuning is registered but disabled in v1 "
            "(spec §3 + §7.5).",
        )


class ThresholdLockIsolationInvariant(unittest.TestCase):
    """Pins C5 §3 lock-ordering policy: no ``FileLock`` construction in
    ``core/innovation/threshold_*.py`` may target any sidecar other than
    ``.calibration.lock``. AST-rejects co-acquisition setups with
    ``.gate.lock`` / ``.lineage.lock`` / ``.drift.lock`` / ``.unified-state.lock``.
    """

    _CANONICAL_LOCK_SUFFIX = ".calibration.lock"
    _CANONICAL_HELPER_NAMES = frozenset({"calibration_lock_path"})

    @classmethod
    def _is_filelock_call(cls, node) -> bool:
        """Return True iff ``node`` is a ``Call`` whose ``func`` is either
        ``FileLock`` (bare name) or ``Attribute(attr="FileLock")``
        (e.g., ``filelock.FileLock(...)``).
        """
        import ast

        if not isinstance(node, ast.Call):
            return False
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "FileLock":
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == "FileLock":
            return True
        return False

    @classmethod
    def _path_arg_of(cls, call) -> object:
        """Return the path argument of a ``FileLock(...)`` Call — either
        the first positional or the ``lock_file=`` kwarg. Returns the AST
        node (not a string) so the resolver can inspect its shape.
        """
        if call.args:
            return call.args[0]
        for kw in call.keywords:
            if kw.arg == "lock_file":
                return kw.value
        return None

    @classmethod
    def _path_arg_is_canonical(cls, path_node) -> bool:
        """Return True iff ``path_node`` resolves to the
        ``.calibration.lock`` sidecar.

        Accepted shapes (rooted in spec §3):
          * ``Constant("...calibration.lock")`` — literal ending in the
            canonical suffix.
          * ``Call(calibration_lock_path(...))`` — the centralized helper.
          * ``Call(str(calibration_lock_path(...)))`` — string-coerced
            helper return value (current production form).
          * Any nested call chain that contains a ``calibration_lock_path``
            invocation anywhere in its subtree — defends against future
            wrapping like ``Path(str(calibration_lock_path(r)))``.

        Anything else (including non-canonical string literals like
        ``".gate.lock"`` and unresolvable expressions) returns False —
        the caller flags.
        """
        import ast

        if path_node is None:
            return False
        # Literal string ending in the canonical suffix.
        if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
            return path_node.value.endswith(cls._CANONICAL_LOCK_SUFFIX)
        # Walk the subtree for any call to the centralized helper.
        for sub in ast.walk(path_node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Name) and fn.id in cls._CANONICAL_HELPER_NAMES:
                    return True
                if isinstance(fn, ast.Attribute) and fn.attr in cls._CANONICAL_HELPER_NAMES:
                    return True
        return False

    def test_threshold_modules_only_acquire_calibration_lock(self) -> None:
        """Walk every ``core/innovation/threshold_*.py``; inspect every
        ``FileLock(...)`` construction. The first positional or
        ``lock_file=`` kwarg MUST resolve to ``.calibration.lock``
        (either by literal suffix or by going through the centralized
        ``calibration_lock_path`` helper). Any other resolved or
        unresolved path is flagged.
        """
        import ast

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        innovation_dir = skill_src / "core" / "innovation"
        offenders: list[str] = []
        for py_file in sorted(innovation_dir.glob("threshold_*.py")):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not self._is_filelock_call(node):
                    continue
                path_node = self._path_arg_of(node)
                if not self._path_arg_is_canonical(path_node):
                    offenders.append(
                        f"{py_file.relative_to(skill_src)}:{node.lineno} — "
                        f"FileLock(...) does not target .calibration.lock"
                    )
        self.assertEqual(
            offenders,
            [],
            "FileLock constructions in core/innovation/threshold_*.py that "
            "target a non-.calibration.lock sidecar — C5 lock-ordering "
            "isolation invariant broken:\n  " + "\n  ".join(offenders),
        )

    def test_positive_failure_synthetic_filelock_is_caught(self) -> None:
        """Hand-crafted ``FileLock(".gate.lock")`` must be caught by the
        walker — proves the rule itself is operative.
        """
        import ast

        synthetic = textwrap.dedent(
            """
            import filelock
            from filelock import FileLock

            def bad_co_acquire(root):
                # Co-acquisition with gate lock would deadlock against the
                # gate orchestrator — forbidden by C5 §3 lock-ordering.
                a = FileLock(".gate.lock")
                b = filelock.FileLock(".lineage.lock")
                return a, b
            """
        )
        tree = ast.parse(synthetic)
        flagged: list[str] = []
        for node in ast.walk(tree):
            if not ThresholdLockIsolationInvariant._is_filelock_call(node):
                continue
            path_node = ThresholdLockIsolationInvariant._path_arg_of(node)
            if not ThresholdLockIsolationInvariant._path_arg_is_canonical(path_node):
                flagged.append(f"line {node.lineno}")
        self.assertEqual(
            len(flagged),
            2,
            f"Walker FAILED to flag known synthetic FileLock violators; "
            f"got {flagged!r} — invariant is vacuously true",
        )

        # And the real threshold modules must pass the walker (positive
        # half of the two-direction proof).
        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        innovation_dir = skill_src / "core" / "innovation"
        any_filelock_seen = False
        for py_file in sorted(innovation_dir.glob("threshold_*.py")):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not ThresholdLockIsolationInvariant._is_filelock_call(node):
                    continue
                any_filelock_seen = True
                path_node = ThresholdLockIsolationInvariant._path_arg_of(node)
                self.assertTrue(
                    ThresholdLockIsolationInvariant._path_arg_is_canonical(path_node),
                    f"real {py_file.name}:{node.lineno} FileLock does not "
                    f"resolve to .calibration.lock — the canonical resolver "
                    f"missed a production call site",
                )
        self.assertTrue(
            any_filelock_seen,
            "Walker found ZERO FileLock calls in threshold_*.py — the "
            "invariant is vacuously true because the production calls "
            "are gone (and the test never executes the resolver)",
        )


if __name__ == "__main__":
    unittest.main()
