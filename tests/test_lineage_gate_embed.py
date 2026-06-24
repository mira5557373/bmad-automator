"""C2 follow-up — gate_file embeds ``lineage_root``.

Symmetry test: both ``run_production_gate`` and ``run_system_gate``
must embed the on-disk lineage Merkle root onto every persisted gate
file. When no chain is present on disk, the field is the empty-string
sentinel "" — distinguishable from a real 64-hex root.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.innovation.lineage_ledger import (
    compute_lineage_root,
    make_lineage_entry,
    persist_lineage_entry,
)
from story_automator.core.system_env import ENV_TIER_MINIMAL, SystemEnvInfo
from story_automator.core.system_gate import run_system_gate


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _h(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _minimal_profile() -> dict:
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


def _make_gate_file() -> dict:
    """Mimic the shape returned by evaluate_gate for system-gate tests."""
    return {
        "gate_id": "sg1",
        "schema_version": 1,
        "tier": "system",
        "target": {"kind": "epic", "id": "E1"},
        "commit_sha": "abc",
        "profile": {"id": "test", "version": 1, "hash": "deadbeef"},
        "factory_version": "1.0.0",
        "categories": {},
        "overall": "PASS",
        "waivers": [],
        "evidence_bundle_hash": "",
    }


def _persist_demo_chain(project_root: Path) -> str:
    """Persist a 2-link chain on disk and return its merkle_root."""
    entries = []
    parent = ""
    for idx, (genre, slug, body) in enumerate(
        [("brainstorm", "demo", "a"), ("braindump", "demo", "b")],
    ):
        ent = make_lineage_entry(
            genre=genre, slug=slug,
            payload_hash=_h(body),
            parent_root=parent,
            timestamp_iso="2026-06-22T00:00:00Z",
        )
        entries.append(ent)
        parent = compute_lineage_root(entries)
        persist_lineage_entry(project_root, ent)
    return compute_lineage_root(entries)


class _GateTempMixin:
    def setUp(self) -> None:  # type: ignore[override]
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.profile = _minimal_profile()
        self.registry = CollectorRegistry()

    def tearDown(self) -> None:  # type: ignore[override]
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class ProductionGateLineageEmbedTests(_GateTempMixin, unittest.TestCase):
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_run_production_gate_embeds_lineage_root_when_chain_present(
        self, mock_run: MagicMock,
    ) -> None:
        expected_root = _persist_demo_chain(self.project_root)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-c2-a",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("lineage_root", gate)
        self.assertEqual(gate["lineage_root"], expected_root)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_run_production_gate_embeds_empty_string_when_no_chain(
        self, mock_run: MagicMock,
    ) -> None:
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-c2-b",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("lineage_root", gate)
        self.assertEqual(gate["lineage_root"], "")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_lineage_root_is_64hex_when_present(
        self, mock_run: MagicMock,
    ) -> None:
        _persist_demo_chain(self.project_root)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-c2-c",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        root = gate["lineage_root"]
        self.assertIsInstance(root, str)
        self.assertRegex(root, HEX64)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_gate_file_consumers_tolerate_lineage_root_key(
        self, mock_run: MagicMock,
    ) -> None:
        """The schema is open-set; existing consumers must keep working.

        We do not assert the exact key set anywhere — but if a future
        consumer pinned the set, this test would catch the regression by
        round-tripping the gate file through ``validate_gate_file`` (which
        tolerates additive keys).
        """
        from story_automator.core.gate_schema import validate_gate_file

        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-c2-d",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        # Should not raise — validate accepts additive top-level fields.
        validate_gate_file(gate)


class SystemGateLineageEmbedTests(_GateTempMixin, unittest.TestCase):
    def test_run_system_gate_embeds_lineage_root_symmetrically(self) -> None:
        expected_root = _persist_demo_chain(self.project_root)
        env_info = SystemEnvInfo(
            env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns",
            provisioned=True,
        )
        gate_file = _make_gate_file()
        with patch(
            "story_automator.core.system_gate.system_env"
        ) as mock_env, patch(
            "story_automator.core.system_gate.evaluate_gate"
        ) as mock_eval, patch(
            "story_automator.core.system_gate.run_gate_collectors",
            return_value=[],
        ), patch(
            "story_automator.core.system_gate._recover_from_crash_locked"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
            mock_env.return_value.__exit__ = MagicMock(return_value=False)
            mock_recover.return_value = ({"recovered": False}, [])
            mock_reuse.return_value = (None, "")
            mock_eval.return_value = gate_file
            result = run_system_gate(
                self.project_root,
                "sg1",
                epic_id="E1",
                commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertIn("lineage_root", result)
        self.assertEqual(result["lineage_root"], expected_root)

    def test_run_system_gate_reuse_path_embeds_lineage_root(self) -> None:
        """Round-2 bug fix #23 — reuse short-circuit must populate
        ``lineage_root`` symmetrically with the fresh path.

        Before the fix, ``run_system_gate``'s reuse short-circuit
        (``if existing is not None: return existing``) returned the cached
        gate_file unmodified, dropping the in-memory ``lineage_root`` field
        that the fresh path explicitly attaches at the end of the function.
        ``run_production_gate``'s reuse path re-derives both
        ``evidence_merkle_root`` and ``lineage_root`` precisely to preserve
        return-shape symmetry across cache hit / miss; this test pins the
        symmetric behavior for ``run_system_gate``.
        """
        expected_root = _persist_demo_chain(self.project_root)
        existing_gate = _make_gate_file()
        with patch(
            "story_automator.core.system_gate._recover_from_crash_locked"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_recover.return_value = ({"recovered": False}, [])
            mock_reuse.return_value = (existing_gate, "")
            result = run_system_gate(
                self.project_root,
                "sg1",
                epic_id="E1",
                commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        # Bug regression: reuse path was returning the cached dict without
        # the ``lineage_root`` field. A caller doing result["lineage_root"]
        # would KeyError on cache hit but succeed on cache miss.
        self.assertIn("lineage_root", result)
        self.assertEqual(result["lineage_root"], expected_root)

    def test_run_system_gate_reuse_path_lineage_root_empty_sentinel(
        self,
    ) -> None:
        """Reuse-path symmetry holds with no on-disk chain too.

        When no lineage chain exists on disk, the fresh path embeds the
        empty-string sentinel; the reuse path must do the same so callers
        see a consistent return shape.
        """
        existing_gate = _make_gate_file()
        with patch(
            "story_automator.core.system_gate._recover_from_crash_locked"
        ) as mock_recover, patch(
            "story_automator.core.system_gate.check_gate_reuse"
        ) as mock_reuse:
            mock_recover.return_value = ({"recovered": False}, [])
            mock_reuse.return_value = (existing_gate, "")
            result = run_system_gate(
                self.project_root,
                "sg1",
                epic_id="E1",
                commit_sha="abc",
                epic_metadata={},
                profile=_minimal_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
        self.assertIn("lineage_root", result)
        self.assertEqual(result["lineage_root"], "")


if __name__ == "__main__":
    unittest.main()
