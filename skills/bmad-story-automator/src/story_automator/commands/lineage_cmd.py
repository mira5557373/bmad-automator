"""C2 query CLI — read-only window onto the disk-persisted lineage ledger.

Mirrors :mod:`commands.gate_cmd` discipline:

* one ``lineage_dispatch(args)`` entry point with argparse subparsers
* every subcommand requires ``--project-root``
* output is canonical JSON to stdout (alphabetically-sorted keys for
  byte-determinism, the same shape the gate file embeds)
* exit code 0 on success, non-zero on error

Subcommands:

    lineage show       -- full chain in canonical order
    lineage entry      -- single ``<genre> <slug>`` entry as JSON
    lineage stats      -- counts per genre, root, length, orphans
    lineage verify     -- re-run :func:`verify_lineage` against disk
    lineage orphans    -- entries whose ``parent_root`` is unknown

All actions are READ-ONLY. The CLI never writes, mutates, or deletes
under ``_bmad/lineage/`` — it is purely an inspection surface for the
C2 follow-up persistence layer (see :mod:`core.innovation.lineage_ledger`).
"""
from __future__ import annotations

import argparse
import json as _json
import sys
from collections import Counter
from typing import Any, Callable

from story_automator.core.innovation.lineage_ledger import (
    LineageEntry,
    LineageError,
    build_lineage_chain,
    compute_lineage_root,
    find_orphans,
    load_lineage_chain,
    load_lineage_entry,
    verify_lineage,
)
from story_automator.core.innovation.lineage_ledger import (
    _read_index as _read_lineage_index,  # read-only consumption
)

# ---------------------------------------------------------------------------
# Output helpers — sort_keys for byte-deterministic JSON, compact form.
# ---------------------------------------------------------------------------


