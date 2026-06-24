"""C2 follow-up — disk persistence for the cross-genre lineage ledger.

Mirrors M54 atomic-write + filelock discipline. Each entry persists to
``_bmad/lineage/<genre>/<slug>.json`` via ``write_atomic_text``, with an
``_bmad/lineage/index.json`` mapping ``(genre, slug)`` -> bookkeeping
metadata. Concurrent persists serialise through a single filelock at
``_bmad/lineage/.lineage.lock``.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.innovation.lineage_ledger import (
    LineageError,
    compute_lineage_root,
    get_lineage_lock,
    get_lineage_root_dir,
    lineage_index_path,
    load_lineage_chain,
    load_lineage_entry,
    load_lineage_root,
    make_lineage_entry,
    persist_lineage_entry,
)


def _h(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry(
    genre: str,
    slug: str,
    parent_root: str = "",
    body: str = "x",
    ts: str = "2026-06-22T00:00:00Z",
):
    return make_lineage_entry(
        genre=genre,
        slug=slug,
        payload_hash=_h(body),
        parent_root=parent_root,
        timestamp_iso=ts,
    )


class _TempProjectMixin:
    def setUp(self) -> None:  # type: ignore[override]
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self) -> None:  # type: ignore[override]
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class LineageRootDirTests(_TempProjectMixin, unittest.TestCase):
    def test_get_lineage_root_dir_returns_expected_path(self) -> None:
        path = get_lineage_root_dir(self.project_root)
        self.assertEqual(path, self.project_root / "_bmad" / "lineage")

    def test_get_lineage_root_dir_creates_directory_lazily(self) -> None:
        path = get_lineage_root_dir(self.project_root)
        self.assertTrue(path.is_dir())


class PersistRoundTripTests(_TempProjectMixin, unittest.TestCase):
    def test_persist_writes_to_correct_path(self) -> None:
        entry = _entry("brainstorm", "s0", body="alpha")
        out_path = persist_lineage_entry(self.project_root, entry)
        expected = (
            self.project_root / "_bmad" / "lineage" / "brainstorm" / "s0.json"
        )
        self.assertEqual(out_path, expected)
        self.assertTrue(out_path.is_file())

    def test_persist_updates_index(self) -> None:
        entry = _entry("brainstorm", "s0", body="alpha")
        persist_lineage_entry(self.project_root, entry)
        index = json.loads(lineage_index_path(self.project_root).read_text())
        self.assertIn("entries", index)
        # Index uses "<genre>/<slug>" as the composite key for stable order.
        self.assertIn("brainstorm/s0", index["entries"])
        meta = index["entries"]["brainstorm/s0"]
        self.assertIn("path", meta)
        self.assertIn("merkle_root", meta)
        self.assertIn("timestamp_iso", meta)

    def test_load_round_trip_returns_equal_entry(self) -> None:
        entry = _entry("brief", "s2", body="brief-body")
        persist_lineage_entry(self.project_root, entry)
        loaded = load_lineage_entry(self.project_root, "brief", "s2")
        self.assertEqual(entry, loaded)

    def test_load_missing_raises_lineage_error(self) -> None:
        with self.assertRaises(LineageError):
            load_lineage_entry(self.project_root, "brief", "missing-slug")

    def test_persist_idempotent_on_same_entry(self) -> None:
        entry = _entry("brainstorm", "s0", body="alpha")
        out_path_a = persist_lineage_entry(self.project_root, entry)
        out_path_b = persist_lineage_entry(self.project_root, entry)
        self.assertEqual(out_path_a, out_path_b)
        # Index entry count stays at 1 — same composite key, no duplicates.
        index = json.loads(lineage_index_path(self.project_root).read_text())
        self.assertEqual(len(index["entries"]), 1)


class IndexAnnotationContractTests(_TempProjectMixin, unittest.TestCase):
    """Pin the ``_read_index`` / ``_write_index`` / ``_index_sort_key``
    annotations against the actual on-disk shape. ``seq`` is written as a
    Python ``int`` and round-trips through JSON as ``int`` — the inner
    value variant must therefore include ``int``, not just ``str``.

    Regression for a type-annotation drift that understated the variant:
    static checkers honouring the annotation would have treated
    ``meta["seq"]`` as ``str`` and could have inserted ``.lower()`` or
    similar string-only operations during a future refactor.
    """

    def test_seq_field_round_trips_as_int(self) -> None:
        # Insertion-order proof: persist a single entry; seq must be int(0).
        from story_automator.core.innovation.lineage_ledger import _read_index

        entry = _entry("brainstorm", "s0", body="alpha")
        persist_lineage_entry(self.project_root, entry)
        meta = _read_index(self.project_root)
        seq_value = meta["brainstorm/s0"]["seq"]
        self.assertIsInstance(
            seq_value, int,
            "seq must round-trip as int — Path/index ordering relies on it",
        )
        # Not isinstance bool — bool is a subclass of int but the writer
        # uses len(entries) which is a true non-bool int.
        self.assertNotIsInstance(seq_value, bool)
        self.assertEqual(seq_value, 0)

    def test_read_index_annotation_includes_int_variant(self) -> None:
        # Inspect the declared annotation directly; this is the
        # documentation-contract check that the inner value variant
        # acknowledges ``seq``'s int type. Uses raw __annotations__ so the
        # check works on Python versions without typing.get_type_hints
        # resolution gymnastics.
        from story_automator.core.innovation.lineage_ledger import (
            _index_sort_key,
            _read_index,
            _write_index,
        )

        # ``_read_index`` return type: must mention ``int`` in the variant.
        read_ret = _read_index.__annotations__["return"]
        # Under ``from __future__ import annotations`` the annotation is a
        # string literal at runtime; the contract check is substring-based.
        self.assertIn("int", str(read_ret),
                      f"_read_index return annotation must include int: {read_ret!r}")

        # ``_write_index`` ``entries`` param: same contract.
        write_param = _write_index.__annotations__["entries"]
        self.assertIn("int", str(write_param),
                      f"_write_index entries annotation must include int: {write_param!r}")

        # ``_index_sort_key`` ``item`` param: same contract.
        sort_param = _index_sort_key.__annotations__["item"]
        self.assertIn("int", str(sort_param),
                      f"_index_sort_key item annotation must include int: {sort_param!r}")


class IndexOrderingTests(_TempProjectMixin, unittest.TestCase):
    def test_index_alpha_sorted_for_determinism(self) -> None:
        # Persist in non-alpha order; on-disk index must serialise sorted.
        for genre, slug, body in [
            ("kernel", "kern-zz", "z"),
            ("brainstorm", "br-aa", "a"),
            ("PRD", "prd-mm", "m"),
        ]:
            persist_lineage_entry(
                self.project_root, _entry(genre, slug, body=body),
            )
        raw = lineage_index_path(self.project_root).read_text()
        index = json.loads(raw)
        keys = list(index["entries"].keys())
        self.assertEqual(keys, sorted(keys))


class ConcurrentPersistTests(_TempProjectMixin, unittest.TestCase):
    def test_persist_concurrent_serializes_via_lock(self) -> None:
        # Two threads append distinct (genre, slug) pairs; both must end
        # up in the index, neither corrupting the other's write.
        errors: list[BaseException] = []

        def worker(genre: str, slug: str, body: str) -> None:
            try:
                persist_lineage_entry(
                    self.project_root, _entry(genre, slug, body=body),
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(
            target=worker, args=("brainstorm", "s-a", "alpha"),
        )
        t2 = threading.Thread(
            target=worker, args=("brief", "s-b", "beta"),
        )
        t1.start()
        t2.start()
        t1.join(timeout=30.0)
        t2.join(timeout=30.0)

        self.assertEqual(errors, [], f"unexpected persist errors: {errors!r}")
        index = json.loads(lineage_index_path(self.project_root).read_text())
        self.assertIn("brainstorm/s-a", index["entries"])
        self.assertIn("brief/s-b", index["entries"])


class AtomicWriteFailureTests(_TempProjectMixin, unittest.TestCase):
    def test_atomic_write_no_partial_file_on_crash(self) -> None:
        entry = _entry("brainstorm", "s0", body="alpha")
        # Simulate os.replace raising mid-persist; the entry json should
        # never appear at its final path, AND the index must not advertise
        # an entry whose payload is missing.
        target_dir = (
            self.project_root / "_bmad" / "lineage" / "brainstorm"
        )
        with patch(
            "story_automator.core.innovation.lineage_ledger.write_atomic_text",
            side_effect=OSError("simulated crash"),
        ):
            with self.assertRaises(OSError):
                persist_lineage_entry(self.project_root, entry)
        # No persisted entry file.
        self.assertFalse(
            (target_dir / "s0.json").exists(),
            "entry file must not exist after a crashed atomic write",
        )
        # No stale index advertising a missing payload.
        idx_path = lineage_index_path(self.project_root)
        if idx_path.exists():
            data = json.loads(idx_path.read_text())
            self.assertNotIn("brainstorm/s0", data.get("entries", {}))

    def test_index_write_failure_rolls_back_orphan_entry_file(self) -> None:
        # Symmetric crash-safety check. ``write_atomic_text(target_path)``
        # succeeds, then ``_write_index`` raises (e.g. ENOSPC/EACCES on the
        # index parent). Before the fix the entry file was left orphaned on
        # disk while ``load_lineage_root`` returned ``""`` — silent
        # provenance loss. The fix best-effort deletes the just-written
        # entry file so the on-disk shape matches the untouched index.
        entry = _entry("brainstorm", "s0", body="alpha")
        target_path = (
            self.project_root / "_bmad" / "lineage" / "brainstorm" / "s0.json"
        )
        with patch(
            "story_automator.core.innovation.lineage_ledger._write_index",
            side_effect=OSError("simulated index write failure"),
        ):
            with self.assertRaises(OSError):
                persist_lineage_entry(self.project_root, entry)
        # No orphan entry file lurking outside the index.
        self.assertFalse(
            target_path.exists(),
            "entry file must be rolled back when index write fails",
        )
        # Index never advanced (genesis case) — no stale advertising either.
        self.assertEqual(load_lineage_root(self.project_root), "")

    def test_index_write_failure_preserves_already_indexed_entry(self) -> None:
        # Idempotent-re-persist guard: when the entry was already in the
        # index, the file pre-existed and the index still advertises it.
        # An ``_write_index`` failure on the re-persist must NOT delete the
        # already-advertised payload, or the read APIs would dangle the
        # index's reference.
        entry = _entry("brainstorm", "s0", body="alpha")
        target_path = persist_lineage_entry(self.project_root, entry)
        self.assertTrue(target_path.exists())
        baseline_root = load_lineage_root(self.project_root)

        with patch(
            "story_automator.core.innovation.lineage_ledger._write_index",
            side_effect=OSError("simulated index write failure"),
        ):
            with self.assertRaises(OSError):
                persist_lineage_entry(self.project_root, entry)
        # Pre-existing payload retained; index still references it.
        self.assertTrue(
            target_path.exists(),
            "already-indexed entry file must not be deleted on re-persist failure",
        )
        self.assertEqual(load_lineage_root(self.project_root), baseline_root)


class CorruptIndexTests(_TempProjectMixin, unittest.TestCase):
    def test_corrupt_index_raises_lineage_error(self) -> None:
        # Pre-create a corrupt index file. load_lineage_root /
        # load_lineage_chain must raise rather than silently rebuild.
        _ = get_lineage_root_dir(self.project_root)  # creates dir
        idx_path = lineage_index_path(self.project_root)
        idx_path.write_text("{not-json:")
        with self.assertRaises(LineageError):
            load_lineage_chain(self.project_root)


class LineageLockTests(_TempProjectMixin, unittest.TestCase):
    def test_get_lineage_lock_returns_filelock(self) -> None:
        lock = get_lineage_lock(self.project_root)
        # filelock.FileLock duck-typed — we only need acquire/release.
        self.assertTrue(hasattr(lock, "acquire"))
        self.assertTrue(hasattr(lock, "release"))


class LoadRootFromDiskTests(_TempProjectMixin, unittest.TestCase):
    def test_load_root_empty_when_no_entries(self) -> None:
        self.assertEqual(load_lineage_root(self.project_root), "")

    def test_load_root_matches_compute_for_full_chain(self) -> None:
        # Persist a 3-link chain in canonical order; the disk-derived
        # root must equal compute_lineage_root over the in-memory list.
        entries = []
        parent = ""
        for idx, (genre, slug, body) in enumerate(
            [("brainstorm", "s0", "a"), ("braindump", "s1", "b"),
             ("brief", "s2", "c")],
        ):
            ent = _entry(genre, slug, parent_root=parent, body=body)
            entries.append(ent)
            parent = compute_lineage_root(entries)
            persist_lineage_entry(self.project_root, ent)
        disk_root = load_lineage_root(self.project_root)
        memory_root = compute_lineage_root(entries)
        self.assertEqual(disk_root, memory_root)
        self.assertEqual(len(disk_root), 64)


if __name__ == "__main__":
    unittest.main()
