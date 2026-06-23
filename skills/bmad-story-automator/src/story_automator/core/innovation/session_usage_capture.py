"""Auto session-usage capture — read a CLI transcript, return UsageMetrics.

Closes the C3 cost-tracking loop end-to-end. Callers of
:func:`story_automator.core.gate_orchestrator.run_production_gate` can
pass ``session_usage`` to populate the additive ``cost_total_usd`` field
on the resulting gate file, but until now they had to hand-build a
:class:`UsageMetrics` themselves. This module is the missing adapter:
read a CLI session's stdout/transcript blob from disk, dispatch the
correct dialect parser via :data:`story_automator.core.usage_parsers.
KNOWN_PARSERS`, and return both the parsed :class:`UsageMetrics` and
the provenance (source path, cli_id, parser_id, bytes read) so the
gate file / audit trail can record where the cost numbers came from.

Two entrypoints:

* :func:`capture_session_usage` — explicit ``cli_id`` + path. Used
  when the caller already knows where the transcript lives (e.g. a
  test harness or a one-shot CLI invocation).
* :func:`capture_session_usage_for_tmux` — convenience wrapper for
  the production runtime: given a tmux session name, locate the
  session's output file via :func:`story_automator.core.tmux_runtime.
  session_paths` and capture from there. ``cli_id`` defaults to
  ``"claude-code"`` because that is the production dialect.

Fail-soft contract — mirrors the cost-evidence emission contract:

* Missing file => :class:`SessionUsageCaptureError` (loud — the
  caller asked us to read a specific path; silently returning zero
  would hide a misconfiguration).
* Unparseable content => return zero-valued :class:`UsageMetrics`
  with ``parser_id="none"`` and a logged warning. The session
  legitimately may have emitted nothing the parser recognizes
  (toy CLI, custom stop hook); we never want to abort a gate over
  it. Note that this is distinct from
  :data:`story_automator.core.usage_parsers.KNOWN_PARSERS["none"]`
  — the ``"none"`` parser dialect is a deliberate operator choice,
  whereas this fallback path is a runtime-degrade signal.
* Unknown ``cli_id`` => :class:`SessionUsageCaptureError` (re-raised
  from :class:`story_automator.core.usage_parsers.ParseError` so
  callers can catch a single class).

stdlib-only (mandatory): ``dataclasses`` / ``logging`` / ``pathlib`` /
no external transports. The tmux convenience entrypoint imports
``tmux_runtime`` lazily so this module stays importable in contexts
where the tmux adapter is not available (CI without tmux installed,
docs-only builds, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..usage_parsers import KNOWN_PARSERS, ParseError, UsageMetrics, get_parser


__all__ = [
    "SessionUsageCapture",
    "SessionUsageCaptureError",
    "capture_session_usage",
    "capture_session_usage_for_tmux",
]


logger = logging.getLogger(__name__)


# Parser id sentinel used when capture succeeded structurally (file
# existed, was readable) but the content yielded no usable usage —
# either because the transcript was empty, malformed, or a future
# dialect we don't yet recognize. Kept distinct from the "none" parser
# dialect (an operator-configured opt-out) so audit consumers can
# distinguish "operator chose no parsing" from "parser tried and
# returned zeros". See module docstring.
_FALLBACK_PARSER_ID: str = "none"


class SessionUsageCaptureError(ValueError):
    """Raised when capture cannot proceed (missing file or unknown CLI).

    Inherits :class:`ValueError` so callers that already catch the
    parser-level :class:`story_automator.core.usage_parsers.ParseError`
    (also a :class:`ValueError`) can use a single ``except`` clause.
    """


@dataclass(frozen=True)
class SessionUsageCapture:
    """Capture result — parsed metrics plus provenance.

    Frozen so the gate orchestrator / audit trail can stash the
    instance without worrying about downstream mutation. ``source_path``
    is the path that was actually read (post-resolution, in case the
    caller passed a relative path).
    """

    usage: UsageMetrics
    source_path: Path
    cli_id: str
    parser_id: str
    bytes_read: int


def _validate_cli_id(cli_id: str) -> str:
    """Validate ``cli_id`` against :data:`KNOWN_PARSERS` and return the parser_id.

    Raised :class:`SessionUsageCaptureError` wraps the underlying
    :class:`ParseError` so callers can catch one class.
    """

    try:
        # Touch the dispatch path to guarantee parity with usage_parsers'
        # ParseError surface — we want SessionUsageCaptureError to be
        # raised on every unknown cli_id, including ones that might
        # appear in KNOWN_PARSERS keys without a dispatch entry (defense
        # in depth against a future split between map + dispatch).
        get_parser(cli_id)
    except ParseError as exc:
        raise SessionUsageCaptureError(str(exc)) from exc

    parser_id = KNOWN_PARSERS.get(cli_id)
    if parser_id is None:
        # Belt-and-suspenders — get_parser would have raised above,
        # but a future refactor that decouples the dispatch and
        # KNOWN_PARSERS maps should still fail loudly here.
        known = ", ".join(sorted(KNOWN_PARSERS))
        raise SessionUsageCaptureError(
            f"unknown cli_id {cli_id!r}; known cli_ids: {known}"
        )
    return parser_id


def _read_session_text(path: Path) -> tuple[str, int]:
    """Read ``path`` as UTF-8 text with replacement on decode errors.

    Returns ``(text, bytes_read)`` where ``bytes_read`` is the raw
    on-disk size — useful for telemetry / sanity checks. Decode errors
    are replaced rather than raised because CLI transcripts often
    contain ANSI escapes and partial UTF-8 sequences when the session
    crashed mid-write; we still want best-effort parsing.
    """

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return text, len(raw)


def capture_session_usage(
    cli_id: str,
    session_output_path: "str | Path",
) -> SessionUsageCapture:
    """Read a CLI session transcript from disk and return parsed usage.

    Validates ``cli_id`` against :data:`KNOWN_PARSERS`, reads the file
    at ``session_output_path`` (UTF-8 with replacement), dispatches the
    matching parser, and returns a :class:`SessionUsageCapture` with the
    resulting :class:`UsageMetrics` plus provenance.

    Raises :class:`SessionUsageCaptureError` if ``cli_id`` is unknown
    (parser-level :class:`ParseError` re-raised) or if the file does
    not exist. Unparseable content is *not* an error: the parser is
    expected to be tolerant (see usage_parsers package docstring), so
    a transcript that yields no usage blocks reads as zero-valued
    :class:`UsageMetrics`. When that happens the returned
    ``parser_id`` is set to ``"none"`` (the runtime-degrade sentinel)
    so callers can tell "parser tried and got nothing" apart from
    "parser succeeded with real numbers".
    """

    parser_id = _validate_cli_id(cli_id)

    path = Path(session_output_path).resolve()
    if not path.exists():
        raise SessionUsageCaptureError(
            f"session output path does not exist: {path}"
        )
    if not path.is_file():
        raise SessionUsageCaptureError(
            f"session output path is not a regular file: {path}"
        )

    try:
        text, bytes_read = _read_session_text(path)
    except OSError as exc:
        raise SessionUsageCaptureError(
            f"failed to read session output at {path}: {exc}"
        ) from exc

    parser = get_parser(cli_id)
    usage = parser(text)

    # If the parser returned all zeros, downgrade parser_id to the
    # fallback sentinel so audit consumers can tell the difference
    # between "parser found real numbers" and "parser found nothing".
    effective_parser_id = parser_id
    if usage == UsageMetrics():
        if bytes_read > 0:
            logger.warning(
                "session_usage_capture: parser %r returned zero usage for "
                "non-empty transcript at %s (%d bytes); downgrading "
                "parser_id to %r",
                parser_id,
                path,
                bytes_read,
                _FALLBACK_PARSER_ID,
            )
        effective_parser_id = _FALLBACK_PARSER_ID

    return SessionUsageCapture(
        usage=usage,
        source_path=path,
        cli_id=cli_id,
        parser_id=effective_parser_id,
        bytes_read=bytes_read,
    )


def capture_session_usage_for_tmux(
    tmux_session_name: str,
    cli_id: str = "claude-code",
    project_root: "str | Path | None" = None,
) -> SessionUsageCapture:
    """Convenience wrapper: resolve the tmux session output path, then capture.

    Looks up the session output path via :func:`story_automator.core.
    tmux_runtime.session_paths` (the existing public accessor — we do
    not duplicate the path-derivation logic). ``cli_id`` defaults to
    ``"claude-code"`` because that is the production dialect for the
    bmad-story-automator runtime; pass an explicit ``cli_id`` to capture
    a session that was launched against a different CLI.

    The import of :mod:`story_automator.core.tmux_runtime` is lazy so
    this module remains importable in environments where tmux is not
    present (CI without tmux installed, docs-only builds).
    """

    # Validate cli_id BEFORE touching tmux_runtime so a typo doesn't
    # waste a session_paths() call.
    _validate_cli_id(cli_id)

    # Lazy import: tmux_runtime pulls in subprocess / shutil / etc.
    # and we don't want this module to require tmux availability.
    from .. import tmux_runtime  # noqa: PLC0415 — lazy by design

    project_root_str = (
        None if project_root is None else str(project_root)
    )
    paths = tmux_runtime.session_paths(
        tmux_session_name, project_root=project_root_str,
    )
    return capture_session_usage(cli_id, paths.output)
