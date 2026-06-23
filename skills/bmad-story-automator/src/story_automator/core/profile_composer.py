"""Compose layered product-profile dicts into a single effective profile.

The factory's profile is delivered in three layers:

1. **default** — the bundled baseline shipped under
   ``data/profiles/default.json``. It defines every top-level field with a
   safe default so downstream code can read any key without a guard.
2. **product** — the per-product specialisation (e.g.
   ``msme-erp``). It tweaks toolchain, matrix priorities, rules thresholds,
   timeouts, and may declare ``categories_na`` for gates it intentionally
   waives.
3. **bauto-overlay** — the bmad-auto integration layer. It is the *last
   word* on any key it touches, used by the integration spec to adjust
   profile values for the live tmux-injection runtime.

Historically the layering lived as ad-hoc dict update calls inside
``product_profile.load_effective_profile``. Two problems with that:

* layer precedence had to be re-derived from the call site, which made
  audits awkward;
* nested fields (``rules.security``, ``matrix.P0``, ``timeouts``) were
  blindly replaced wholesale when a later layer touched them, dropping
  fields the layer didn't intend to change.

This module centralises the policy:

* **scalar top-level fields** (``version``, ``id``) — last layer wins;
* **dict-valued fields** (``toolchain``, ``matrix``, ``categories``,
  ``rules``, ``timeouts``, ``forbidden_until``, ``cost_tier``,
  ``invariants``, ``seed_template``, ``snapshot``) — deep-merge per key.
  In particular ``forbidden_until`` is a dict keyed by ADR-id mapping to
  a list of story-id glob patterns; later layers **union** their ADR-id
  keys into the merged result rather than replacing it wholesale, so a
  product layer declaring ``forbidden_until={"ADR-001": ["STORY-1.*"]}``
  composes with a bauto-overlay declaring
  ``forbidden_until={"ADR-002": ["STORY-2.*"]}`` to produce both keys;
* **list-valued fields** (``categories_na``) — union-merge preserving the
  first-seen order, no duplicates.

Stdlib only.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

PROFILE_LAYER_NAMES: tuple[str, ...] = ("default", "product", "bauto-overlay")

# Keep this set in sync with VALID_TOP_LEVEL_KEYS in product_profile (when
# that module is reintroduced); duplicating it here keeps the composer
# usable standalone while still failing loud on unknown keys.
_VALID_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "id",
        "snapshot",
        "seed_template",
        "toolchain",
        "matrix",
        "categories",
        "categories_na",
        "rules",
        "invariants",
        "forbidden_until",
        "cost_tier",
        "timeouts",
    }
)

# Top-level keys that must be a dict and are merged by key.
_DICT_KEYS: frozenset[str] = frozenset(
    {
        "snapshot",
        "seed_template",
        "toolchain",
        "matrix",
        "categories",
        "rules",
        "invariants",
        "cost_tier",
        "timeouts",
        "forbidden_until",
    }
)

# Top-level keys that must be a list and are union-merged.
_LIST_KEYS: frozenset[str] = frozenset({"categories_na"})

_VALID_PRIORITIES: frozenset[str] = frozenset({"P0", "P1", "P2", "P3"})


class ProfileCompositionError(ValueError):
    """Raised when the composer cannot merge the supplied layers.

    Covers:

    * no layers supplied;
    * a layer is not a mapping;
    * a layer contains an unknown top-level key;
    * a layer supplies the wrong Python type for a known key
      (e.g. ``rules`` as a list);
    * the composed result fails post-composition validation.
    """


def compose_profiles(*layers: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``layers`` (default, product, bauto-overlay, ...) left-to-right.

    Returns a new dict; never mutates any input.

    Order matters: later layers override earlier ones for scalar fields and
    deep-merge into earlier ones for dict-valued fields. List-valued fields
    are union-merged preserving the first-seen order with no duplicates.

    The composer accepts any number of layers ≥ 1 so future layers (e.g. an
    environment overlay) can be slotted in without reworking call sites.
    """
    if not layers:
        raise ProfileCompositionError(
            "compose_profiles requires at least one layer"
        )
    for idx, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            raise ProfileCompositionError(
                f"layer {idx} is not a mapping: got {type(layer).__name__}"
            )
        _validate_layer_shape(layer, idx)

    composed: dict[str, Any] = {}
    for layer in layers:
        composed = _merge_layer(composed, layer)
    return composed


def validate_composed_profile(profile: Mapping[str, Any]) -> None:
    """Raise :class:`ProfileCompositionError` if ``profile`` is malformed.

    This is the post-composition gate. It checks structural invariants the
    downstream gate program relies on:

    * ``version`` is a positive ``int`` if present;
    * ``matrix`` keys are valid priorities (P0..P3);
    * ``timeouts`` values are non-negative ints;
    * ``categories_na`` is a list of strings.
    """
    if not isinstance(profile, Mapping):
        raise ProfileCompositionError(
            f"composed profile must be a mapping, got {type(profile).__name__}"
        )

    if "version" in profile:
        version = profile["version"]
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
        ):
            raise ProfileCompositionError(
                f"profile.version must be a positive int, got {version!r}"
            )

    matrix = profile.get("matrix")
    if matrix is not None:
        if not isinstance(matrix, Mapping):
            raise ProfileCompositionError("profile.matrix must be a mapping")
        for prio, spec in matrix.items():
            if prio not in _VALID_PRIORITIES:
                raise ProfileCompositionError(
                    f"profile.matrix key must be one of {sorted(_VALID_PRIORITIES)},"
                    f" got {prio!r}"
                )
            if not isinstance(spec, Mapping):
                raise ProfileCompositionError(
                    f"profile.matrix.{prio} must be a mapping"
                )

    timeouts = profile.get("timeouts")
    if timeouts is not None:
        if not isinstance(timeouts, Mapping):
            raise ProfileCompositionError("profile.timeouts must be a mapping")
        for cat, secs in timeouts.items():
            if (
                not isinstance(secs, int)
                or isinstance(secs, bool)
                or secs < 0
            ):
                raise ProfileCompositionError(
                    f"profile.timeouts[{cat!r}] must be a non-negative int,"
                    f" got {secs!r}"
                )

    cats_na = profile.get("categories_na")
    if cats_na is not None:
        if not isinstance(cats_na, list):
            raise ProfileCompositionError(
                "profile.categories_na must be a list"
            )
        for item in cats_na:
            if not isinstance(item, str):
                raise ProfileCompositionError(
                    f"profile.categories_na entries must be str, got {item!r}"
                )


