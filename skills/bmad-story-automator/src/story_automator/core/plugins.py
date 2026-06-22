"""Declarative-only plugin registry — Path B compat layer (N6.4).

The HookBus shim shipped in N6.2 (``core/bauto_bridge/hookbus_shim.py``)
covers *in-process* Python callbacks. This module is its declarative
sibling: it loads TOML manifests describing subprocess hooks, validates
them against an explicit operator-controlled allowlist, and surfaces the
result to the dispatcher.

Why a separate registry instead of importing bmad-auto's plugin engine?

* Trust boundary. Path B (see
  ``docs/spec/2026-06-22-engine-adoption-decision.md``) keeps the
  generation-child sandbox airtight by refusing to load arbitrary Python
  off a plugin disk. A manifest may *describe* a subprocess to invoke;
  it may not name a Python module the registry will then ``importlib``.
* Auditability. Every loaded plugin is a small TOML file with five
  recognized keys. The set is closed; any extra key raises
  ``PluginTrustError`` so a future contributor cannot quietly widen the
  surface.
* Determinism. Plugins are loaded in sorted-by-name order so the
  dispatch sequence is reproducible across machines regardless of
  filesystem readdir ordering.

Manifest TOML shape (loaded from ``_bmad/plugins/<name>.toml``)::

    name = "example"
    version = "1.0.0"
    timeout_s = 30.0       # optional, default 30.0
    fail_closed = false    # optional, default False

    [hooks]
    post_gate = "my-plugin --gate-id $BMAD_GATE_ID"
    pre_review = "my-plugin --story $BMAD_STORY_ID"

Rejection rules (each raises ``PluginTrustError``):

1. The manifest's ``name`` is not in the allowlist passed to the
   ``PluginRegistry`` constructor.
2. The manifest contains a Python-import key — ``python_module`` or
   ``py_module``. These names are reserved precisely so engines that
   support Python entrypoints (including bmad-auto upstream) cannot be
   silently re-enabled here.
3. The manifest contains a key not in ``PLUGIN_MANIFEST_KEYS``.
4. A ``[hooks]`` value is not a string. Subprocess command strings only;
   no callables, lists, or tables.
5. A required key (``name`` or ``version``) is missing.
6. The TOML is malformed.

``$BMAD_*`` placeholder strings in hook commands are *preserved
verbatim*. The registry does not perform any string interpolation — that
is the dispatcher's job, after it has resolved the runtime context.

Public surface (the minimum the dispatcher in a later milestone needs):

* ``PluginSpec`` — frozen dataclass returned by ``load_all``.
* ``PluginTrustError`` — every rejection raises this; callers can catch
  exactly one type to fail-closed.
* ``PluginRegistry`` — discovers, validates, and indexes manifests.
* ``PLUGIN_MANIFEST_KEYS`` — the closed key allowlist.

Design constraints (per project hard guardrails):

* stdlib-only — uses ``tomllib`` (Python 3.11+).
* No timestamps, PIDs, or run-IDs are baked into any returned value, so
  ``PluginSpec`` is safe to embed in audit payloads later.
* No new imports beyond stdlib + ``filelock`` + ``psutil``. This module
  takes none.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The closed set of recognized top-level keys in a plugin manifest. Any
# other key — including the two Python-import names called out below —
# is rejected. Kept as a module-level constant so callers can introspect
# what is legal without parsing this docstring.
PLUGIN_MANIFEST_KEYS: frozenset[str] = frozenset(
    {"name", "version", "hooks", "timeout_s", "fail_closed"}
)

# Keys that explicitly name a Python entrypoint. We reject these even
# though they are also "unknown" by ``PLUGIN_MANIFEST_KEYS`` because the
# error message should make the *reason* obvious: this registry is
# declarative-only, not because the operator forgot to list a key but
# because Python-import plugins are out of scope by design.
_PYTHON_IMPORT_KEYS: frozenset[str] = frozenset({"python_module", "py_module"})

# Required keys — a manifest missing either is structurally invalid.
_REQUIRED_KEYS: frozenset[str] = frozenset({"name", "version"})


class PluginTrustError(ValueError):
    """Raised when a manifest violates a trust-boundary rule.

    Inherits ``ValueError`` so existing exception filters that catch
    "bad input" types pick this up, but is its own type so callers that
    must distinguish a *trust* failure from an ordinary parse error can
    do so with one ``except``. The dispatcher is expected to fail-closed
    on this exception — never log it and continue.
    """


@dataclass(frozen=True)
class PluginSpec:
    """One declarative plugin's contract after validation.

    The fields here are the minimum the dispatcher needs to invoke the
    hook: a name (for ordering + audit), a version (for drift detection
    in a later milestone), the absolute manifest path (so the audit log
    can point at the source), the event -> subprocess-command map, and
    two policy flags. Everything else from the TOML is intentionally
    discarded so a future addition to the schema cannot leak into the
    public surface without a code change here.
    """

    name: str
    version: str
    manifest_path: str  # absolute path
    hooks: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 30.0
    fail_closed: bool = False


def _fail(source: Path, msg: str) -> PluginTrustError:
    """Build a ``PluginTrustError`` whose message names the offending file.

    Centralized so every rejection produces a uniformly-shaped message —
    a contributor adding a new rule does not have to re-discover the
    "plugin {path}: {reason}" convention.
    """
    return PluginTrustError(f"plugin {source}: {msg}")


def _validate_top_level_keys(doc: dict[str, Any], source: Path) -> None:
    """Reject Python-import keys and any other unknown top-level field.

    Order matters: we check the Python-import names *first* so the error
    message points at the trust-boundary rule rather than the generic
    "unknown key" rule — easier to debug, and keeps the policy explicit.
    """
    for forbidden in _PYTHON_IMPORT_KEYS:
        if forbidden in doc:
            raise _fail(
                source,
                f"key {forbidden!r} is not allowed — this registry is "
                "declarative-only; Python-import plugins are rejected by "
                "design (see N6.4 / Path B trust boundary)",
            )
    unknown = set(doc.keys()) - PLUGIN_MANIFEST_KEYS
    if unknown:
        raise _fail(
            source,
            f"unknown key(s) {sorted(unknown)!r}; "
            f"allowed keys are {sorted(PLUGIN_MANIFEST_KEYS)}",
        )
    missing = _REQUIRED_KEYS - set(doc.keys())
    if missing:
        raise _fail(
            source,
            f"missing required key(s) {sorted(missing)!r}",
        )


def _validate_hooks(hooks: Any, source: Path) -> dict[str, str]:
    """Normalize and validate the ``[hooks]`` table.

    Returns a fresh ``dict[str, str]`` so the caller's TOML document is
    not retained beyond parse — small but real defense against a later
    edit accidentally aliasing manifest internals into ``PluginSpec``.

    A missing ``[hooks]`` is valid (it just means the plugin registers
    nothing for this run); we return an empty dict. A *present* hooks
    table with a non-string value, however, is rejected — no callables,
    no lists, no nested tables. Subprocess command strings only.
    """
    if hooks is None:
        return {}
    if not isinstance(hooks, dict):
        raise _fail(source, "[hooks] must be a table")
    out: dict[str, str] = {}
    for event, command in hooks.items():
        if not isinstance(event, str):  # tomllib gives str keys, but be safe
            raise _fail(source, f"[hooks] event names must be strings, got {event!r}")
        if not isinstance(command, str):
            raise _fail(
                source,
                f"[hooks.{event}] command must be a string, "
                f"got {type(command).__name__}",
            )
        out[event] = command
    return out


def _parse_manifest(path: Path, allowlist: frozenset[str]) -> PluginSpec:
    """Read one TOML file and return its ``PluginSpec`` or raise.

    Every failure mode lands on ``PluginTrustError`` so the caller has
    exactly one exception class to catch. ``tomllib.TOMLDecodeError`` is
    wrapped here so a malformed file is treated the same as any other
    trust violation (fail-closed on bad input).
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise _fail(path, f"cannot read manifest: {exc}") from exc
    try:
        doc = tomllib.loads(raw_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise _fail(path, f"invalid TOML: {exc}") from exc
    if not isinstance(doc, dict):  # pragma: no cover — tomllib always returns dict
        raise _fail(path, "manifest root must be a table")

    _validate_top_level_keys(doc, path)

    name = doc["name"]
    if not isinstance(name, str) or not name.strip():
        raise _fail(path, "'name' must be a non-empty string")
    if name not in allowlist:
        raise _fail(
            path,
            f"plugin name {name!r} is not in the allowlist "
            f"{sorted(allowlist)!r}",
        )

    version = doc["version"]
    if not isinstance(version, str) or not version.strip():
        raise _fail(path, "'version' must be a non-empty string")

    hooks = _validate_hooks(doc.get("hooks"), path)

    timeout_raw = doc.get("timeout_s", 30.0)
    if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
        # bool is a subclass of int in Python — guard explicitly so a
        # ``timeout_s = true`` typo does not silently coerce to 1.0.
        raise _fail(path, f"'timeout_s' must be a number, got {timeout_raw!r}")
    timeout_s = float(timeout_raw)
    if timeout_s <= 0:
        raise _fail(path, f"'timeout_s' must be > 0, got {timeout_s}")

    fail_closed_raw = doc.get("fail_closed", False)
    if not isinstance(fail_closed_raw, bool):
        raise _fail(
            path, f"'fail_closed' must be a boolean, got {fail_closed_raw!r}"
        )

    return PluginSpec(
        name=name,
        version=version,
        manifest_path=str(path.resolve()),
        hooks=hooks,
        timeout_s=timeout_s,
        fail_closed=bool(fail_closed_raw),
    )


class PluginRegistry:
    """Discover, validate, and index declarative plugin manifests.

    Construction is cheap — no I/O happens until ``load_all()`` is
    called. ``load_all`` is idempotent: subsequent calls re-read the
    manifest directory and replace the internal index, so a long-lived
    registry can be refreshed mid-run if a higher layer wants that.

    Ordering: the registry sorts manifest files by stem before parsing
    so the resulting ``PluginSpec`` list — and the per-event
    ``hooks_for`` chain — is deterministic across machines. The
    HookBusShim documents "registration order = dispatch order"; by
    pinning registration to sorted-by-name we get reproducible
    dispatch without requiring callers to provide an explicit order.
    """

    def __init__(self, plugin_dir: Path, allowlist: frozenset[str]) -> None:
        """Bind the registry to a directory and an allowlist.

        Args:
            plugin_dir: Directory containing ``<name>.toml`` manifests.
                Need not exist at construction time — ``load_all``
                treats a missing directory the same as an empty one,
                which is the right default for a fresh project that has
                not yet adopted any plugin.
            allowlist: The set of plugin names the operator has opted
                into. ``frozenset`` because the registry must not be
                able to mutate it — a plugin cannot enrol itself.
        """
        self._plugin_dir = plugin_dir
        self._allowlist = allowlist
        self._specs: list[PluginSpec] = []

    def load_all(self) -> list[PluginSpec]:
        """Scan ``plugin_dir`` for ``*.toml``, validate each, return list.

        Validation failures raise ``PluginTrustError`` and abort the
        load — partial loads are not allowed because a half-loaded
        registry would silently disable some plugins, which is exactly
        the failure mode the trust boundary exists to prevent.
        """
        if not self._plugin_dir.exists():
            self._specs = []
            return []
        if not self._plugin_dir.is_dir():
            raise _fail(
                self._plugin_dir, "plugin path exists but is not a directory"
            )
        # Sorting by stem (filename without extension) so two plugins
        # with the same TOML name produce a stable order.
        manifest_paths = sorted(
            self._plugin_dir.glob("*.toml"), key=lambda p: p.stem
        )
        specs: list[PluginSpec] = []
        for path in manifest_paths:
            spec = _parse_manifest(path, self._allowlist)
            specs.append(spec)
        self._specs = specs
        return list(specs)

    def hooks_for(self, event_name: str) -> list[tuple[str, str]]:
        """Return ``(plugin_name, command)`` pairs registered for one event.

        Returns an empty list if no plugin registers the event — the
        caller does not need to special-case "no listeners". The order
        mirrors ``list_plugins`` (sorted by plugin name) so dispatch is
        reproducible.

        Note: the registry returns the *raw command string*, including
        any ``$BMAD_*`` placeholders. The dispatcher is responsible for
        substituting runtime context — the registry must not eagerly
        interpolate because the substitution values are not known until
        a hook actually fires.
        """
        return [
            (spec.name, spec.hooks[event_name])
            for spec in self._specs
            if event_name in spec.hooks
        ]

    def list_plugins(self) -> list[PluginSpec]:
        """Return every loaded ``PluginSpec``, sorted by name.

        Returns a fresh list so callers can mutate the result without
        disturbing the registry. The sort is by ``name`` (not file
        stem) so a manifest whose filename and ``name`` field differ
        still lands where its plugin name says it should.
        """
        return sorted(self._specs, key=lambda s: s.name)


__all__ = [
    "PLUGIN_MANIFEST_KEYS",
    "PluginRegistry",
    "PluginSpec",
    "PluginTrustError",
]
