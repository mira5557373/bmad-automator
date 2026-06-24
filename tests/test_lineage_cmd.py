"""C2 query CLI — tests for ``commands.lineage_cmd`` subcommands.

The CLI is a read-only window onto the disk-persisted lineage ledger
under ``_bmad/lineage/``. All actions emit JSON to stdout with
alphabetically-sorted keys for byte-determinism; non-zero exit on
error.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.lineage_cmd import (
    entry_action,
    lineage_dispatch,
    orphans_action,
    show_action,
    stats_action,
    verify_action,
)
from story_automator.core.innovation.lineage_ledger import (
    compute_lineage_root,
    make_lineage_entry,
    persist_lineage_entry,
)


def _h(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry(genre, slug, parent_root="", body="x", ts="2026-06-22T00:00:00Z"):
    return make_lineage_entry(
        genre=genre,
        slug=slug,
        payload_hash=_h(body),
        parent_root=parent_root,
        timestamp_iso=ts,
    )


def _persist_chain(project_root: Path, n: int = 3) -> list:
    """Persist a valid n-entry chain (brainstorm -> braindump -> brief)."""
    genres = ["brainstorm", "braindump", "brief", "BRD", "PRD", "kernel", "story", "gate"]
    entries = []
    parent_root = ""
    for i in range(n):
        ent = _entry(genres[i], f"s{i}", parent_root=parent_root, body=f"b{i}")
        persist_lineage_entry(project_root, ent)
        entries.append(ent)
        parent_root = compute_lineage_root(entries)
    return entries


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, action, args):
        full_args = [f"--project-root={self.tmpdir}", *args]
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = action(full_args)
        return code, out.getvalue()


class ShowActionTests(_Base):
    def test_show_empty_returns_empty_chain_json(self) -> None:
        code, raw = self._run(show_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["merkle_root"], "")
        self.assertTrue(payload["ok"])

    def test_show_returns_persisted_entries_in_chain_order(self) -> None:
        entries = _persist_chain(self.project_root, n=3)
        code, raw = self._run(show_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        # Chain order = persistence/seq order, NOT alphabetical
        self.assertEqual(
            [e["genre"] for e in payload["entries"]],
            [e.genre for e in entries],
        )
        self.assertEqual(
            payload["merkle_root"], compute_lineage_root(entries)
        )


class EntryActionTests(_Base):
    def test_entry_existing_returns_json_payload(self) -> None:
        _persist_chain(self.project_root, n=2)
        code, raw = self._run(entry_action, ["brainstorm", "s0"])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertEqual(payload["genre"], "brainstorm")
        self.assertEqual(payload["slug"], "s0")
        self.assertEqual(payload["parent_root"], "")
        self.assertTrue(payload["ok"])

    def test_entry_missing_returns_nonzero_exit(self) -> None:
        code, raw = self._run(entry_action, ["brainstorm", "missing"])
        self.assertNotEqual(code, 0)
        payload = json.loads(raw)
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)

    def test_entry_missing_positional_returns_nonzero_exit(self) -> None:
        code, _ = self._run(entry_action, ["brainstorm"])
        self.assertNotEqual(code, 0)


class StatsActionTests(_Base):
    def test_stats_empty_lineage_returns_zero_counts(self) -> None:
        code, raw = self._run(stats_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertEqual(payload["chain_length"], 0)
        self.assertEqual(payload["merkle_root"], "")
        self.assertEqual(payload["genres"], {})
        self.assertEqual(payload["orphan_count"], 0)

    def test_stats_counts_per_genre(self) -> None:
        _persist_chain(self.project_root, n=3)
        code, raw = self._run(stats_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertEqual(payload["genres"]["brainstorm"], 1)
        self.assertEqual(payload["genres"]["braindump"], 1)
        self.assertEqual(payload["genres"]["brief"], 1)

    def test_stats_includes_root_and_length(self) -> None:
        entries = _persist_chain(self.project_root, n=2)
        code, raw = self._run(stats_action, [])
        payload = json.loads(raw)
        self.assertEqual(payload["chain_length"], 2)
        self.assertEqual(
            payload["merkle_root"], compute_lineage_root(entries)
        )


class VerifyActionTests(_Base):
    def test_verify_happy_path_returns_ok_true(self) -> None:
        entries = _persist_chain(self.project_root, n=3)
        code, raw = self._run(verify_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["merkle_root"], compute_lineage_root(entries)
        )

    def test_verify_empty_chain_returns_ok_true(self) -> None:
        code, raw = self._run(verify_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["merkle_root"], "")

    def test_verify_tampered_chain_returns_ok_false(self) -> None:
        _persist_chain(self.project_root, n=3)
        # Corrupt the second entry's disk file by rewriting payload_hash.
        target = self.project_root / "_bmad" / "lineage" / "braindump" / "s1.json"
        obj = json.loads(target.read_text())
        obj["payload_hash"] = "0" * 64
        target.write_text(json.dumps(obj, sort_keys=True, separators=(",", ":")))
        code, raw = self._run(verify_action, [])
        self.assertNotEqual(code, 0)
        payload = json.loads(raw)
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)


class OrphansActionTests(_Base):
    def test_orphans_returns_empty_on_intact_chain(self) -> None:
        _persist_chain(self.project_root, n=3)
        code, raw = self._run(orphans_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["orphans"], [])

    def test_orphans_empty_chain_returns_empty(self) -> None:
        code, raw = self._run(orphans_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["orphans"], [])

    def test_orphans_returns_entries_with_unknown_parent(self) -> None:
        # Persist a normal entry, then a second entry whose parent_root
        # references something not in the chain.
        e0 = _entry("brainstorm", "s0", parent_root="", body="b0")
        persist_lineage_entry(self.project_root, e0)
        bogus_parent = "f" * 64
        e1 = _entry("braindump", "s1", parent_root=bogus_parent, body="b1")
        persist_lineage_entry(self.project_root, e1)
        code, raw = self._run(orphans_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertEqual(len(payload["orphans"]), 1)
        self.assertEqual(payload["orphans"][0]["slug"], "s1")

    def test_orphans_non_alpha_persist_order_without_seq_no_false_positives(
        self,
    ) -> None:
        # Persist a non-alpha order: kernel first, brainstorm second. Then
        # strip the seq keys from the index to simulate a legacy/migrated
        # index where the lenient loader falls back to alpha order. The
        # chain is structurally intact (brainstorm's parent_root references
        # the kernel-only prefix root), so find_orphans must NOT report any
        # phantom orphans — it should walk the chain topologically rather
        # than rely on input ordering. See lineage_ledger.find_orphans.
        e_kernel = _entry("kernel", "s1", parent_root="", body="k1")
        persist_lineage_entry(self.project_root, e_kernel)
        parent_after_kernel = compute_lineage_root([e_kernel])
        e_brainstorm = _entry(
            "brainstorm", "s1", parent_root=parent_after_kernel, body="b1"
        )
        persist_lineage_entry(self.project_root, e_brainstorm)
        # Strip the seq keys from index.json — lenient loader will then
        # fall back to alpha tie-break (brainstorm < kernel), which is the
        # OPPOSITE of persist/chain order.
        idx_path = self.project_root / "_bmad" / "lineage" / "index.json"
        idx_data = json.loads(idx_path.read_text())
        for key in list(idx_data["entries"].keys()):
            idx_data["entries"][key].pop("seq", None)
        idx_path.write_text(
            json.dumps(idx_data, sort_keys=True, separators=(",", ":"))
        )
        code, raw = self._run(orphans_action, [])
        self.assertEqual(code, 0)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["orphan_count"], 0)
        self.assertEqual(payload["orphans"], [])


class DispatchTests(_Base):
    def test_dispatch_unknown_action_returns_nonzero(self) -> None:
        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                code = lineage_dispatch(
                    [f"--project-root={self.tmpdir}", "not-a-subcommand"]
                )
        self.assertNotEqual(code, 0)

    def test_dispatch_no_args_returns_nonzero(self) -> None:
        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                code = lineage_dispatch([])
        self.assertNotEqual(code, 0)

    def test_dispatch_missing_project_root_returns_nonzero(self) -> None:
        # Force PROJECT_ROOT-free env so get_project_root falls back to cwd
        # without a hint; passing the action a non-existent root surfaces
        # as a nonzero exit because no lineage data exists there. Since
        # --project-root is REQUIRED per spec, omitting it should be a
        # parse error (nonzero).
        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                code = lineage_dispatch(["show"])
        self.assertNotEqual(code, 0)

    def test_dispatch_routes_to_show(self) -> None:
        _persist_chain(self.project_root, n=2)
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = lineage_dispatch(
                ["show", f"--project-root={self.tmpdir}"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(len(payload["entries"]), 2)

    def test_dispatch_routes_to_verify(self) -> None:
        _persist_chain(self.project_root, n=2)
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = lineage_dispatch(
                ["verify", f"--project-root={self.tmpdir}"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])


class JsonShapeTests(_Base):
    """Every action emits valid JSON with alphabetically-sorted top keys."""

    def _assert_sorted_keys(self, raw: str) -> None:
        payload = json.loads(raw)
        keys = list(payload.keys())
        self.assertEqual(keys, sorted(keys), f"keys not sorted: {keys}")

    def test_show_emits_sorted_json(self) -> None:
        _persist_chain(self.project_root, n=2)
        _, raw = self._run(show_action, [])
        json.loads(raw)
        self._assert_sorted_keys(raw)

    def test_entry_emits_sorted_json(self) -> None:
        _persist_chain(self.project_root, n=1)
        _, raw = self._run(entry_action, ["brainstorm", "s0"])
        json.loads(raw)
        self._assert_sorted_keys(raw)

    def test_stats_emits_sorted_json(self) -> None:
        _persist_chain(self.project_root, n=1)
        _, raw = self._run(stats_action, [])
        json.loads(raw)
        self._assert_sorted_keys(raw)

    def test_verify_emits_sorted_json(self) -> None:
        _persist_chain(self.project_root, n=1)
        _, raw = self._run(verify_action, [])
        json.loads(raw)
        self._assert_sorted_keys(raw)

    def test_orphans_emits_sorted_json(self) -> None:
        _persist_chain(self.project_root, n=1)
        _, raw = self._run(orphans_action, [])
        json.loads(raw)
        self._assert_sorted_keys(raw)


class CliRegistrationTests(unittest.TestCase):
    def test_cli_registration_includes_lineage(self) -> None:
        # The orchestrator dispatch table is a local inside
        # cmd_orchestrator_helper; exercise it via the entry point.
        from story_automator.commands import orchestrator as orch
        import inspect
        source = inspect.getsource(orch.cmd_orchestrator_helper)
        self.assertIn('"lineage"', source)


if __name__ == "__main__":
    unittest.main()
