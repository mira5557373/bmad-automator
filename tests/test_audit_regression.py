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

import inspect
import json
import shutil
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from story_automator.core.evidence_io import (
    GateMarkerCorruptedError,
    can_reuse_gate_file,
    read_gate_marker,
)
from story_automator.core.gate_orchestrator import recover_from_crash, route_gate_verdict
from story_automator.core.gate_schema import canonical_json, make_gate_file


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
        # Use dynamic future dates so this test does NOT become a time bomb.
        # See ``test_unexpired_waiver_fixture_has_no_hardcoded_year_literal``
        # for the regression rationale (calendar drift would otherwise flip
        # the assertion shape and mask a real §6.4(e) regression).
        now = datetime.now(timezone.utc)
        issued_at = now.isoformat()
        expires_at = (now + timedelta(days=1)).isoformat()
        gate = self._gate(
            waivers=[
                {
                    "waiver_id": "01J90000000000000000000F",
                    "operator_id": "mira",
                    "issued_at": issued_at,
                    "expires_at": expires_at,
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

    def test_unexpired_waiver_fixture_has_no_hardcoded_year_literal(self) -> None:
        """Regression test for the 2099-12-31 time bomb.

        The previous fixture pinned ``expires_at = '2099-12-31T23:59:59Z'``,
        which would silently flip ``test_unexpired_waiver_allows_reuse`` to
        a ``waiver expired`` failure after that date — indistinguishable in
        CI from a real §6.4(e) regression. This invariant pins the dynamic
        fixture so the time-bomb cannot reappear via copy-paste or revert.
        """
        source = inspect.getsource(self.test_unexpired_waiver_allows_reuse)
        # Specifically reject the historical 2099 literal that was the
        # original time-bomb. Other year literals (e.g. inside docstring
        # references) are not the bug here, so we keep the rule narrow.
        self.assertNotIn(
            "2099",
            source,
            "fixture must use dynamic dates (datetime.now + timedelta), not "
            "hardcoded year literals — see the 2099-12-31 time-bomb finding",
        )
        # And it MUST actually use a dynamic date helper, not just be
        # silent. This pins the fix forward.
        self.assertIn(
            "datetime.now",
            source,
            "fixture must derive expires_at from datetime.now to avoid a "
            "future time bomb",
        )


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
        # Pin the FAIL field set (mirror of the PASS sibling).
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
        self.assertTrue(
            expected_keys.issubset(set(gate.keys())),
            f"missing gate fields: {sorted(expected_keys - set(gate.keys()))}",
        )
        # Real canonical-encoding pin: canonical_json uses sort_keys=True AND
        # compact separators (",", ":"). A round-trip through json.loads +
        # json.dumps(sort_keys=True) is a tautology that cannot detect drift;
        # comparing canonical_json's compact output against a NON-compact
        # encoding proves the canonicalization is doing real work.
        canonical = canonical_json(gate)
        # Compact separators distinguish canonical from default json.dumps.
        non_compact = json.dumps(gate, sort_keys=True)  # default separators
        self.assertNotEqual(
            canonical,
            non_compact,
            "canonical_json must produce compact-separator output distinct "
            "from default json.dumps(..., sort_keys=True); otherwise the "
            "audit-replay determinism contract is not actually pinned.",
        )
        # Canonicalization is idempotent over loads→dumps (real determinism).
        self.assertEqual(canonical, canonical_json(json.loads(canonical)))
        # Re-ordering the source dict's keys must not change canonical output.
        reordered = {k: gate[k] for k in reversed(list(gate.keys()))}
        self.assertEqual(canonical, canonical_json(reordered))

    def test_canonical_json_pin_is_not_a_tautology(self) -> None:
        """Regression: the FAIL-shape assertion must not be `s1 == s2` where
        `s1 = json.dumps(x, sort_keys=True)` and
        `s2 = json.dumps(json.loads(s1), sort_keys=True)`.

        That form is a mathematical tautology — it holds for any
        JSON-serializable dict because json.loads is lossless and
        sort_keys=True is deterministic. A real canonical-encoding pin
        MUST detect at least one of: (a) compact-separator drift,
        (b) key-ordering drift in the source dict, (c) loss of
        idempotency through the canonical_json helper.

        This test pins the existence of the contract by demonstrating
        that the tautological assertion passes on arbitrary inputs while
        canonical_json comparisons against non-canonical encodings do not.
        """
        # The tautology holds for any dict — prove it.
        arbitrary_dicts: list[dict] = [
            {"z": 1, "a": 2},
            {},
            {"nested": {"y": [3, 1, 2], "x": "ok"}},
            {"unrelated": "to-gate-schema"},
        ]
        for d in arbitrary_dicts:
            s1 = json.dumps(d, sort_keys=True)
            s2 = json.dumps(json.loads(s1), sort_keys=True)
            self.assertEqual(
                s1,
                s2,
                f"Tautology proof failed for {d!r}; this should never happen "
                "unless json semantics changed.",
            )
        # Now show that the real canonical_json helper DOES detect the
        # difference between compact and non-compact encoding for the same
        # arbitrary dicts — this is what makes it a real pin.
        for d in arbitrary_dicts:
            if not d:
                # Empty dict serializes identically under both separator sets.
                continue
            compact = canonical_json(d)
            default = json.dumps(d, sort_keys=True)
            self.assertNotEqual(
                compact,
                default,
                "canonical_json must use compact separators that differ from "
                f"json.dumps default output; failed for {d!r}.",
            )


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

    # Closed allowlist of subprocess callables the AST walker must
    # recognise. Mirrors the canonical ``subprocess`` API surface used
    # across the codebase.
    SUBPROCESS_CALLABLES = {
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
    }

    @staticmethod
    def _collect_subprocess_bindings(tree) -> tuple[set[str], set[str]]:
        """Return ``(module_aliases, callable_aliases)`` for ``tree``.

        ``module_aliases`` are names bound to the ``subprocess`` module
        via ``import subprocess`` / ``import subprocess as sp`` AND via
        plain rebinding (``sub = subprocess`` / ``sub: object =
        subprocess``).
        ``callable_aliases`` are names bound to one of
        :pyattr:`SUBPROCESS_CALLABLES` via ``from subprocess import run``
        or ``from subprocess import run as r`` AND via plain rebinding
        (``r = run`` / ``r: object = run``).

        Mirrors the binding-tracking idiom in
        :py:meth:`ThresholdApplyIsolationInvariant._module_violates`
        (lines 1942-1965) so future ``import subprocess as sp``, ``from
        subprocess import run``, ``from subprocess import run as r``,
        AND ``sub = subprocess`` / ``r = run`` rebinding idioms cannot
        silently bypass the D-04 trust-boundary net.
        """
        import ast

        module_aliases: set[str] = set()
        callable_aliases: set[str] = set()
        # First pass — direct imports.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        module_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                # Gate on ``node.level == 0`` so a relative import like
                # ``from .subprocess import run`` (level=1, referring to a
                # project-local sibling module named ``subprocess.py``) is
                # NOT mis-classified as a stdlib ``subprocess`` binding.
                # No file under skills/ currently shadows the stdlib name,
                # so this is a precision-contract guard: the walker's
                # negative test at the end of
                # ``test_positive_failure_bypass_idioms_are_caught``
                # promises binding-tracking is "precise, not over-broad".
                if node.module == "subprocess" and node.level == 0:
                    for alias in node.names:
                        # Star imports bind every public name from the
                        # source module into the current namespace, so
                        # ``from subprocess import *`` introduces bare-
                        # name ``run`` / ``Popen`` / ``call`` /
                        # ``check_call`` / ``check_output`` callables.
                        # Without this branch a star-import + bare
                        # ``run(..., env=...)`` silently bypasses the
                        # D-04 trust-boundary net (verified empirically:
                        # the walker returned ``[]`` for the canonical
                        # star-import leaker before this branch landed).
                        # Defense-in-depth ruff F403 also bans star
                        # imports project-wide, so this branch is the
                        # belt to F403's suspenders.
                        if alias.name == "*":
                            callable_aliases.update(
                                AuditKeyEnvScrubInvariant.SUBPROCESS_CALLABLES
                            )
                        elif alias.name in AuditKeyEnvScrubInvariant.SUBPROCESS_CALLABLES:
                            callable_aliases.add(alias.asname or alias.name)
        # Second pass — fixed-point rebinding closure. ``sub = subprocess``
        # rebinds the module; ``r = run`` rebinds a callable. Iterate to
        # a fixed point so chains like ``a = subprocess; b = a; b.run(...)``
        # are also caught. Modeled on
        # ``ThresholdApplyIsolationInvariant._module_violates`` lines
        # 1942-1965 (Assign + AnnAssign rebind tracking).
        changed = True
        while changed:
            changed = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Name):
                        if node.value.id in module_aliases:
                            for tgt in node.targets:
                                if isinstance(tgt, ast.Name) and tgt.id not in module_aliases:
                                    module_aliases.add(tgt.id)
                                    changed = True
                        elif node.value.id in callable_aliases:
                            for tgt in node.targets:
                                if isinstance(tgt, ast.Name) and tgt.id not in callable_aliases:
                                    callable_aliases.add(tgt.id)
                                    changed = True
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    if isinstance(node.value, ast.Name) and isinstance(node.target, ast.Name):
                        if (
                            node.value.id in module_aliases
                            and node.target.id not in module_aliases
                        ):
                            module_aliases.add(node.target.id)
                            changed = True
                        elif (
                            node.value.id in callable_aliases
                            and node.target.id not in callable_aliases
                        ):
                            callable_aliases.add(node.target.id)
                            changed = True
        return module_aliases, callable_aliases

    @staticmethod
    def _is_subprocess_call_with_bindings(
        node,
        module_aliases: set[str],
        callable_aliases: set[str],
    ) -> bool:
        """Return True iff ``node`` is a subprocess call given the
        binding sets from :py:meth:`_collect_subprocess_bindings`.

        Recognises:
          * ``<module_alias>.<callable>(...)`` — covers canonical
            ``subprocess.run(...)`` AND ``import subprocess as sp`` →
            ``sp.run(...)``.
          * bare-name ``<callable_alias>(...)`` — covers ``from
            subprocess import run`` → ``run(...)`` AND ``from subprocess
            import run as r`` → ``r(...)``.
        """
        import ast

        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return (
                func.value.id in module_aliases
                and func.attr in AuditKeyEnvScrubInvariant.SUBPROCESS_CALLABLES
            )
        if isinstance(func, ast.Name):
            return func.id in callable_aliases
        return False

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

    @staticmethod
    def _collect_scrub_aliases(tree) -> set[str]:
        """Return names bound to ``scrub_env_for_subprocess`` via
        ``from <anywhere> import scrub_env_for_subprocess`` or
        ``from <anywhere> import scrub_env_for_subprocess as <alias>``.

        Mirrors the binding-tracking idiom in
        :py:meth:`_collect_subprocess_bindings` (lines 710-739) so future
        ``from .audit import scrub_env_for_subprocess as s`` /
        ``from story_automator.core.audit import scrub_env_for_subprocess
        as s`` idioms cannot silently trip a D-04 false-positive on the
        *allowed* scrub-name side — symmetric with the alias-binding
        coverage that already exists on the forbidden subprocess side.
        """
        import ast

        aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "scrub_env_for_subprocess":
                        aliases.add(alias.asname or alias.name)
        return aliases

    @staticmethod
    def _is_scrub_call(node, aliases: frozenset[str] | set[str] = frozenset()) -> bool:
        """Return True iff ``node`` is a call to ``scrub_env_for_subprocess``
        (bare-name, attribute, or import-alias form). Lifted to a
        staticmethod so the positive-failure regression test can
        exercise the env-keyword check directly without scanning the
        real skill tree.

        ``aliases`` is the per-module set returned by
        :py:meth:`_collect_scrub_aliases` — names bound to
        ``scrub_env_for_subprocess`` via ``from ... import ... as
        <alias>``. Default ``frozenset()`` preserves backward-compatible
        bare-name + attribute matching for any non-walker caller.
        """
        import ast

        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "scrub_env_for_subprocess":
                return True
            if func.id in aliases:
                return True
        if isinstance(func, ast.Attribute) and func.attr == "scrub_env_for_subprocess":
            return True
        return False

    @staticmethod
    def _defines_scrub_helper(tree) -> bool:
        """Return True iff the module's top level defines
        ``scrub_env_for_subprocess`` — rename-proof signal that this
        *is* the helper's implementation file (current home:
        ``audit_env_scrub.py``; ``audit.py`` only re-exports). The
        invariant must not apply to the file that owns the helper, no
        matter which filename hosts it.
        """
        import ast

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "scrub_env_for_subprocess":
                return True
        return False

    @classmethod
    def _module_offenders(cls, tree) -> list[int]:
        """Return line numbers of every subprocess call in ``tree`` that
        does NOT pass ``env=scrub_env_for_subprocess(...)`` (or a name
        bound to such a result). Returns ``[]`` if the module defines
        the scrub helper itself (structural exemption) or imports no
        subprocess form.

        Lifted to a classmethod so the positive-failure regression test
        can exercise the FULL walker (binding-tracking + env-keyword
        check + scrubbed-name tracking) directly on synthetic source,
        proving the invariant is not vacuously true. Modeled on
        ``ThresholdApplyIsolationInvariant._module_violates`` /
        ``WorktreePerUnitIsolationInvariant._module_violates``.
        """
        import ast

        if cls._defines_scrub_helper(tree):
            return []

        module_aliases, callable_aliases = cls._collect_subprocess_bindings(tree)
        if not module_aliases and not callable_aliases:
            return []

        # Symmetric to ``module_aliases`` / ``callable_aliases`` on the
        # forbidden subprocess side: track aliased names of the
        # ALLOWED scrub helper so ``from .audit import
        # scrub_env_for_subprocess as s`` followed by ``env=s()`` is
        # NOT falsely flagged. Closes the asymmetry called out by the
        # D-04 regression-net audit.
        scrub_aliases = cls._collect_scrub_aliases(tree)
        _is_scrub_call_static = cls._is_scrub_call

        def is_scrub_call(node) -> bool:
            return _is_scrub_call_static(node, scrub_aliases)

        is_subprocess_call = cls._is_subprocess_call_with_bindings
        offenders: list[int] = []

        # Track names bound to scrub_env_for_subprocess(...) per visit so
        # callers may write:
        #   sandboxed = scrub_env_for_subprocess(env)
        #   subprocess.run(..., env=sandboxed)
        #
        # ``scrubbed_names`` is snapshot/restored on every FunctionDef /
        # AsyncFunctionDef boundary so the binding is scoped to the
        # ENCLOSING FUNCTION as the docstring at
        # ``test_ast_no_unscrubbed_subprocess_in_core`` promises. Without
        # the snapshot, a ``sandboxed = scrub_env_for_subprocess(...)``
        # in function ``a`` would leak into function ``b`` and silently
        # accept a ``subprocess.run(..., env=sandboxed)`` where
        # ``sandboxed`` is bound to a raw env dict — a false-negative
        # path for the D-04 audit-floor invariant.
        class _Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scrubbed_names: set[str] = set()

            def _visit_function(self, node) -> None:
                # Snapshot+restore the scrubbed-name set across the
                # function boundary so bindings made inside ``node`` do
                # not leak into sibling functions, and bindings made in
                # the enclosing scope (e.g. module-level) remain
                # available to nested closures.
                saved = self.scrubbed_names
                self.scrubbed_names = set(saved)
                try:
                    # Register parameters whose DEFAULT VALUE is a scrub
                    # call as scrubbed-name bindings inside the function
                    # body. Without this branch, ``def safe(env=
                    # scrub_env_for_subprocess()): subprocess.run(...,
                    # env=env)`` is falsely flagged — the parameter
                    # ``env`` is bound at def-time to a scrubbed dict
                    # but the walker only tracks bindings via
                    # ``visit_Assign`` / ``visit_AnnAssign``. Mirrors
                    # the symmetric AnnAssign branch in visit_AnnAssign
                    # to keep the binding tracker uniform across all
                    # bind-by-name forms. ``node.args.defaults`` are
                    # right-aligned to ``args.posonlyargs + args.args``;
                    # ``node.args.kw_defaults`` map 1:1 with
                    # ``args.kwonlyargs`` and may contain ``None`` for
                    # keyword-only params with no default.
                    positional = list(node.args.posonlyargs) + list(node.args.args)
                    defaults = list(node.args.defaults)
                    # Right-align defaults to positional params.
                    offset = len(positional) - len(defaults)
                    for idx, default in enumerate(defaults):
                        if is_scrub_call(default):
                            param = positional[offset + idx]
                            self.scrubbed_names.add(param.arg)
                    for param, default in zip(
                        node.args.kwonlyargs, node.args.kw_defaults
                    ):
                        if default is not None and is_scrub_call(default):
                            self.scrubbed_names.add(param.arg)
                    self.generic_visit(node)
                finally:
                    self.scrubbed_names = saved

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_function(node)

            def visit_Assign(self, node: ast.Assign) -> None:
                # When the RHS is a scrub call, ADD the target names; on
                # any other RHS, DISCARD them so a rebind from a
                # scrub-bound name to a raw value (dict literal,
                # os.environ.copy(), arbitrary Name) cannot silently
                # pass the D-04 walker. Without the discard branch, a
                # function that scrubs first and then reassigns the
                # same identifier to a raw env dict gets a free pass —
                # see the rebind-attack regression test
                # ``test_rebind_to_raw_invalidates_scrubbed_binding``.
                #
                # Tuple/list/starred unpack targets must recurse into
                # ``ast.Tuple`` / ``ast.List`` / ``ast.Starred`` patterns
                # so a rebind via ``sandboxed, _ = (raw_env, None)``
                # invalidates the prior scrub binding. Without the
                # recursion, the ``isinstance(tgt, ast.Name)`` guard
                # silently skips the unpack target and the previously
                # scrubbed binding remains accepted by the env-keyword
                # check — a real false-negative on the D-04 audit-floor
                # invariant. Conservative add-branch policy: only add on
                # plain ``ast.Name`` targets (no realistic scrub idiom
                # binds multiple scrubbed envs via tuple-unpack); always
                # discard ALL Name leaves of the target tree on any
                # non-scrub RHS.
                def _iter_name_targets(target):
                    if isinstance(target, ast.Name):
                        yield target
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        for elt in target.elts:
                            yield from _iter_name_targets(elt)
                    elif isinstance(target, ast.Starred):
                        yield from _iter_name_targets(target.value)

                if is_scrub_call(node.value):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            self.scrubbed_names.add(tgt.id)
                else:
                    for tgt in node.targets:
                        for name in _iter_name_targets(tgt):
                            self.scrubbed_names.discard(name.id)
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                # Mirror visit_Assign for PEP 526 annotated assignments
                # (e.g. ``scrubbed: dict = scrub_env_for_subprocess(env)``).
                # Without this branch, a benign type annotation on a
                # correctly-scrubbed call site falsely trips the D-04
                # audit-floor invariant — see the AnnAssign branches in
                # ThresholdApplyIsolationInvariant._module_violates and
                # UnifiedStateWriteIsolationInvariant._module_violates
                # for the same pattern. ``node.value`` is optional on
                # AnnAssign (bare annotations like ``x: int`` have
                # value=None) so guard before probing.
                #
                # Symmetric to ``visit_Assign``: when the RHS exists
                # but is NOT a scrub call, DISCARD the target so an
                # ``sandboxed: dict = {...}`` after a prior scrub
                # binding cannot silently leak through.
                if node.value is not None and isinstance(node.target, ast.Name):
                    if is_scrub_call(node.value):
                        self.scrubbed_names.add(node.target.id)
                    else:
                        self.scrubbed_names.discard(node.target.id)
                self.generic_visit(node)

            def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
                # Mirror visit_Assign for PEP 572 walrus-operator
                # assignments (e.g. ``if (scrubbed :=
                # scrub_env_for_subprocess(env)): subprocess.run(...,
                # env=scrubbed)``). Without this branch, a benign
                # walrus binding of a correctly-scrubbed call site
                # falsely trips the D-04 audit-floor invariant —
                # ``node.target`` is always a single ``ast.Name`` per
                # the Python grammar (PEP 572).
                #
                # Symmetric to ``visit_Assign``: when the RHS is NOT a
                # scrub call, DISCARD the target so a rebind via walrus
                # to a raw value cannot silently leak through.
                if isinstance(node.target, ast.Name):
                    if is_scrub_call(node.value):
                        self.scrubbed_names.add(node.target.id)
                    else:
                        self.scrubbed_names.discard(node.target.id)
                self.generic_visit(node)

            def visit_AugAssign(self, node: ast.AugAssign) -> None:
                # PEP 584 augmented-assignment rebinds (e.g.
                # ``sandboxed |= {"BMAD_AUDIT_KEY": "leak"}`` after a
                # prior ``sandboxed = scrub_env_for_subprocess(env)``)
                # mutate the existing value IN PLACE — for dicts this
                # merges the RHS keys into the dict the walker still
                # trusts, directly injecting BMAD_AUDIT_KEY into a
                # previously-scrubbed env. Without this branch, the
                # downstream ``subprocess.run(..., env=sandboxed)`` is
                # silently accepted, a real false-negative bypass of
                # the D-04 audit-floor invariant.
                #
                # An augmented assignment can NEVER re-establish a
                # scrub guarantee — the operator combines the existing
                # value with the RHS, and the walker cannot prove the
                # RHS is empty or that the operator preserves the
                # scrubbed-key invariant. So the policy is symmetric
                # with the unpack-target branch in visit_Assign: ALL
                # ``ast.Name`` leaves of the target tree are
                # unconditionally DISCARDED. The recursive Name-
                # collector mirrors the one in visit_Assign for
                # consistency with the tuple/list/starred unpack
                # discard policy.
                def _iter_name_targets(target):
                    if isinstance(target, ast.Name):
                        yield target
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        for elt in target.elts:
                            yield from _iter_name_targets(elt)
                    elif isinstance(target, ast.Starred):
                        yield from _iter_name_targets(target.value)

                for name in _iter_name_targets(node.target):
                    self.scrubbed_names.discard(name.id)
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                if is_subprocess_call(node, module_aliases, callable_aliases):
                    env_kw = next(
                        (kw for kw in node.keywords if kw.arg == "env"),
                        None,
                    )
                    ok = False
                    if env_kw is not None:
                        val = env_kw.value
                        if is_scrub_call(val):
                            ok = True
                        elif isinstance(val, ast.Name) and val.id in self.scrubbed_names:
                            ok = True
                    if not ok:
                        offenders.append(node.lineno)
                self.generic_visit(node)

        _Visitor().visit(tree)
        return offenders

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

        py_files: list[Path] = []
        for d in scan_dirs:
            if d.is_dir():
                py_files.extend(d.rglob("*.py"))
        for py_file in sorted(py_files):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for lineno in self._module_offenders(tree):
                offenders.append(
                    f"{py_file.relative_to(skill_src)}:{lineno} — "
                    f"subprocess call without scrub_env_for_subprocess"
                )

        self.assertEqual(
            offenders,
            [],
            "Unscrubbed subprocess calls found in core/. D-04 invariant broken:\n  "
            + "\n  ".join(offenders),
        )

    def test_positive_failure_synthetic_violator_is_caught(self) -> None:
        """Two-direction proof matching
        ``ThresholdApplyIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``
        / ``WorktreePerUnitIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``
        / ``UnifiedStateWriteIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``:

        Without this proof ``test_ast_no_unscrubbed_subprocess_in_core``
        could be vacuously true — a future refactor that breaks the
        env-keyword check, the scrubbed-name tracker, the binding
        collector, OR the structural skip would still produce
        ``offenders == []`` on the real skill tree and pass silently.
        The convention exists precisely so each AST-walker invariant
        carries a synthetic-source proof that the rule is operative.

        (a) Synthesize FOUR known-bad subprocess call patterns and
            assert the walker flags ALL of them:
              * subprocess.run(['ls'])             — no env at all
              * subprocess.run(['ls'], env=os.environ.copy())
              * sp.run(['ls'], env={'X': 'y'})     — import-as alias bypass
              * run(['ls'], env=child_env)         — from-import bare name,
                                                    env=name NOT bound to
                                                    scrub_env_for_subprocess
        (b) Synthesize FOUR known-good subprocess call patterns and
            assert the walker flags NONE of them:
              * env=scrub_env_for_subprocess(...)  — direct scrub call
              * scrubbed = scrub_env_for_subprocess(env); env=scrubbed
              * env=audit.scrub_env_for_subprocess(...)
                                                   — attribute form
              * (no subprocess import at all)      — unrelated run() call
        (c) Structural-skip proof: a synthetic module that DEFINES
            ``scrub_env_for_subprocess`` at top level must be exempt
            even if it contains a known-bad subprocess call — pins the
            rename-proof skip helper.
        """
        import ast

        # (a) BAD — no env at all.
        no_env_src = textwrap.dedent(
            """
            import subprocess

            def leak():
                subprocess.run(["ls"])
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(no_env_src))),
            1,
            "Walker FAILED to flag subprocess call with no env= at all — "
            "env-keyword check is broken or vacuous",
        )

        # (a) BAD — env=os.environ.copy().
        environ_copy_src = textwrap.dedent(
            """
            import os
            import subprocess

            def leak():
                subprocess.run(["ls"], env=os.environ.copy())
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(environ_copy_src))),
            1,
            "Walker FAILED to flag env=os.environ.copy() — env value "
            "check is not rejecting unscrubbed dict construction",
        )

        # (a) BAD — ``import subprocess as sp`` alias bypass with
        # env={} (NOT a scrub call). Pins the binding-tracker AND
        # env-keyword check together.
        sp_alias_src = textwrap.dedent(
            """
            import subprocess as sp

            def leak():
                sp.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(sp_alias_src))),
            1,
            "Walker FAILED to flag `import subprocess as sp` + "
            "sp.run(..., env={}) — alias-binding bypass",
        )

        # (a) BAD — ``from subprocess import run`` + env=<name> where
        # <name> was NOT bound to scrub_env_for_subprocess.
        from_import_src = textwrap.dedent(
            """
            from subprocess import run

            def leak(child_env):
                run(["ls"], env=child_env)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(from_import_src))),
            1,
            "Walker FAILED to flag bare `run(..., env=child_env)` where "
            "child_env was never bound to scrub_env_for_subprocess",
        )

        # (b) GOOD — env=scrub_env_for_subprocess() direct call.
        scrub_direct_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe():
                subprocess.run(["ls"], env=scrub_env_for_subprocess())
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(scrub_direct_src)),
            [],
            "Walker FALSELY flagged env=scrub_env_for_subprocess() — "
            "direct scrub call is the canonical safe form",
        )

        # (b) GOOD — scrubbed = scrub_env_for_subprocess(env); env=scrubbed.
        scrub_assigned_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                scrubbed = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(scrub_assigned_src)),
            [],
            "Walker FALSELY flagged env=<name> where <name> was bound "
            "to scrub_env_for_subprocess(...) — scrubbed-name tracker broken",
        )

        # (b) GOOD — env=audit.scrub_env_for_subprocess() attribute form.
        scrub_attr_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core import audit

            def safe():
                subprocess.run(["ls"], env=audit.scrub_env_for_subprocess())
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(scrub_attr_src)),
            [],
            "Walker FALSELY flagged env=audit.scrub_env_for_subprocess() — "
            "attribute-form scrub call must be accepted",
        )

        # (b) GOOD — no subprocess import at all. Unrelated bare run()
        # must NOT trip the walker.
        no_import_src = textwrap.dedent(
            """
            def run(args, env=None):
                return None

            def innocent():
                run(["ls"], env={"FOO": "bar"})
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(no_import_src)),
            [],
            "Walker FALSELY flagged unrelated run() with no subprocess "
            "import — binding-tracker is over-broad",
        )

        # (c) Structural-skip proof — a module defining
        # ``scrub_env_for_subprocess`` at top level is exempt even with
        # a known-bad call. Pins the rename-proof skip helper used at
        # line ~780.
        defines_helper_src = textwrap.dedent(
            """
            import subprocess

            def scrub_env_for_subprocess(env=None):
                return {}

            def self_test():
                # The implementation file itself may shell out without
                # scrubbing — e.g. for a smoke test of the helper.
                subprocess.run(["ls"])
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(defines_helper_src)),
            [],
            "Walker FAILED to honour the structural skip for modules "
            "defining scrub_env_for_subprocess at top level — "
            "rename-proof skip helper is broken",
        )

    def test_annassign_scrub_binding_is_tracked(self) -> None:
        """PEP 526 annotated assignment of a scrub call must register
        the target name in ``scrubbed_names`` — same as a plain
        ``ast.Assign``. Without ``visit_AnnAssign`` mirroring
        ``visit_Assign``, ``e: dict = scrub_env_for_subprocess(env)``
        silently fails to bind ``e``, and the follow-up
        ``subprocess.run(..., env=e)`` is falsely flagged.

        This is a latent false-positive in the D-04 audit-floor
        invariant: no current core/ module uses the annotated pattern,
        so the suite passes today — but the moment somebody writes
        ``child_env: dict[str, str] = scrub_env_for_subprocess(...)``
        CI breaks for a non-issue. Modeled on the AnnAssign tests in
        ``ThresholdApplyIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``
        (lines 1690-1722).

        Negative case: a bare annotation ``x: int`` (no value) must
        not trip the visitor — ``node.value`` is ``None`` for those,
        and the AnnAssign branch must guard before probing.
        """
        import ast

        # (a) GOOD — annotated assignment of a direct scrub call.
        # Mirrors the canonical safe form ``scrubbed =
        # scrub_env_for_subprocess(env)`` exactly, just with a PEP 526
        # annotation; the walker must accept the follow-up
        # ``env=scrubbed`` exactly the same way.
        annassign_name_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                scrubbed: dict = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(annassign_name_src)),
            [],
            "Walker FALSELY flagged env=<name> where <name> was bound "
            "to scrub_env_for_subprocess(...) via an annotated assignment "
            "(AnnAssign) — visit_AnnAssign branch is missing from the "
            "binding tracker",
        )

        # (b) GOOD — annotated assignment of an attribute-form scrub call.
        annassign_attr_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core import audit

            def safe(env):
                scrubbed: dict = audit.scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(annassign_attr_src)),
            [],
            "Walker FALSELY flagged env=<name> where <name> was bound "
            "to audit.scrub_env_for_subprocess(...) via an annotated "
            "assignment — attribute-form scrub call inside AnnAssign "
            "must be accepted",
        )

        # (c) Robustness — a bare AnnAssign with no value (e.g.
        # ``x: int``) must not crash the visitor. ``node.value`` is
        # ``None`` for those, and the AnnAssign branch must guard
        # before probing. Also asserts the walker does not falsely
        # accept a subsequent unscrubbed call simply because a bare
        # annotation of the same name appears earlier.
        bare_annassign_src = textwrap.dedent(
            """
            import subprocess

            def leak():
                e: dict
                subprocess.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(bare_annassign_src))),
            1,
            "Walker either crashed on AnnAssign(value=None) or falsely "
            "accepted an unscrubbed env=dict literal after a bare "
            "annotation — visit_AnnAssign must guard ``node.value is "
            "not None`` AND must not bind a name without a scrub call",
        )

    def test_default_arg_and_walrus_scrub_bindings_are_tracked(self) -> None:
        """Function default arguments bound to a scrub call AND PEP 572
        walrus-operator bindings must register the target name in
        ``scrubbed_names`` — same as a plain ``ast.Assign`` /
        ``ast.AnnAssign``. Without ``_visit_function`` walking
        ``node.args.defaults`` / ``node.args.kw_defaults`` AND a
        ``visit_NamedExpr`` mirroring ``visit_Assign``, two latent
        false-positives in the D-04 walker silently break CI on
        legitimate refactors:

          (a) ``def safe(env=scrub_env_for_subprocess()):
                 subprocess.run(..., env=env)``
          (b) ``if (scrubbed := scrub_env_for_subprocess(env)):
                 subprocess.run(..., env=scrubbed)``

        Both are functionally-safe forms but the pre-fix walker only
        tracked bindings via ``visit_Assign`` / ``visit_AnnAssign``.
        Mirrors the AnnAssign coverage in
        ``test_annassign_scrub_binding_is_tracked`` — the convention is
        that every binding form the audit-floor docstring promises
        must be exercised by a positive-and-negative pair.

        Also asserts the DISCARD semantics of the walrus branch:
        ``scrubbed = scrub_env_for_subprocess(env)`` followed by
        ``if (scrubbed := {...}):`` must INVALIDATE the prior binding,
        symmetric with the ``visit_Assign`` discard branch pinned by
        ``test_rebind_to_raw_invalidates_scrubbed_binding``.
        """
        import ast

        # (a) GOOD — positional default bound to a direct scrub call.
        # The reproducer in the bug report. Parameter ``env`` is bound
        # at def-time to a scrubbed dict; the follow-up
        # ``subprocess.run(..., env=env)`` must be accepted.
        positional_default_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env=scrub_env_for_subprocess()):
                subprocess.run(["ls"], env=env)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(positional_default_src)),
            [],
            "Walker FALSELY flagged env=<param> where <param>'s default "
            "value is scrub_env_for_subprocess(...) — _visit_function "
            "must walk node.args.defaults and register parameter names "
            "whose default is a scrub call",
        )

        # (a) GOOD — keyword-only default bound to a scrub call.
        # ``node.args.kw_defaults`` maps 1:1 with ``args.kwonlyargs``
        # and may contain ``None``; the walker must guard against the
        # None entries and accept the scrub-call entries.
        kw_only_default_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(*, env=scrub_env_for_subprocess()):
                subprocess.run(["ls"], env=env)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(kw_only_default_src)),
            [],
            "Walker FALSELY flagged env=<kwonly param> where the kwonly "
            "default is scrub_env_for_subprocess(...) — _visit_function "
            "must walk node.args.kw_defaults symmetrically with "
            "node.args.defaults",
        )

        # (a) GOOD — attribute-form scrub call as positional default.
        attr_form_default_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core import audit

            def safe(env=audit.scrub_env_for_subprocess()):
                subprocess.run(["ls"], env=env)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(attr_form_default_src)),
            [],
            "Walker FALSELY flagged env=<param> where the default is "
            "audit.scrub_env_for_subprocess(...) — attribute-form scrub "
            "call in a default must be accepted",
        )

        # (a) BAD — default IS NOT a scrub call. Parameter ``env``
        # defaults to a raw dict literal; the follow-up
        # ``subprocess.run(..., env=env)`` must be flagged. Pins that
        # the default-walking branch only ADDS to ``scrubbed_names``
        # for genuine scrub calls.
        unsafe_default_src = textwrap.dedent(
            """
            import subprocess

            def leak(env={"BMAD_AUDIT_KEY": "leak"}):
                subprocess.run(["ls"], env=env)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(unsafe_default_src))),
            1,
            "Walker FAILED to flag env=<param> where the default is a "
            "raw dict literal — default-walking must only register "
            "scrub-call defaults, not all defaults indiscriminately",
        )

        # (b) GOOD — walrus-operator binding of a scrub call. Pins the
        # ``visit_NamedExpr`` branch.
        walrus_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                if (scrubbed := scrub_env_for_subprocess(env)):
                    subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(walrus_src)),
            [],
            "Walker FALSELY flagged env=<name> where <name> was bound "
            "to scrub_env_for_subprocess(...) via a walrus operator "
            "(NamedExpr) — visit_NamedExpr branch is missing from the "
            "binding tracker",
        )

        # (b) BAD — walrus-operator binding to a raw dict literal. Pins
        # the env-keyword check still catches the unsafe case even when
        # the unsafe value is bound via walrus.
        walrus_unsafe_src = textwrap.dedent(
            """
            import subprocess

            def leak():
                if (sandboxed := {"BMAD_AUDIT_KEY": "leak"}):
                    subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(walrus_unsafe_src))),
            1,
            "Walker FAILED to flag env=<name> where <name> was bound "
            "via walrus to a raw dict literal — visit_NamedExpr must "
            "only register scrub-call walrus bindings, not all walrus "
            "bindings",
        )

        # (b) BAD — walrus REBIND from a prior scrub binding to a raw
        # dict literal. Symmetric with the visit_Assign discard branch
        # pinned by ``test_rebind_to_raw_invalidates_scrubbed_binding``.
        walrus_rebind_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env):
                scrubbed = scrub_env_for_subprocess(env)
                if (scrubbed := {"BMAD_AUDIT_KEY": "leak"}):
                    subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(walrus_rebind_src))),
            1,
            "Walker FAILED to flag walrus REBIND from a prior scrub "
            "binding to a raw dict literal — visit_NamedExpr must "
            "DISCARD the target name on any non-scrub RHS, symmetric "
            "with visit_Assign",
        )

    def test_rebind_to_raw_invalidates_scrubbed_binding(self) -> None:
        """A name bound to ``scrub_env_for_subprocess(...)`` that is
        later REBOUND to a raw value (dict literal, ``os.environ.copy()``,
        another ``Name``, AnnAssign of a dict literal) must NOT remain
        in ``scrubbed_names`` — the subsequent
        ``subprocess.run(..., env=<rebound>)`` must be flagged as
        unscrubbed.

        Without the discard branch in ``visit_Assign`` /
        ``visit_AnnAssign``, the walker only ADDS to
        ``scrubbed_names``; it never removes. A function that
        scrubs first and then silently rebinds the same identifier
        to a raw env dict containing ``BMAD_AUDIT_KEY`` passes the
        walker as safe — a real false-negative on the D-04
        audit-floor trust-boundary invariant.

        Four bypass variants are covered:
          (a) ``sandboxed = scrub_env_for_subprocess(env)`` then
              ``sandboxed = {'BMAD_AUDIT_KEY': 'leaked'}``
          (b) rebind to ``os.environ.copy()``
          (c) rebind to a plain ``Name`` (the function's other
              parameter)
          (d) AnnAssign rebind: ``sandboxed: dict = {...}`` after
              a prior scrub binding

        Each variant asserts ``offenders`` is non-empty AND that
        the unscrubbed ``subprocess.run`` line is the one flagged.
        """
        import ast

        # (a) Plain Assign rebind to a raw dict literal — the
        # canonical bypass in the bug report.
        rebind_dict_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed = {"BMAD_AUDIT_KEY": "leaked"}
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(rebind_dict_src))),
            1,
            "Walker FAILED to flag rebind from scrub call to raw dict "
            "literal — scrubbed_names tracker never invalidates on "
            "rebind, defeating the D-04 audit-floor invariant",
        )

        # (b) Plain Assign rebind to os.environ.copy().
        rebind_environ_src = textwrap.dedent(
            """
            import os
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed = os.environ.copy()
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(rebind_environ_src))),
            1,
            "Walker FAILED to flag rebind from scrub call to "
            "os.environ.copy() — visit_Assign must discard the target "
            "name on any non-scrub RHS",
        )

        # (c) Plain Assign rebind to another Name (raw env parameter).
        rebind_name_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, raw):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed = raw
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(rebind_name_src))),
            1,
            "Walker FAILED to flag rebind from scrub call to a raw "
            "Name — the scrubbed-name tracker must invalidate on any "
            "non-scrub RHS, not only literal dict rebinds",
        )

        # (d) AnnAssign rebind to a raw dict literal after a prior
        # plain-Assign scrub binding. Mirrors the visit_AnnAssign gap.
        rebind_annassign_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed: dict = {"BMAD_AUDIT_KEY": "leaked"}
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(rebind_annassign_src))),
            1,
            "Walker FAILED to flag AnnAssign rebind from a prior scrub "
            "binding to a raw dict literal — visit_AnnAssign must "
            "discard the target name on any non-scrub RHS, symmetric "
            "with visit_Assign",
        )

        # Sanity: the canonical safe pattern (scrub then use directly,
        # no rebind) must STILL pass — the discard branch must not
        # accidentally invalidate a legitimately-scrubbed binding.
        safe_pattern_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                scrubbed = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(safe_pattern_src)),
            [],
            "Discard branch falsely invalidated a legitimately-scrubbed "
            "binding — the fix must only discard on REBIND, not on the "
            "initial bind",
        )

    def test_tuple_list_starred_unpack_rebind_invalidates_scrubbed_binding(
        self,
    ) -> None:
        """A name bound to ``scrub_env_for_subprocess(...)`` that is
        later REBOUND via a tuple/list/starred unpack target (e.g.
        ``sandboxed, _ = (raw_env, None)``) must NOT remain in
        ``scrubbed_names`` — the subsequent ``subprocess.run(...,
        env=<rebound>)`` must be flagged as unscrubbed.

        Companion to
        :py:meth:`test_rebind_to_raw_invalidates_scrubbed_binding`,
        which covers only ``ast.Name`` target rebinds (variants a-d).
        Without recursion into ``ast.Tuple`` / ``ast.List`` /
        ``ast.Starred`` patterns inside ``visit_Assign``, a
        contributor can scrub once and silently rebind via tuple-
        unpack to a raw env dict — a real false-negative on the
        D-04 audit-floor invariant pinned by
        :py:meth:`test_ast_no_unscrubbed_subprocess_in_core`.

        Four bypass sub-variants are covered:
          (a) Tuple unpack:   ``sandboxed, _ = (raw_env, None)``
          (b) List unpack:    ``[sandboxed, _] = [raw_env, None]``
          (c) Starred unpack: ``sandboxed, *_ = (raw_env, None)``
          (d) Nested tuple:   ``(sandboxed, _), x = ((raw_env, None), 1)``

        Each variant asserts the unscrubbed ``subprocess.run`` line
        is flagged. Discard policy is conservative: ALL ``ast.Name``
        leaves in the unpack target tree are discarded on any non-
        scrub RHS, regardless of which element-position the leaf
        occupies — there is no realistic scrub idiom that binds
        multiple scrubbed envs via tuple-unpack, so the asymmetric
        discard-only policy keeps the invariant simple and closed.
        """
        import ast

        # (a) Tuple unpack — the canonical bypass in the bug report.
        tuple_unpack_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, raw_env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed, _ = (raw_env, None)
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(tuple_unpack_src))),
            1,
            "Walker FAILED to flag tuple-unpack rebind from scrub call to "
            "raw value — visit_Assign must recurse into ast.Tuple targets "
            "and discard every ast.Name leaf on any non-scrub RHS, "
            "defeating the D-04 audit-floor invariant otherwise",
        )

        # (b) List unpack.
        list_unpack_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, raw_env):
                sandboxed = scrub_env_for_subprocess(env)
                [sandboxed, _] = [raw_env, None]
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(list_unpack_src))),
            1,
            "Walker FAILED to flag list-unpack rebind from scrub call to "
            "raw value — visit_Assign must recurse into ast.List targets "
            "symmetric with ast.Tuple",
        )

        # (c) Starred unpack.
        starred_unpack_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, raw_env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed, *_ = (raw_env, None, None)
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(starred_unpack_src))),
            1,
            "Walker FAILED to flag starred-unpack rebind from scrub call "
            "to raw value — visit_Assign must unwrap ast.Starred targets "
            "to reach the inner Name leaf",
        )

        # (d) Nested tuple — recursion must reach arbitrary depth.
        nested_tuple_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, raw_env):
                sandboxed = scrub_env_for_subprocess(env)
                (sandboxed, _), x = ((raw_env, None), 1)
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(nested_tuple_src))),
            1,
            "Walker FAILED to flag nested-tuple rebind from scrub call to "
            "raw value — the unpack-target walk must be recursive, not a "
            "single-level loop over node.targets[0].elts",
        )

        # Sanity: the canonical safe pattern must STILL pass after the
        # unpack-target recursion lands — the discard policy must not
        # accidentally invalidate a legitimately-scrubbed binding.
        safe_pattern_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                scrubbed = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(safe_pattern_src)),
            [],
            "Unpack-target recursion falsely invalidated a legitimately-"
            "scrubbed binding — the fix must only discard Name leaves "
            "reachable from an unpack target, not the plain-Name target",
        )

    def test_augassign_rebind_invalidates_scrubbed_binding(self) -> None:
        """A name bound to ``scrub_env_for_subprocess(...)`` that is
        later REBOUND via an augmented-assignment operator (``|=``,
        ``+=``, ``&=``, ``-=`` etc.) must NOT remain in
        ``scrubbed_names`` — the subsequent ``subprocess.run(...,
        env=<rebound>)`` must be flagged as unscrubbed.

        Companion to
        :py:meth:`test_rebind_to_raw_invalidates_scrubbed_binding`
        (Assign / AnnAssign rebinds) and
        :py:meth:`test_tuple_list_starred_unpack_rebind_invalidates_scrubbed_binding`
        (unpack-target rebinds). Without ``visit_AugAssign`` the
        walker generic-visits the rebind node, so the binding stays
        in ``scrubbed_names`` and the downstream
        ``subprocess.run(..., env=<rebound>)`` is silently accepted —
        a real false-negative bypass of the D-04 audit-floor invariant.

        The ``|=`` variant is the most dangerous: PEP 584 dict union-
        update merges the RHS keys IN PLACE, so an attacker who can
        write the immediately-following statement can inject
        ``BMAD_AUDIT_KEY`` into a dict the walker still trusts. The
        ``+=`` / ``&=`` variants pin that the policy is symmetric
        across all augmented-assignment operators — the walker
        cannot prove ANY operator preserves the scrubbed-key
        invariant.

        Three bypass sub-variants are covered:
          (a) ``sandboxed |= {"BMAD_AUDIT_KEY": "leak"}`` (PEP 584
              dict union-update — the canonical bypass in the bug
              report)
          (b) ``sandboxed += [...]`` (treat any AugAssign operator
              symmetrically; the operator family must be closed-set
              not enumerated)
          (c) ``sandboxed &= {...}`` (intersection update — even an
              operator that REMOVES keys must invalidate the
              scrubbed binding because the walker has no way to
              prove the result is still scrub-equivalent)
        """
        import ast

        # (a) ``|=`` dict union-update — the canonical bypass.
        ior_rebind_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed |= {"BMAD_AUDIT_KEY": "leak"}
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(ior_rebind_src))),
            1,
            "Walker FAILED to flag ``|=`` augmented-assignment rebind "
            "from a prior scrub binding — visit_AugAssign must DISCARD "
            "the target name unconditionally because PEP 584 dict "
            "union-update merges tainted keys in place, defeating the "
            "D-04 audit-floor invariant otherwise",
        )

        # (b) ``+=`` symmetric coverage — any AugAssign operator must
        # invalidate.
        iadd_rebind_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, taint):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed += taint
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(iadd_rebind_src))),
            1,
            "Walker FAILED to flag ``+=`` augmented-assignment rebind — "
            "the discard policy must be symmetric across ALL AugAssign "
            "operators, not gated on ``|=`` alone, since the walker "
            "cannot prove any operator preserves the scrubbed invariant",
        )

        # (c) ``&=`` intersection — even removal-only operators must
        # invalidate the binding.
        iand_rebind_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def evil(env, mask):
                sandboxed = scrub_env_for_subprocess(env)
                sandboxed &= mask
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(iand_rebind_src))),
            1,
            "Walker FAILED to flag ``&=`` augmented-assignment rebind — "
            "even removal-only operators must discard the scrubbed "
            "binding because the walker has no way to prove the "
            "post-operator dict is still scrub-equivalent",
        )

        # Sanity: the canonical safe pattern must STILL pass after
        # visit_AugAssign lands — the discard branch must not leak
        # into unrelated bindings.
        safe_pattern_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def safe(env):
                scrubbed = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(safe_pattern_src)),
            [],
            "visit_AugAssign falsely invalidated a legitimately-scrubbed "
            "binding — the discard must fire ONLY when the binding "
            "target itself is the AugAssign target, not for unrelated "
            "AugAssigns elsewhere in the function",
        )

    def test_scrub_import_alias_is_tracked(self) -> None:
        """``from <anywhere> import scrub_env_for_subprocess as <alias>``
        must register ``<alias>`` as an accepted scrub-call name — same
        as the canonical bare-name ``scrub_env_for_subprocess`` is
        accepted directly.

        Without an ``ImportFrom`` collection pass mirroring
        :py:meth:`_collect_subprocess_bindings` (lines 710-739), a
        contributor writing ``from .audit import
        scrub_env_for_subprocess as s`` followed by
        ``subprocess.run(..., env=s())`` is silently flagged as
        unscrubbed by the D-04 audit-floor invariant — a latent
        false-positive that breaks CI on a legitimate refactor the
        moment somebody adopts the aliased-import idiom.

        The asymmetry is the root cause: the *forbidden* subprocess
        side already tracks ``import subprocess as sp`` and ``from
        subprocess import run as r`` (see
        ``_collect_subprocess_bindings`` lines 710-739), but the
        *allowed* scrub side hard-codes the literal name. This test
        pins the symmetric alias-collection helper
        (``_collect_scrub_aliases``) so the gap cannot regress.

        Negative case (c): a module that aliases ``scrub_env_for_subprocess``
        in an import but then calls ``subprocess.run`` WITHOUT an env=
        keyword must still be flagged — the alias collection must not
        accidentally relax the unrelated env-keyword check.
        """
        import ast

        # (a) GOOD — direct aliased call ``env=s()`` after ``from ...
        # import scrub_env_for_subprocess as s``. This is the
        # repro-case in the bug report.
        aliased_direct_src = textwrap.dedent(
            """
            from story_automator.core.audit import scrub_env_for_subprocess as s
            import subprocess

            def safe():
                subprocess.run(["ls"], env=s())
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(aliased_direct_src)),
            [],
            "Walker FALSELY flagged env=s() where ``s`` was bound to "
            "scrub_env_for_subprocess via ``from ... import "
            "scrub_env_for_subprocess as s`` — _is_scrub_call must "
            "consult the import-alias map symmetric with "
            "_collect_subprocess_bindings on the forbidden side",
        )

        # (b) GOOD — aliased assigned variant: ``scrubbed = s(env)``
        # followed by ``env=scrubbed``. Pins that the scrubbed-name
        # tracker recognises the aliased call AS a scrub call when
        # binding the target name.
        aliased_assigned_src = textwrap.dedent(
            """
            from story_automator.core.audit import scrub_env_for_subprocess as s
            import subprocess

            def safe(env):
                scrubbed = s(env)
                subprocess.run(["ls"], env=scrubbed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(aliased_assigned_src)),
            [],
            "Walker FALSELY flagged env=scrubbed where ``scrubbed`` was "
            "bound to s(env) and ``s`` was an alias for "
            "scrub_env_for_subprocess — visit_Assign must treat aliased "
            "scrub calls as scrub calls for binding purposes",
        )

        # (c) BAD — alias is imported but the actual call still lacks
        # any env= keyword. The alias map must not relax the unrelated
        # env-keyword check. This pins that the alias-collection helper
        # is additive (accept more scrub calls) rather than subtractive
        # (skip the env= check entirely once any scrub alias is seen).
        aliased_but_no_env_src = textwrap.dedent(
            """
            from story_automator.core.audit import scrub_env_for_subprocess as s
            import subprocess

            def leak():
                subprocess.run(["ls"])
            """
        )
        self.assertEqual(
            len(self._module_offenders(ast.parse(aliased_but_no_env_src))),
            1,
            "Walker FAILED to flag subprocess.run with NO env= keyword "
            "after an aliased-import line — alias collection must be "
            "additive (accept more scrub calls), not subtractive (skip "
            "the env-keyword check)",
        )

        # (d) GOOD — bare ``from ... import scrub_env_for_subprocess``
        # without ``as``. The canonical name must continue to work
        # exactly as before; the alias collection must not regress the
        # zero-alias case. (Without this control, the bare-name path
        # could be silently broken by a refactor of the alias map.)
        bare_import_src = textwrap.dedent(
            """
            from story_automator.core.audit import scrub_env_for_subprocess
            import subprocess

            def safe():
                subprocess.run(["ls"], env=scrub_env_for_subprocess())
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(bare_import_src)),
            [],
            "Walker FALSELY flagged the canonical bare-name "
            "scrub_env_for_subprocess() form — alias collection must "
            "not regress the non-aliased import path",
        )

    def test_scrub_binding_is_function_scoped(self) -> None:
        """The docstring at ``test_ast_no_unscrubbed_subprocess_in_core``
        promises the walker accepts ``env=<name>`` only when ``<name>``
        was bound by ``scrub_env_for_subprocess(...)`` IN THE SAME
        FUNCTION. Without ``visit_FunctionDef`` / ``visit_AsyncFunctionDef``
        snapshotting ``scrubbed_names``, a binding made in function A
        leaks into function B and silently accepts an unscrubbed
        ``subprocess.run(..., env=<same name>)`` there — a false-negative
        path for the D-04 audit-floor invariant.
        """
        import ast

        # (a) BAD — function ``a`` binds ``sandboxed`` via scrub_env, then
        # function ``b`` binds the SAME name to a raw env dict and calls
        # subprocess.run(..., env=sandboxed). With module-scoped
        # tracking, b's call is falsely accepted; with function-scoped
        # tracking, b's call is flagged.
        cross_function_leak_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def a(env):
                sandboxed = scrub_env_for_subprocess(env)
                return sandboxed

            def b(raw_env):
                sandboxed = raw_env
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        offenders = self._module_offenders(ast.parse(cross_function_leak_src))
        self.assertEqual(
            len(offenders),
            1,
            "Walker FAILED to flag subprocess.run(env=sandboxed) inside "
            "function ``b`` even though ``sandboxed`` is bound to a raw "
            "env dict there — module-scoped scrubbed_names is leaking "
            "function ``a``'s binding into ``b``'s scope, contradicting "
            "the 'in the same function' contract in the docstring at "
            "test_ast_no_unscrubbed_subprocess_in_core",
        )

        # (b) BAD — ordering-independent variant: function ``b`` (the
        # leaker) appears BEFORE function ``a`` (the scrubber) in source
        # order. The walker must flag b's call regardless of source
        # order; module-scoped tracking that processes a first would
        # produce a different verdict than module-scoped tracking that
        # processes b first, so this case pins the per-function reset
        # rather than just a "names from later functions don't bleed
        # backward" weaker property.
        reversed_order_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def b(raw_env):
                sandboxed = raw_env
                subprocess.run(["ls"], env=sandboxed)

            def a(env):
                sandboxed = scrub_env_for_subprocess(env)
                return sandboxed
            """
        )
        offenders = self._module_offenders(ast.parse(reversed_order_src))
        self.assertEqual(
            len(offenders),
            1,
            "Walker FAILED to flag subprocess.run(env=sandboxed) inside "
            "function ``b`` when ``b`` appears before ``a`` in source "
            "order — function-scope isolation must be order-independent",
        )

        # (c) BAD — undefined name case. Function ``a`` binds
        # ``sandboxed`` via scrub_env; function ``b`` references the
        # SAME name without defining it. At runtime ``b`` would raise
        # NameError; at AST-check time the walker must still flag
        # because the name is not bound to scrub_env_for_subprocess
        # IN THE SAME FUNCTION.
        undefined_name_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def a(env):
                sandboxed = scrub_env_for_subprocess(env)
                return sandboxed

            def b():
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        offenders = self._module_offenders(ast.parse(undefined_name_src))
        self.assertEqual(
            len(offenders),
            1,
            "Walker FAILED to flag subprocess.run(env=sandboxed) inside "
            "function ``b`` where ``sandboxed`` is not defined — "
            "module-scoped scrubbed_names is bleeding from ``a``",
        )

        # (d) GOOD — async-function variant of the same-function safe
        # pattern. Pins the AsyncFunctionDef branch of the per-function
        # snapshot.
        async_safe_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            async def safe(env):
                sandboxed = scrub_env_for_subprocess(env)
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(async_safe_src)),
            [],
            "Walker FALSELY flagged a same-function scrub-and-use pattern "
            "inside an async def — visit_AsyncFunctionDef must mirror "
            "visit_FunctionDef's snapshot behavior",
        )

        # (e) BAD — async cross-function leak. Pins that the
        # AsyncFunctionDef branch RESTORES the saved scrubbed_names on
        # exit (not just that it snapshots on entry).
        async_cross_function_leak_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            async def a(env):
                sandboxed = scrub_env_for_subprocess(env)
                return sandboxed

            async def b(raw_env):
                sandboxed = raw_env
                subprocess.run(["ls"], env=sandboxed)
            """
        )
        offenders = self._module_offenders(ast.parse(async_cross_function_leak_src))
        self.assertEqual(
            len(offenders),
            1,
            "Walker FAILED to flag async-function cross-function leak — "
            "visit_AsyncFunctionDef must restore the saved scrubbed_names",
        )

        # (f) GOOD — nested closure inherits the enclosing function's
        # scrub binding. The snapshot pattern uses ``set(saved)`` (a
        # COPY), so an inner function reads its enclosing function's
        # bindings while its own bindings do not leak out.
        nested_closure_src = textwrap.dedent(
            """
            import subprocess
            from story_automator.core.audit import scrub_env_for_subprocess

            def outer(env):
                sandboxed = scrub_env_for_subprocess(env)

                def inner():
                    subprocess.run(["ls"], env=sandboxed)

                inner()
            """
        )
        self.assertEqual(
            self._module_offenders(ast.parse(nested_closure_src)),
            [],
            "Walker FALSELY flagged a nested closure reading its "
            "enclosing function's scrubbed name — the per-function "
            "snapshot must seed the inner scope from the saved set",
        )

    def test_positive_failure_bypass_idioms_are_caught(self) -> None:
        """Two-direction proof for D-04 binding-tracking — the walker
        must catch EIGHT idiomatic Python aliasing patterns that a
        literal ``subprocess.<name>(...)`` predicate silently misses:

          (a) ``import subprocess as sp`` → ``sp.run(...)``
          (b) ``from subprocess import run`` → ``run(...)``
          (c) ``from subprocess import run as r`` → ``r(...)``
          (e) ``sub = subprocess`` plain Assign rebind → ``sub.run(...)``
          (f) ``sub: object = subprocess`` AnnAssign rebind →
              ``sub.run(...)``
          (g) chained rebind ``a = subprocess; b = a`` →
              ``b.run(...)`` (transitive closure)
          (h) callable rebind ``from subprocess import run; r = run`` →
              ``r(...)``
          (i) star import ``from subprocess import *`` → bare-name
              ``run(...)`` / ``Popen(...)`` / ``call(...)`` /
              ``check_call(...)`` / ``check_output(...)``

        Plus the canonical baseline:
          (d) ``import subprocess`` → ``subprocess.run(...)``

        Modeled on
        ``ThresholdApplyIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``
        (lines 1264-1340): each synthetic source is parsed, the
        binding-collection helper is run, and the predicate is asserted
        to flag the call. Negative case (no subprocess import at all)
        is also asserted to confirm the walker doesn't false-positive
        on unrelated ``run(...)`` calls.

        Without binding-tracking (the pre-fix predicate which only
        recognised ``ast.Attribute(value=ast.Name('subprocess'),
        attr in {run,Popen,...})``), patterns (a)/(b)/(c) silently exit
        the D-04 trust-boundary net while the audit-floor suite stays
        green — the regression net itself is broken. The (e)/(f)/(g)/(h)
        rebind cases close the gap with sibling C5/G2 invariants that
        track ``ast.Assign`` / ``ast.AnnAssign`` rebinding (lines
        1942-1965 / 2911-2935).
        """
        import ast

        # Helper: parse, collect bindings, locate the leaking call, run
        # predicate.
        def _flag(src: str) -> bool:
            tree = ast.parse(textwrap.dedent(src))
            module_aliases, callable_aliases = self._collect_subprocess_bindings(
                tree
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and self._is_subprocess_call_with_bindings(
                    node, module_aliases, callable_aliases
                ):
                    return True
            return False

        # (d) Canonical baseline — predicate MUST flag.
        canonical_src = """
            import subprocess

            def leak():
                subprocess.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(canonical_src),
            "Walker FAILED to flag canonical `subprocess.run(...)` — predicate broken",
        )

        # (a) ``import subprocess as sp`` rebind.
        sp_alias_src = """
            import subprocess as sp

            def leak():
                sp.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(sp_alias_src),
            "Walker FAILED to flag `import subprocess as sp` + `sp.run(...)` — "
            "binding-tracking missing for ast.Import asname",
        )

        # (b) ``from subprocess import run`` bare-name call.
        from_import_src = """
            from subprocess import run

            def leak():
                run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(from_import_src),
            "Walker FAILED to flag `from subprocess import run` + `run(...)` — "
            "binding-tracking missing for ast.ImportFrom",
        )

        # (c) ``from subprocess import run as r`` renamed call.
        from_import_as_src = """
            from subprocess import run as r

            def leak():
                r(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(from_import_as_src),
            "Walker FAILED to flag `from subprocess import run as r` + `r(...)` — "
            "binding-tracking missing for ast.ImportFrom asname",
        )

        # (e) ``sub = subprocess`` plain Assign rebind. Pins the
        # ast.Assign arm of the rebind closure mirroring
        # ThresholdApplyIsolationInvariant._module_violates lines
        # 1942-1952. Without the rebind closure, ``sub.run(...)`` is
        # silently treated as a non-subprocess call.
        assign_rebind_src = """
            import subprocess

            sub = subprocess

            def leak():
                sub.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(assign_rebind_src),
            "Walker FAILED to flag `sub = subprocess` + `sub.run(...)` — "
            "binding-tracking missing for ast.Assign module-rebind "
            "(strictly weaker than C5/G2 sibling invariants)",
        )

        # (f) ``sub: object = subprocess`` AnnAssign rebind. Pins the
        # ast.AnnAssign arm of the rebind closure mirroring lines
        # 1953-1965.
        annassign_rebind_src = """
            import subprocess

            sub: object = subprocess

            def leak():
                sub.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(annassign_rebind_src),
            "Walker FAILED to flag `sub: object = subprocess` + `sub.run(...)` — "
            "binding-tracking missing for ast.AnnAssign module-rebind",
        )

        # (g) Chained rebind ``a = subprocess; b = a; b.run(...)`` —
        # transitive closure. The fixed-point loop in
        # _collect_subprocess_bindings must propagate through chains.
        chained_rebind_src = """
            import subprocess

            a = subprocess
            b = a

            def leak():
                b.run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(chained_rebind_src),
            "Walker FAILED to flag chained rebind `a = subprocess; b = a` + "
            "`b.run(...)` — rebind closure must iterate to fixed point",
        )

        # (h) Callable rebind — ``from subprocess import run; r = run``.
        # Pins that the rebind closure also propagates callable aliases,
        # not just module aliases.
        callable_rebind_src = """
            from subprocess import run

            r = run

            def leak():
                r(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(callable_rebind_src),
            "Walker FAILED to flag callable rebind `r = run` + `r(...)` — "
            "binding-tracking missing for callable-alias rebinding",
        )

        # (i) Star import ``from subprocess import *`` followed by
        # bare-name ``run(...)``. Without the star-arm in
        # _collect_subprocess_bindings, ``alias.name == '*'`` never
        # matches SUBPROCESS_CALLABLES, ``callable_aliases`` stays
        # empty, _module_offenders early-returns ``[]`` at the
        # ``not module_aliases and not callable_aliases`` guard, and
        # the leaking ``run(..., env={'BMAD_AUDIT_KEY': ...})`` call is
        # silently exempted from the trust-boundary net. ruff F403
        # bans star imports project-wide as defense-in-depth, but the
        # audit-floor walker is the structural net of last resort —
        # belt-and-suspenders is the contract.
        star_import_src = """
            from subprocess import *

            def leak():
                run(["ls"], env={"BMAD_AUDIT_KEY": "leak"})
        """
        self.assertTrue(
            _flag(star_import_src),
            "Walker FAILED to flag `from subprocess import *` + bare "
            "`run(...)` — star-imports must seed callable_aliases with "
            "the full SUBPROCESS_CALLABLES set",
        )

        # And the same star-import must also seed every other
        # callable, not just ``run``. Pins that the seed is the FULL
        # SUBPROCESS_CALLABLES set, not a subset.
        for callable_name in sorted(self.SUBPROCESS_CALLABLES):
            star_import_callable_src = f"""
            from subprocess import *

            def leak():
                {callable_name}(["ls"], env={{"BMAD_AUDIT_KEY": "leak"}})
        """
            self.assertTrue(
                _flag(star_import_callable_src),
                f"Walker FAILED to flag star-import + bare `{callable_name}(...)` — "
                "star-import seed must include every SUBPROCESS_CALLABLES entry",
            )

        # Negative — `run(...)` without any subprocess import MUST NOT
        # be flagged. Proves binding-tracking is precise, not over-broad.
        unrelated_src = """
            def run(args, env=None):
                return None

            def innocent():
                run(["ls"], env={"FOO": "bar"})
        """
        self.assertFalse(
            _flag(unrelated_src),
            "Walker FALSELY flagged unrelated `run(...)` with no subprocess "
            "import — binding-tracking is over-broad",
        )

        # Negative — ``from .subprocess import run`` (level=1, relative
        # import of a project-local sibling module named
        # ``subprocess.py``) MUST NOT be flagged. The walker collects
        # ``ast.ImportFrom`` only when ``node.level == 0`` (absolute
        # import of the stdlib name). A level >= 1 import targets a
        # package-local module; treating its ``run`` as a stdlib
        # subprocess callable would over-flag innocent ``run(...)`` calls
        # inside that module and contradict the precision contract
        # documented above. Also exercises the level=2 ``..`` case.
        relative_import_src = """
            from .subprocess import run

            def innocent():
                run(["ls"], env={"FOO": "bar"})
        """
        self.assertFalse(
            _flag(relative_import_src),
            "Walker FALSELY flagged ``from .subprocess import run`` (level=1, "
            "project-local sibling module) — relative imports do not target "
            "the stdlib ``subprocess`` module and must be excluded from the "
            "binding collector",
        )

        relative_import_parent_src = """
            from ..subprocess import run

            def innocent():
                run(["ls"], env={"FOO": "bar"})
        """
        self.assertFalse(
            _flag(relative_import_parent_src),
            "Walker FALSELY flagged ``from ..subprocess import run`` (level=2, "
            "parent-package local module) — same precision contract as the "
            "level=1 case applies to any ``node.level >= 1`` import",
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


# ---------------------------------------------------------------------------
# G2 — WorktreePerUnitIsolationInvariant
# ---------------------------------------------------------------------------
# Per-unit worktree isolation (spec docs/superpowers/specs/2026-06-23-g2-...)
# pins four safety properties:
#
#   1. ``core/collector_isolation.py`` MUST NOT mutate any process-global
#      state (cwd, env, signal handlers) and MUST NOT acquire any
#      ``_bmad/*.lock`` sidecar. Thread-safety of the parallel worker
#      pool relies on this — a future contributor adding ``os.chdir`` or
#      ``signal.signal(...)`` to the module would re-introduce the
#      cross-thread races G2 is designed to close.
#
#   2. The per-unit dispatch is centralized: only ``collector_isolation``
#      defines ``run_collectors_per_unit``, and the ONLY legal caller is
#      ``run_gate_collectors``'s structurally-recognized
#      ``if isolation_mode == "per_unit":`` branch. Anything else
#      (alias rebinding, AnnAssign rebinding, getattr-indirect,
#      importlib chain) bypasses the early kwarg validation in
#      ``run_production_gate`` / ``run_system_gate`` and is rejected.
#
#   3. The two-direction positive-failure proof matches the C5
#      ``ThresholdApplyIsolationInvariant`` form: synthetic violators
#      across every binding shape are flagged, AND the residual after
#      stripping the legitimate ``def`` from ``collector_isolation.py``
#      with a synthetic-violator injected MUST flag — closes the
#      vacuous-true hole the C5 post-impl review surfaced.
#
#   4. The safety-critical defaults ``isolation_mode="shared"`` and
#      ``max_workers=4`` are pinned at FOUR sites (``run_gate_collectors``,
#      ``run_production_gate``, ``_run_collectors``, ``run_system_gate``)
#      via ``inspect.signature``. Flipping any of these to ``"per_unit"``
#      is an operator-driven configuration change, not a default-flip.


class WorktreePerUnitIsolationInvariant(unittest.TestCase):
    """Pins G2 §7.5 — worktree-per-unit isolation. Five sub-tests:

    1. ``collector_isolation.py`` is process-global-state-free + lock-free.
    2. The Sub-test 1 glob scan ALSO covers the sibling
       ``collector_isolation_outcomes.py`` (extracted to keep the parent
       under the 500-LOC soft limit) — added as a round-1-fix-37
       regression to close the vacuous-pass hole where a violator placed
       into the sibling silently passed Sub-test 1.
    3. Only ``run_gate_collectors``'s ``isolation_mode == "per_unit"``
       dispatch may call ``run_collectors_per_unit``.
    4. Two-direction positive-failure proof: synthetic violators flagged,
       AND the residual after stripping the legitimate ``def`` from
       ``collector_isolation.py`` with a fake violator injected MUST flag.
    5. Safety-critical defaults pinned via ``inspect.signature`` at all
       four wiring sites.

    Mirrors ``AuditKeyEnvScrubInvariant`` for structural exemption,
    ``UnifiedStateWriteIsolationInvariant`` for binding tracking, and
    ``ThresholdApplyIsolationInvariant`` (the C5 post-impl review form)
    for the meaningful two-direction positive-failure proof.
    """

    # ------------------------------------------------------------------
    # Sub-test 1 — no process-global state mutation in collector_isolation
    # ------------------------------------------------------------------

    _FORBIDDEN_OS_CALLS: frozenset[str] = frozenset(
        {
            "chdir",
            "fchdir",
            "umask",
            "setpgrp",
            "setsid",
            "setgid",
            "setuid",
            "setresgid",
            "setresuid",
        }
    )
    _FORBIDDEN_ENVIRON_METHODS: frozenset[str] = frozenset(
        {"update", "pop", "clear", "setdefault", "__setitem__", "__delitem__"}
    )

    @classmethod
    def _is_os_environ_attribute(cls, node) -> bool:
        """Return True iff ``node`` is the AST shape ``os.environ``."""
        import ast

        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    @classmethod
    def _module_has_global_state_mutation(cls, tree) -> list[str]:
        """Walk ``tree`` and return list of violation descriptions.

        Rejects:
          * ``Call(func=Attribute(value=Name("os"), attr in _FORBIDDEN_OS_CALLS))``
          * ``Subscript(value=Attribute(value=Name("os"), attr="environ"))``
            as ``targets`` of ``Assign|AnnAssign|AugAssign`` OR as a
            ``Delete`` target.
          * ``Call(func=Attribute(value=os.environ, attr in
            _FORBIDDEN_ENVIRON_METHODS))``.
          * ``Call(func=Name("signal"))`` OR
            ``Call(func=Attribute(value=Name("signal"), attr="signal"))``.
          * ``Call(func=Name("get_gate_lock"))`` OR
            ``Call(func=Attribute(attr="get_gate_lock"))``.
        """
        import ast

        violations: list[str] = []

        def _is_environ_subscript(node) -> bool:
            return isinstance(node, ast.Subscript) and cls._is_os_environ_attribute(node.value)

        for node in ast.walk(tree):
            # os.chdir / os.umask / os.setsid / etc. Calls.
            if isinstance(node, ast.Call):
                fn = node.func
                if (
                    isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "os"
                    and fn.attr in cls._FORBIDDEN_OS_CALLS
                ):
                    violations.append(f"os.{fn.attr}() call at line {node.lineno}")
                # os.environ.update(...) / pop / clear / etc.
                if (
                    isinstance(fn, ast.Attribute)
                    and cls._is_os_environ_attribute(fn.value)
                    and fn.attr in cls._FORBIDDEN_ENVIRON_METHODS
                ):
                    violations.append(f"os.environ.{fn.attr}() call at line {node.lineno}")
                # signal.signal(...) — both bare-Name and Attribute forms.
                if isinstance(fn, ast.Name) and fn.id == "signal":
                    violations.append(f"signal(...) call at line {node.lineno}")
                if (
                    isinstance(fn, ast.Attribute)
                    and fn.attr == "signal"
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "signal"
                ):
                    violations.append(f"signal.signal(...) call at line {node.lineno}")
                # get_gate_lock(...) — both Name and Attribute forms.
                if isinstance(fn, ast.Name) and fn.id == "get_gate_lock":
                    violations.append(f"get_gate_lock() call at line {node.lineno}")
                if isinstance(fn, ast.Attribute) and fn.attr == "get_gate_lock":
                    violations.append(f"<receiver>.get_gate_lock() call at line {node.lineno}")
                # Post-impl review fold-in (MED #2): broaden the lock
                # surface to any FileLock(...) constructor and any
                # ``*_lock(...)`` helper. The spec §3 "Lock ordering"
                # row promised "Worker threads MUST NOT acquire ANY
                # ``_bmad/*.lock``" — the prior pin only caught
                # ``get_gate_lock``, missing ``FileLock``,
                # ``unified_state_lock``, ``calibration_lock_path``,
                # ``get_lineage_lock``, ``get_drift_lock``, etc.
                if isinstance(fn, ast.Name) and fn.id == "FileLock":
                    violations.append(f"FileLock(...) call at line {node.lineno}")
                if isinstance(fn, ast.Attribute) and fn.attr == "FileLock":
                    violations.append(f"<receiver>.FileLock(...) call at line {node.lineno}")
                # Generic ``*_lock(...)`` helpers (both Name and
                # Attribute forms). Excludes ``get_gate_lock`` (already
                # flagged above) to avoid double-counting.
                _GENERIC_LOCK_NAMES = {
                    "unified_state_lock",
                    "calibration_lock_path",
                    "get_lineage_lock",
                    "get_drift_lock",
                    "acquire_lock",
                    "gate_lock",
                }
                if isinstance(fn, ast.Name) and fn.id in _GENERIC_LOCK_NAMES:
                    violations.append(f"{fn.id}() call at line {node.lineno}")
                if isinstance(fn, ast.Attribute) and fn.attr in _GENERIC_LOCK_NAMES:
                    violations.append(f"<receiver>.{fn.attr}() call at line {node.lineno}")
            # os.environ["X"] = ... / os.environ["X"] += ... / del os.environ["X"]
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets: list = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                else:
                    targets = [node.target]
                for tgt in targets:
                    if _is_environ_subscript(tgt):
                        violations.append(f"os.environ[...] = ... assignment at line {node.lineno}")
            if isinstance(node, ast.Delete):
                for tgt in node.targets:
                    if _is_environ_subscript(tgt):
                        violations.append(f"del os.environ[...] at line {node.lineno}")

        return violations

    def test_ast_no_process_global_state_mutation_in_isolation_module(self) -> None:
        """Walks every ``core/collector_isolation*.py`` file and rejects every
        form of process-global state mutation that would break the parallel
        worker contract. Positive-failure proof: synthetic AST with each
        violation pattern is flagged.

        Post-impl review fold-in: the G2 plan extracted
        ``core/collector_isolation_outcomes.py`` as a sibling helper to keep
        ``collector_isolation.py`` under the 500-LOC soft limit. The four
        reifier helpers (``make_error_outcome`` / ``error_outcome`` /
        ``crash_outcome`` / ``audit_timeout_outcome``) ARE invoked from
        inside the ``ThreadPoolExecutor`` worker threads via
        ``_run_isolated`` — so a future contributor adding ``os.chdir``
        / ``os.environ[...]`` / ``signal.signal`` / ``FileLock`` to that
        sibling re-introduces the cross-thread races G2 was designed to
        close. The glob ``collector_isolation*.py`` covers the parent
        AND every sibling under the same prefix, matching the rename-
        proof exemption pattern used by ``AuditKeyEnvScrubInvariant``
        (``_defines_scrub_helper`` over ``rglob``).
        """
        import ast
        import textwrap

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        isolation_files = sorted((skill_src / "core").glob("collector_isolation*.py"))
        # Guard against an accidental empty glob — there MUST always be at
        # least the canonical ``collector_isolation.py`` parent module.
        self.assertTrue(
            isolation_files,
            "No core/collector_isolation*.py files found — glob expansion "
            "broken or the parent module was renamed without updating "
            "the audit-floor invariant",
        )
        canonical = skill_src / "core" / "collector_isolation.py"
        self.assertIn(
            canonical,
            isolation_files,
            "core/collector_isolation.py missing from glob expansion — "
            "the canonical isolation module must be scanned",
        )
        all_violations: list[str] = []
        for isolation_file in isolation_files:
            tree = ast.parse(isolation_file.read_text(encoding="utf-8"))
            file_violations = self._module_has_global_state_mutation(tree)
            for v in file_violations:
                all_violations.append(
                    f"{isolation_file.relative_to(skill_src)}: {v}"
                )
        self.assertEqual(
            all_violations,
            [],
            "core/collector_isolation*.py module(s) mutate process-global "
            "state — G2 thread-safety invariant broken:\n  "
            + "\n  ".join(all_violations),
        )

        # Positive-failure proof: each violation pattern, synthesised
        # individually, MUST be flagged by the walker.
        pattern_cases = {
            "os.chdir": "import os\ndef f():\n    os.chdir('/tmp')\n",
            "os.umask": "import os\ndef f():\n    os.umask(0o077)\n",
            "os.setsid": "import os\ndef f():\n    os.setsid()\n",
            "os.environ assign": ("import os\ndef f():\n    os.environ['X'] = 'y'\n"),
            "os.environ del": ("import os\ndef f():\n    del os.environ['X']\n"),
            "os.environ.update": ("import os\ndef f():\n    os.environ.update(a='b')\n"),
            "os.environ.pop": ("import os\ndef f():\n    os.environ.pop('X', None)\n"),
            "os.environ.clear": ("import os\ndef f():\n    os.environ.clear()\n"),
            "os.environ.setdefault": ("import os\ndef f():\n    os.environ.setdefault('X', 'y')\n"),
            "signal bare-name": (
                "from signal import signal\ndef f():\n    signal(1, lambda *a: None)\n"
            ),
            "signal attribute": (
                "import signal\ndef f():\n    signal.signal(1, lambda *a: None)\n"
            ),
            "get_gate_lock name": ("def f():\n    get_gate_lock('/tmp')\n"),
            "get_gate_lock attribute": ("import x\ndef f():\n    x.get_gate_lock('/tmp')\n"),
            "os.environ AnnAssign": ("import os\ndef f():\n    os.environ['X']: str = 'y'\n"),
            "os.environ AugAssign": ("import os\ndef f():\n    os.environ['X'] += 'z'\n"),
            # Post-impl review fold-in (MED #2) — broader lock surface.
            "FileLock name": (
                "from filelock import FileLock\ndef f():\n    FileLock('/tmp/x.lock')\n"
            ),
            "FileLock attribute": (
                "import filelock\ndef f():\n    filelock.FileLock('/tmp/x.lock')\n"
            ),
            "unified_state_lock": "def f():\n    unified_state_lock('.')\n",
            "unified_state_lock attribute": "import m\ndef f():\n    m.unified_state_lock('.')\n",
            "calibration_lock_path": "def f():\n    calibration_lock_path('.')\n",
            "get_lineage_lock": "def f():\n    get_lineage_lock('.')\n",
            "get_drift_lock": "def f():\n    get_drift_lock('.')\n",
        }
        for label, src in pattern_cases.items():
            synth_tree = ast.parse(textwrap.dedent(src))
            flagged = self._module_has_global_state_mutation(synth_tree)
            self.assertNotEqual(
                flagged,
                [],
                f"Walker FAILED to flag synthetic violator [{label}] — "
                f"invariant is vacuously true for this pattern",
            )

    def test_glob_scan_covers_sibling_collector_isolation_modules(self) -> None:
        """Regression for the round-1-fix-37 sibling-coverage gap.

        The G2 plan extracted ``core/collector_isolation_outcomes.py`` to
        keep the parent module under the 500-LOC soft limit. The four
        reifier helpers in that sibling (``make_error_outcome`` /
        ``error_outcome`` / ``crash_outcome`` /
        ``audit_timeout_outcome``) are invoked from inside the
        ``ThreadPoolExecutor`` worker threads via ``_run_isolated``, so
        they are subject to the same "no process-global state mutation"
        contract as the parent.

        Pre-fix, sub-test 1 hard-coded the scan target as
        ``core/collector_isolation.py`` and silently passed even when a
        violator (e.g. ``os.chdir('/tmp')``) was injected into the
        sibling. Post-fix, the glob ``collector_isolation*.py`` expands
        to BOTH files and the audit-floor structurally rejects any
        global-state mutation in either module.

        This regression test pins the structural property: the sibling
        module MUST be present in the glob expansion, and a synthetic
        violator placed in a sibling-shaped path MUST be flagged by the
        scan loop.
        """
        import ast

        skill_src = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
        )
        isolation_files = sorted((skill_src / "core").glob("collector_isolation*.py"))
        names = {p.name for p in isolation_files}
        self.assertIn(
            "collector_isolation.py",
            names,
            "Glob must include the canonical parent module",
        )
        self.assertIn(
            "collector_isolation_outcomes.py",
            names,
            "Glob must include the sibling helper module — pre-fix the "
            "sub-test only scanned the parent, so any contributor adding "
            "os.chdir / os.environ / signal.signal / FileLock to the "
            "sibling would silently re-introduce the cross-thread races "
            "the G2 milestone was designed to close",
        )

        # End-to-end positive-failure proof: simulating a violator inside
        # the sibling-module source MUST be flagged by the walker. This
        # closes the vacuous-pass that the round-1 reviewer reproduced
        # by injecting ``os.chdir('/tmp')`` into ``make_error_outcome``.
        # The walker is shape-based on ``os.chdir(...)`` (matching the
        # canonical ``import os`` form), so the appended violator MUST
        # use that exact AST shape.
        sibling_path = skill_src / "core" / "collector_isolation_outcomes.py"
        clean_src = sibling_path.read_text(encoding="utf-8")
        violator_src = clean_src + "\nimport os\nos.chdir('/tmp')\n"
        violator_tree = ast.parse(violator_src)
        flagged = self._module_has_global_state_mutation(violator_tree)
        self.assertNotEqual(
            flagged,
            [],
            "Walker FAILED to flag a synthetic violator injected into "
            "the sibling module shape — the glob-based scan in sub-test "
            "1 is vacuously true for collector_isolation_outcomes.py",
        )

        # Also assert that the CLEAN sibling source does NOT trip the
        # walker — pins the present-day baseline that the sibling is
        # mutation-free.
        clean_tree = ast.parse(clean_src)
        self.assertEqual(
            self._module_has_global_state_mutation(clean_tree),
            [],
            "Clean collector_isolation_outcomes.py source already trips "
            "the global-state-mutation walker — the sibling is supposed "
            "to be a PURE helper module per its docstring",
        )

    # ------------------------------------------------------------------
    # Sub-test 2 — no implicit per_unit dispatch outside isolation module
    # ------------------------------------------------------------------

    @staticmethod
    def _defines_isolation_runner(tree) -> bool:
        """Return True iff the module's top level defines
        ``def run_collectors_per_unit(...)`` — rename-proof signal that
        this *is* the implementation file (current home:
        ``core/collector_isolation.py``). Mirrors ``_defines_scrub_helper``
        in ``AuditKeyEnvScrubInvariant``.
        """
        import ast

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "run_collectors_per_unit":
                return True
        return False

    @staticmethod
    def _dispatches_via_isolation_mode(tree) -> bool:
        """Return True iff the module's top level defines
        ``def run_gate_collectors(...)`` whose body contains an ``If``
        whose test references ``Name("isolation_mode")`` AND whose
        comparators include ``Constant("per_unit")``.

        Refactor-tolerant: handles ``==``, ``in {...}``, ``match ... case
        "per_unit":``, AND intermediate-variable forms like
        ``mode = isolation_mode; if mode == "per_unit": ...``. The
        walker collects every ``Name`` ID that is rebound from
        ``isolation_mode`` (Assign / AnnAssign) and treats those as
        equivalent to the kwarg name when scanning ``If.test``.

        Mirrors the rename-proof exemption pattern from
        ``ThresholdApplyIsolationInvariant._is_cli_apply_handler``.
        """
        import ast

        def _test_references_isolation_alias(test_node, aliases) -> bool:
            for sub in ast.walk(test_node):
                if isinstance(sub, ast.Name) and sub.id in aliases:
                    return True
            return False

        def _test_contains_per_unit_constant(test_node) -> bool:
            for sub in ast.walk(test_node):
                if isinstance(sub, ast.Constant) and sub.value == "per_unit":
                    return True
            return False

        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name != "run_gate_collectors":
                continue
            # Build the alias set: any local Name bound from
            # isolation_mode (intermediate-variable shape).
            aliases: set[str] = {"isolation_mode"}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    if isinstance(sub.value, ast.Name) and sub.value.id in aliases:
                        for tgt in sub.targets:
                            if isinstance(tgt, ast.Name):
                                aliases.add(tgt.id)
                elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
                    if (
                        isinstance(sub.value, ast.Name)
                        and sub.value.id in aliases
                        and isinstance(sub.target, ast.Name)
                    ):
                        aliases.add(sub.target.id)
            # Look for an If whose test ties an alias to the
            # "per_unit" constant.
            for sub in ast.walk(node):
                if isinstance(sub, ast.If):
                    if _test_references_isolation_alias(
                        sub.test, aliases
                    ) and _test_contains_per_unit_constant(sub.test):
                        return True
                # Python 3.10+ match statement on isolation_mode.
                if isinstance(sub, ast.Match):
                    if isinstance(sub.subject, ast.Name) and sub.subject.id in aliases:
                        for case in sub.cases:
                            for pat_sub in ast.walk(case.pattern):
                                if (
                                    isinstance(pat_sub, ast.MatchValue)
                                    and isinstance(pat_sub.value, ast.Constant)
                                    and pat_sub.value.value == "per_unit"
                                ):
                                    return True
        return False

    @classmethod
    def _module_violates(cls, tree) -> bool:
        """Return True iff ``tree`` contains a direct or indirect call to
        ``run_collectors_per_unit`` and is NOT covered by either structural
        exemption. Binding-tracking walker modeled on
        ``UnifiedStateWriteIsolationInvariant._module_violates`` and
        ``ThresholdApplyIsolationInvariant._module_violates``.

        Tracks:
          * ``from X import run_collectors_per_unit as ALIAS`` → ALIAS
            forbidden (handles parenthesized form).
          * ``ALIAS = run_collectors_per_unit`` → LHS forbidden.
          * ``ALIAS: object = run_collectors_per_unit`` → LHS forbidden
            (the C5 post-impl AnnAssign branch fix).
          * Aliasing through ``Attribute`` value with
            ``attr == "run_collectors_per_unit"``.

        Flags:
          * ``Call(func=Name(N))`` with N in the forbidden set.
          * ``Call(func=Attribute(attr="run_collectors_per_unit"))``.
          * ``Call(func=Name("getattr"), args=[_, Constant("run_collectors_per_unit"), ...])``.
          * ``Attribute(attr="run_collectors_per_unit",
            value=Call(func=Attribute(attr="import_module"), ...))``.
        """
        import ast

        forbidden: set[str] = {"run_collectors_per_unit"}

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "run_collectors_per_unit":
                        forbidden.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Name) and node.value.id in forbidden:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            forbidden.add(tgt.id)
                elif (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr == "run_collectors_per_unit"
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
                    and node.value.attr == "run_collectors_per_unit"
                    and isinstance(node.target, ast.Name)
                ):
                    forbidden.add(node.target.id)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    if fn.id in forbidden:
                        return True
                    if fn.id == "getattr" and len(node.args) >= 2:
                        second = node.args[1]
                        if (
                            isinstance(second, ast.Constant)
                            and second.value == "run_collectors_per_unit"
                        ):
                            return True
                if isinstance(fn, ast.Attribute) and fn.attr == "run_collectors_per_unit":
                    return True
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "run_collectors_per_unit"
                and isinstance(node.value, ast.Call)
            ):
                inner = node.value.func
                if isinstance(inner, ast.Attribute) and inner.attr == "import_module":
                    return True
                if isinstance(inner, ast.Name) and inner.id == "import_module":
                    return True
        return False

    def test_ast_no_implicit_per_unit_dispatch_outside_isolation(self) -> None:
        """Walk every .py under BOTH ``core/`` AND ``commands/``; flag any
        call (direct, aliased, AnnAssign-rebound, getattr-indirect,
        importlib-indirect) to ``run_collectors_per_unit`` from a module
        not covered by either structural exemption.
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
            if self._defines_isolation_runner(tree):
                continue
            # Exemption (b): the structurally-recognized dispatcher
            # (``run_gate_collectors`` with ``isolation_mode == "per_unit"``).
            # Post-impl review fold-in: scope the dispatcher exemption to
            # STRICTLY ``core/collector_runner.py`` so an unrelated core/*
            # or commands/* module cannot self-exempt by defining a
            # confirm-shaped helper. Mirrors the path constraint that
            # the C5 ThresholdApplyIsolationInvariant tightened to
            # ``skill_src / "commands"``.
            collector_runner_path = skill_src / "core" / "collector_runner.py"
            if (
                py_file.resolve() == collector_runner_path.resolve()
                and self._dispatches_via_isolation_mode(tree)
            ):
                continue
            if self._module_violates(tree):
                offenders.append(str(py_file.relative_to(skill_src)))
        self.assertEqual(
            offenders,
            [],
            "Modules calling run_collectors_per_unit outside the "
            "structurally-recognized dispatch — G2 isolation invariant "
            "broken:\n  " + "\n  ".join(offenders),
        )

    # ------------------------------------------------------------------
    # Sub-test 3 — meaningful two-direction positive-failure proof
    # ------------------------------------------------------------------

    def test_positive_failure_synthetic_violator_is_caught(self) -> None:
        """Two-direction proof matching
        ``ThresholdApplyIsolationInvariant.test_positive_failure_synthetic_violator_is_caught``:

        (a) Synthesize source containing direct call + alias-rebinding
            call + AnnAssign-rebinding call + getattr-indirect call +
            importlib chain; assert ALL flagged.
        (b) Read the real ``collector_isolation.py`` source, AST-strip
            the ``def run_collectors_per_unit`` top-level FunctionDef,
            INJECT a synthetic ``_residual_check = run_collectors_per_unit;
            _residual_check(...)`` violator into the residual; walker
            MUST flag it. The C5 post-impl review found that residual-
            stripping alone was vacuously true (zero Call nodes
            referenced the name); injecting a synthetic call AFTER the
            strip makes the residual exercise the rule.
        """
        import ast
        import textwrap

        # (a) Direct call.
        direct_src = textwrap.dedent(
            """
            from story_automator.core.collector_isolation import (
                run_collectors_per_unit,
            )

            def evil_direct():
                run_collectors_per_unit('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(direct_src)),
            "AST walker FAILED to flag a direct call — invariant is vacuously true",
        )

        # (a) Alias rebinding call.
        alias_src = textwrap.dedent(
            """
            from story_automator.core.collector_isolation import (
                run_collectors_per_unit as _rcpu,
            )

            def evil_alias():
                _rcpu('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(alias_src)),
            "AST walker FAILED to flag an alias-rebinding call",
        )

        # (a) AnnAssign rebinding via Name (the C5 post-impl review fix).
        annassign_name_src = textwrap.dedent(
            """
            from story_automator.core.collector_isolation import (
                run_collectors_per_unit,
            )

            def evil_annassign_name():
                fn: object = run_collectors_per_unit
                fn('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(annassign_name_src)),
            "AST walker FAILED to flag AnnAssign(Name) rebind — first-pass "
            "binding tracker is missing the AnnAssign branch",
        )

        # (a) AnnAssign rebinding via Attribute.
        annassign_attr_src = textwrap.dedent(
            """
            from story_automator.core import collector_isolation as ci

            def evil_annassign_attr():
                fn: object = ci.run_collectors_per_unit
                fn('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(annassign_attr_src)),
            "AST walker FAILED to flag AnnAssign(Attribute) rebind",
        )

        # (a) Indirect getattr call.
        getattr_src = textwrap.dedent(
            """
            from story_automator.core import collector_isolation as ci

            def evil_getattr():
                fn = getattr(ci, 'run_collectors_per_unit')
                fn('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(getattr_src)),
            "AST walker FAILED to flag a getattr-indirect call",
        )

        # (a) importlib.import_module(...).run_collectors_per_unit chain.
        importlib_src = textwrap.dedent(
            """
            import importlib

            def evil_importlib():
                mod = importlib.import_module(
                    'story_automator.core.collector_isolation'
                )
                mod.run_collectors_per_unit('.', 'g', 'sha', {}, [])
            """
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(ast.parse(importlib_src)),
            "AST walker FAILED to flag importlib.import_module chain",
        )

        # (b) Real collector_isolation.py — meaningful two-direction proof.
        #     Strip the top-level def and INJECT a synthetic violator so
        #     the residual actually exercises the rule (C5 post-impl
        #     lesson: residual-only stripping was vacuously true).
        from story_automator.core import collector_isolation as ci_mod

        real_tree = ast.parse(Path(ci_mod.__file__).read_text(encoding="utf-8"))
        stripped_body = [
            n
            for n in real_tree.body
            if not (isinstance(n, ast.FunctionDef) and n.name == "run_collectors_per_unit")
        ]

        # (b.1) Inject a fake top-level violator into the residual.
        # Use the "residual_check = run_collectors_per_unit; residual_check(...)"
        # shape the spec calls out explicitly.
        violator_src = textwrap.dedent(
            """
            def _residual_check_caller():
                _residual_check = run_collectors_per_unit
                _residual_check('.', 'g', 'sha', {}, [])
            """
        )
        violator_def = ast.parse(violator_src).body[0]
        stripped_with_violator = ast.Module(
            body=stripped_body + [violator_def],
            type_ignores=[],
        )
        self.assertTrue(
            WorktreePerUnitIsolationInvariant._module_violates(stripped_with_violator),
            "Injecting a real violator into the residual collector_isolation.py "
            "tree did NOT trip the rule — the rule may be vacuously true",
        )

        # (b.2) Same residual without the injected violator must NOT trip.
        stripped = ast.Module(body=stripped_body, type_ignores=[])
        self.assertFalse(
            WorktreePerUnitIsolationInvariant._module_violates(stripped),
            "collector_isolation.py residual (without its own def) trips the "
            "violation rule — the file should not call run_collectors_per_unit "
            "anywhere else",
        )

    # ------------------------------------------------------------------
    # Sub-test 4 — safety-critical defaults pinned at four sites
    # ------------------------------------------------------------------

    def test_default_isolation_mode_is_shared(self) -> None:
        """Pin safety-critical defaults at FOUR sites via ``inspect.signature``.

        Flipping any of these defaults from ``"shared"`` to ``"per_unit"``
        is an operator-driven configuration change, NOT a default-flip.
        Likewise, ``max_workers=4`` is the documented default in §13 row
        2 ("No ``max_workers=None`` auto-tune. Explicit int default of 4.").
        """
        import inspect

        from story_automator.core.collector_runner import run_gate_collectors
        from story_automator.core.gate_orchestrator import (
            _run_collectors,
            run_production_gate,
        )
        from story_automator.core.system_gate import run_system_gate

        for fn in (
            run_gate_collectors,
            run_production_gate,
            _run_collectors,
            run_system_gate,
        ):
            sig = inspect.signature(fn)
            self.assertIn(
                "isolation_mode",
                sig.parameters,
                f"{fn.__qualname__} missing isolation_mode kwarg",
            )
            self.assertIn(
                "max_workers",
                sig.parameters,
                f"{fn.__qualname__} missing max_workers kwarg",
            )
            self.assertEqual(
                sig.parameters["isolation_mode"].default,
                "shared",
                f"{fn.__qualname__}(isolation_mode=...) default MUST be "
                f'"shared" — flipping to "per_unit" is an operator-driven '
                f"configuration change (spec §13 row 4)",
            )
            self.assertEqual(
                sig.parameters["max_workers"].default,
                4,
                f"{fn.__qualname__}(max_workers=...) default MUST be 4 "
                f"(spec §13 row 2 — explicit int, no auto-tune)",
            )


if __name__ == "__main__":
    unittest.main()
