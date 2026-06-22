"""bauto_bridge — interop layer between bmad-automator (bauto) policy files
and the story-automator runtime configuration.

This subpackage hosts adapters that translate external configuration formats
(currently TOML policy files) into the runtime's dict-shaped policy view and
back again. It is intentionally a thin bridge: it does not interpret semantics,
it only converts between serialization formats.
"""

from __future__ import annotations

from .hookbus_shim import (
    KNOWN_EVENTS,
    HookBusShim,
    HookbusShimError,
    HookSpec,
)
from .policy_translator import (
    KNOWN_BAUTO_TABLES,
    PolicyTranslationError,
    policy_toml_to_runtime,
    runtime_to_policy_toml,
)

__all__ = [
    "HookBusShim",
    "HookSpec",
    "HookbusShimError",
    "KNOWN_BAUTO_TABLES",
    "KNOWN_EVENTS",
    "PolicyTranslationError",
    "policy_toml_to_runtime",
    "runtime_to_policy_toml",
]