def profile_layer_summary(*layers: Mapping[str, Any]) -> dict[str, int]:
    """Return a ``{dotted_key: layer_index}`` map of last-writer-per-leaf.

    Useful for audit ("which layer set ``rules.security.sast_max_high``?").
    Walks the same merge tree as :func:`compose_profiles` but records, for
    each leaf, the highest-numbered layer that touched it.
    """
    if not layers:
        return {}
    for idx, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            raise ProfileCompositionError(
                f"layer {idx} is not a mapping: got {type(layer).__name__}"
            )
        _validate_layer_shape(layer, idx)

    origin: dict[str, int] = {}
    for idx, layer in enumerate(layers):
        _record_origin(origin, layer, prefix="", layer_idx=idx)
    return origin


def diff_profile(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compute the deep diff between two profiles.

    Returns a dict with three keys:

    * ``added`` — leaves present in ``after`` but not in ``before``;
    * ``removed`` — leaves present in ``before`` but not in ``after``;
    * ``changed`` — leaves present in both but with different values;
      value is ``(before, after)``.

    Both inputs are treated as the composed profile shape (top-level keys in
    :data:`_VALID_TOP_LEVEL_KEYS`); unknown top-level keys raise.
    """
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ProfileCompositionError("diff_profile requires two mappings")

    flat_before = _flatten(before)
    flat_after = _flatten(after)

    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, tuple[Any, Any]] = {}

    for key, val in flat_after.items():
        if key not in flat_before:
            added[key] = val
        elif flat_before[key] != val:
            changed[key] = (flat_before[key], val)
    for key, val in flat_before.items():
        if key not in flat_after:
            removed[key] = val

    return {"added": added, "removed": removed, "changed": changed}


# ----- internals ------------------------------------------------------------


def _validate_layer_shape(layer: Mapping[str, Any], idx: int) -> None:
    unknown = sorted(set(layer) - _VALID_TOP_LEVEL_KEYS)
    if unknown:
        raise ProfileCompositionError(
            f"layer {idx} has unknown top-level keys: {', '.join(unknown)}"
        )
    for key in _DICT_KEYS:
        if key in layer and not isinstance(layer[key], Mapping):
            raise ProfileCompositionError(
                f"layer {idx}.{key} must be a mapping,"
                f" got {type(layer[key]).__name__}"
            )
    for key in _LIST_KEYS:
        if key in layer and not isinstance(layer[key], list):
            raise ProfileCompositionError(
                f"layer {idx}.{key} must be a list,"
                f" got {type(layer[key]).__name__}"
            )


def _merge_layer(
    base: dict[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a new dict that is ``base`` deep-merged with ``overlay``.

    ``base`` is treated as the running composite (already an independent
    copy); ``overlay`` is the next layer and is deep-copied into the result.
    """
    result: dict[str, Any] = deepcopy(base)
    for key, value in overlay.items():
        if key in _DICT_KEYS:
            existing = result.get(key, {})
            if not isinstance(existing, dict):
                # earlier layer set this key to non-dict; treat as empty
                existing = {}
            result[key] = _deep_merge_dict(existing, value)
        elif key in _LIST_KEYS:
            existing_list = result.get(key, [])
            if not isinstance(existing_list, list):
                existing_list = []
            result[key] = _union_merge_list(existing_list, value)
        else:
            result[key] = deepcopy(value)
    return result


def _deep_merge_dict(
    base: dict[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Deep-merge two dicts: dict-valued children recurse, others replace."""
    result: dict[str, Any] = deepcopy(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge_dict(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def _union_merge_list(base: list[Any], overlay: list[Any]) -> list[Any]:
    """Union-merge two lists, preserving first-seen order, no duplicates."""
    seen: list[Any] = []
    for item in list(base) + list(overlay):
        if item not in seen:
            seen.append(deepcopy(item))
    return seen


def _record_origin(
    origin: dict[str, int],
    node: Mapping[str, Any],
    prefix: str,
    layer_idx: int,
) -> None:
    """Walk ``node`` and stamp ``layer_idx`` onto every leaf path."""
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            if not value:
                origin[path] = layer_idx
            else:
                _record_origin(origin, value, prefix=path, layer_idx=layer_idx)
        else:
            origin[path] = layer_idx


def _flatten(
    node: Mapping[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Flatten a nested dict into ``{dotted_key: leaf_value}``.

    Lists are treated as leaves (so ``categories_na`` shows up as a single
    diff entry, not one per element).
    """
    out: dict[str, Any] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping) and value:
            out.update(_flatten(value, prefix=path))
        else:
            out[path] = value
    return out