def _emit(payload: dict[str, Any]) -> None:
    """Print ``payload`` as canonical JSON (sorted keys, no whitespace)."""
    print(_json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _entry_to_dict(entry: LineageEntry) -> dict[str, str]:
    """Render a :class:`LineageEntry` as a JSON-friendly dict.

    Duplicated from :mod:`core.innovation.lineage_ledger` (where it is
    a private helper) so this module has no dependency on private API.
    """
    return {
        "genre": entry.genre,
        "slug": entry.slug,
        "payload_hash": entry.payload_hash,
        "parent_root": entry.parent_root,
        "timestamp_iso": entry.timestamp_iso,
    }


def _load_entries(project_root: str) -> list[LineageEntry]:
    """Return the on-disk entry list in chain (seq) order, or []."""
    try:
        chain = load_lineage_chain(project_root)
        return list(chain.entries)
    except LineageError:
        # Empty index is the only LineageError path that should silently
        # collapse to []; corrupt-index callers want to see the error.
        if not _read_lineage_index(project_root):
            return []
        raise


def _load_entries_lenient(project_root: str) -> list[LineageEntry]:
    """Load entries in seq order WITHOUT validating chain integrity.

    Distinct from :func:`_load_entries`, which goes through
    :func:`build_lineage_chain` and rejects broken parent_root chains.
    Orphan detection by definition needs to inspect a chain with bad
    pointers, so we walk the index directly here. Per-entry corruption
    still raises (a corrupt JSON file is a different failure mode than
    a dangling parent_root pointer).
    """
    entries_meta = _read_lineage_index(project_root)
    if not entries_meta:
        return []

    def _seq_key(item: tuple[str, dict[str, str]]) -> tuple[int, str]:
        composite_key, meta = item
        try:
            seq_value = int(meta.get("seq", -1))
        except (TypeError, ValueError):
            seq_value = -1
        return (seq_value, composite_key)

    out: list[LineageEntry] = []
    for composite_key, _meta in sorted(entries_meta.items(), key=_seq_key):
        genre, _, slug = composite_key.partition("/")
        out.append(load_lineage_entry(project_root, genre, slug))
    return out


# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse tree for ``lineage_dispatch``.

    Each subparser declares ``--project-root`` as REQUIRED to mirror the
    contract spec (no implicit env fallback at the CLI surface, even
    though :func:`core.utils.get_project_root` would happily provide one).
    """
    parser = argparse.ArgumentParser(
        prog="orchestrator-helper lineage",
        description="Query the cross-genre lineage ledger (read-only).",
    )
    sub = parser.add_subparsers(dest="subcommand")

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--project-root",
            dest="project_root",
            required=True,
            help="project root containing _bmad/lineage/",
        )

    p_show = sub.add_parser("show", help="print the full chain as JSON")
    _add_common(p_show)

    p_entry = sub.add_parser("entry", help="print one entry as JSON")
    _add_common(p_entry)
    p_entry.add_argument("genre", help="lineage genre (e.g. brainstorm)")
    p_entry.add_argument("slug", help="artifact slug within the genre")

    p_stats = sub.add_parser("stats", help="counts per genre + root + length")
    _add_common(p_stats)

    p_verify = sub.add_parser("verify", help="re-run verify_lineage against disk")
    _add_common(p_verify)

    p_orphans = sub.add_parser(
        "orphans", help="list entries with an unknown parent_root"
    )
    _add_common(p_orphans)

    return parser


def _parse_one(action_name: str, args: list[str]) -> argparse.Namespace | None:
    """Parse ``args`` as the named subcommand; return None on parser error.

    argparse normally calls ``sys.exit`` on failure; we trap that so the
    action layer can return a clean non-zero exit code instead of
    letting SystemExit propagate to a test harness.
    """
    parser = _build_parser()
    # Prepend the subcommand so we can reuse the shared parser tree even
    # when an action helper is invoked directly with only its own args.
    try:
        return parser.parse_args([action_name, *args])
    except SystemExit:
        return None


# ---------------------------------------------------------------------------
# Action handlers.
# ---------------------------------------------------------------------------


def show_action(args: list[str]) -> int:
    ns = _parse_one("show", args)
    if ns is None or not ns.project_root:
        _emit({"error": "missing --project-root", "ok": False})
        return 2
    try:
        entries = _load_entries(ns.project_root)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    root = compute_lineage_root(entries) if entries else ""
    _emit({
        "entries": [_entry_to_dict(e) for e in entries],
        "merkle_root": root,
        "ok": True,
    })
    return 0


def entry_action(args: list[str]) -> int:
    ns = _parse_one("entry", args)
    if ns is None or not ns.project_root:
        _emit({"error": "missing --project-root or positional args", "ok": False})
        return 2
    try:
        entry = load_lineage_entry(ns.project_root, ns.genre, ns.slug)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    payload = _entry_to_dict(entry)
    payload["ok"] = True
    _emit(payload)
    return 0


def stats_action(args: list[str]) -> int:
    ns = _parse_one("stats", args)
    if ns is None or not ns.project_root:
        _emit({"error": "missing --project-root", "ok": False})
        return 2
    # Use the lenient loader so ``stats`` remains informative even when
    # the chain has dangling parent_root references; ``merkle_root`` is
    # then a best-effort root over what's on disk in seq order.
    try:
        entries = _load_entries_lenient(ns.project_root)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    counts = Counter(e.genre for e in entries)
    # Sorted dict so JSON output is genre-alpha within ``genres``.
    genre_counts = {k: counts[k] for k in sorted(counts.keys())}
    root = compute_lineage_root(entries) if entries else ""
    orphan_count = len(find_orphans(entries)) if entries else 0
    _emit({
        "chain_length": len(entries),
        "genres": genre_counts,
        "merkle_root": root,
        "ok": True,
        "orphan_count": orphan_count,
    })
    return 0


def verify_action(args: list[str]) -> int:
    ns = _parse_one("verify", args)
    if ns is None or not ns.project_root:
        _emit({"error": "missing --project-root", "ok": False})
        return 2
    try:
        entries = _load_entries(ns.project_root)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    if not entries:
        # Empty chain = trivially intact (mirrors load_lineage_root sentinel).
        _emit({"merkle_root": "", "ok": True})
        return 0
    try:
        chain = build_lineage_chain(entries)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    if not verify_lineage(chain):
        _emit({
            "error": "lineage verification failed (tampered chain)",
            "ok": False,
        })
        return 1
    _emit({"merkle_root": chain.merkle_root, "ok": True})
    return 0


def orphans_action(args: list[str]) -> int:
    ns = _parse_one("orphans", args)
    if ns is None or not ns.project_root:
        _emit({"error": "missing --project-root", "ok": False})
        return 2
    # Orphan detection MUST run against a possibly-broken chain — that's
    # the whole point. Use the lenient loader so a dangling parent_root
    # pointer doesn't short-circuit the inspection.
    try:
        entries = _load_entries_lenient(ns.project_root)
    except LineageError as exc:
        _emit({"error": str(exc), "ok": False})
        return 1
    orphan_entries = find_orphans(entries) if entries else []
    _emit({
        "ok": True,
        "orphan_count": len(orphan_entries),
        "orphans": [_entry_to_dict(e) for e in orphan_entries],
    })
    return 0


# ---------------------------------------------------------------------------
# Dispatcher.
# ---------------------------------------------------------------------------


_DISPATCH: dict[str, Callable[[list[str]], int]] = {
    "show": show_action,
    "entry": entry_action,
    "stats": stats_action,
    "verify": verify_action,
    "orphans": orphans_action,
}


def _usage() -> None:
    print(
        "Usage: orchestrator-helper lineage "
        "<show|entry|stats|verify|orphans> --project-root=<path> [args]",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("  lineage show       --project-root=<path>", file=sys.stderr)
    print("  lineage entry      --project-root=<path> <genre> <slug>", file=sys.stderr)
    print("  lineage stats      --project-root=<path>", file=sys.stderr)
    print("  lineage verify     --project-root=<path>", file=sys.stderr)
    print("  lineage orphans    --project-root=<path>", file=sys.stderr)


def lineage_dispatch(args: list[str]) -> int:
    """Route a lineage subcommand. Returns the action's exit code.

    The caller passes the args *after* the top-level ``lineage`` token
    (mirroring :func:`commands.gate_cmd.gate_dispatch`). ``--project-root``
    may appear before or after the subcommand thanks to argparse, but
    the subcommand itself MUST be the first positional argument we see.
    """
    if not args:
        _usage()
        return 1

    # The subcommand may not be ``args[0]`` if the caller put a global
    # flag first; scan for the first non-flag token.
    subcommand: str | None = None
    remaining: list[str] = []
    for idx, tok in enumerate(args):
        if not tok.startswith("-") and subcommand is None:
            subcommand = tok
            remaining = args[:idx] + args[idx + 1 :]
            break
    if subcommand is None:
        _usage()
        return 1

    handler = _DISPATCH.get(subcommand)
    if handler is None:
        _usage()
        return 1
    return handler(remaining)
