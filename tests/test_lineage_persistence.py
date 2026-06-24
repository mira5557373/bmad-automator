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

    def test_distinct_keys_under_heavy_contention_yield_unique_contiguous_seqs(
        self,
    ) -> None:
        # Pin the documented contract from
        # ``persist_lineage_entry`` (lineage_ledger.py docstring):
        # "parallel persists on distinct (genre, slug) both end up in
        # the index". Two threads is too tame to surface a duplicate-seq
        # regression — derive seq from ``len(entries)`` outside the lock
        # discipline and the index would show colliding seqs under
        # barrier-synchronised contention. Assert the seq SET equals
        # ``{0..N-1}`` exactly, which is the only invariant that
        # actually disambiguates lock-protected reads from racy ones.
        n_threads = 24
        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def worker(idx: int) -> None:
            try:
                barrier.wait(timeout=30.0)
                persist_lineage_entry(
                    self.project_root,
                    _entry("brainstorm", f"s-{idx:03d}", body=f"body-{idx}"),
                )
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60.0)

        self.assertEqual(errors, [], f"unexpected persist errors: {errors!r}")
        index = json.loads(lineage_index_path(self.project_root).read_text())
        entries = index["entries"]
        self.assertEqual(
            len(entries), n_threads,
            f"expected {n_threads} distinct entries, got {len(entries)}",
        )
        seqs = [meta["seq"] for meta in entries.values()]
        # Uniqueness + contiguity: under a properly locked persist the
        # set of seqs equals exactly ``{0, 1, ..., n_threads-1}``. A
        # duplicate would shrink this set; a leaked seq would leave a
        # gap. Either failure mode silently misorders the chain at
        # ``load_lineage_chain`` time.
        self.assertEqual(
            sorted(seqs), list(range(n_threads)),
            f"seq values must be unique and contiguous 0..{n_threads - 1}: {seqs!r}",
        )

    def test_same_key_race_is_idempotent_and_chain_rebuilds_cleanly(self) -> None:
        # Pin the second half of the contract: "re-persist of the same
        # entry is idempotent". A buggy variant that advances ``seq``
        # on every persist would emit ``seq=n_threads-1`` at the end
        # of a same-key flood. The lock-protected reuse must keep it
        # at ``seq=0`` (the original insertion ordinal), and the chain
        # rebuild via :func:`load_lineage_chain` must succeed.
        n_threads = 12
        barrier = threading.Barrier(n_threads)
        # All threads persist the IDENTICAL entry so payload_hash,
        # parent_root, timestamp, genre, and slug all match — the
        # canonical-JSON form is byte-identical across threads.
        target_entry = _entry(
            "brainstorm", "dup-key", body="dup-body",
            ts="2026-06-24T00:00:00Z",
        )
        errors: list[BaseException] = []
        errors_lock = threading.Lock()
        returned_paths: list[Path] = []
        paths_lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait(timeout=30.0)
                out_path = persist_lineage_entry(
                    self.project_root, target_entry,
                )
                with paths_lock:
                    returned_paths.append(out_path)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60.0)

        self.assertEqual(errors, [], f"unexpected persist errors: {errors!r}")
        # (a) Every thread received the same disk path — the persist
        # is functionally pure for an already-indexed entry.
        self.assertEqual(len(returned_paths), n_threads)
        self.assertEqual(
            len(set(returned_paths)), 1,
            f"all threads must return identical path: {returned_paths!r}",
        )
        # (b) Exactly one composite key in the index — no duplicate
        # advertising of the same (genre, slug).
        index = json.loads(lineage_index_path(self.project_root).read_text())
        self.assertEqual(len(index["entries"]), 1)
        self.assertIn("brainstorm/dup-key", index["entries"])
        # (c) seq stays at 0 — the lock-protected reuse path read the
        # pre-existing meta and copied its ``seq``. A regression that
        # treats every persist as fresh would leak ``seq=n_threads-1``.
        meta = index["entries"]["brainstorm/dup-key"]
        self.assertEqual(
            meta["seq"], 0,
            f"idempotent re-persist must keep seq=0; got {meta['seq']!r}",
        )
        # (d) merkle_root is stable across re-persists (deterministic
        # function of the entry alone).
        self.assertEqual(meta["merkle_root"], compute_lineage_root([target_entry]))
        # (e) Chain rebuild via load_lineage_chain succeeds — the
        # idempotence contract holds end-to-end through the public
        # read API, not just at the index level.
        chain = load_lineage_chain(self.project_root)
        self.assertEqual(len(chain.entries), 1)
        self.assertEqual(chain.entries[0], target_entry)
        self.assertEqual(chain.merkle_root, meta["merkle_root"])


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

    def test_write_atomic_text_partial_failure_exercises_rollback(self) -> None:
        # Finer-granularity sibling of
        # ``test_index_write_failure_rolls_back_orphan_entry_file``. The
        # ``_write_index`` patch above intercepts at the helper boundary;
        # this test intercepts one level lower at ``write_atomic_text`` so
        # the FIRST call (entry write at line 484) goes through to the
        # real implementation and the SECOND call (inside ``_write_index``
        # at line 445) raises. This exercises the actual partial-write
        # window — entry file lands on disk, index write fails — and pins
        # the rollback path end-to-end without trusting that the
        # ``_write_index`` helper is the only path through the second
        # ``write_atomic_text`` call.
        entry = _entry("brainstorm", "s0", body="alpha")
        target_path = (
            self.project_root / "_bmad" / "lineage" / "brainstorm" / "s0.json"
        )
        from story_automator.core.innovation import lineage_ledger as _ll

        real_write = _ll.write_atomic_text
        call_log: list[Path] = []

        def _side_effect(path, text):  # type: ignore[no-untyped-def]
            call_log.append(Path(path))
            if len(call_log) == 1:
                # First call = entry write at line 484. Let it through.
                return real_write(path, text)
            # Second call = ``_write_index`` -> ``write_atomic_text`` for
            # ``index.json`` (line 445). Simulate ENOSPC/EACCES here.
            raise OSError("simulated index-write crash")

        with patch.object(_ll, "write_atomic_text", side_effect=_side_effect):
            with self.assertRaises(OSError):
                persist_lineage_entry(self.project_root, entry)
        # Confirm both calls were attempted — the test would be vacuous
        # if the patch raised on call #1.
        self.assertEqual(
            len(call_log), 2,
            f"expected two write_atomic_text calls (entry + index); got {call_log!r}",
        )
        # No orphan entry file lurking outside the index — the rollback
        # path at ``persist_lineage_entry`` lines 501-516 must have
        # best-effort deleted the just-written payload.
        self.assertFalse(
            target_path.exists(),
            "entry file must be rolled back when the index write_atomic_text fails",
        )
        # Index never advanced (genesis case) — no stale advertising.
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
