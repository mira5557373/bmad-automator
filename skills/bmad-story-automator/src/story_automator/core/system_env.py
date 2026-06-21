"""System environment tier resolution, config, and provision/teardown (§10).

Resolves whether an epic gate needs a minimal (testcontainers/compose)
or full (kind/k3d + Helm) ephemeral environment, and builds the
SystemEnvConfig used by provision/teardown.
"""
from __future__ import annotations

import dataclasses
import subprocess
import uuid
from contextlib import contextmanager
from typing import Any

from .trust_boundary import assert_host_context

ENV_TIER_MINIMAL = "minimal"
ENV_TIER_FULL = "full"

_FULL_TIER_EPIC_TYPES = frozenset({"infra", "cross-cutting"})


@dataclasses.dataclass(frozen=True)
class SystemEnvConfig:
    """Configuration for an ephemeral system-test environment."""

    tier: str
    namespace: str
    compose_file: str = ""
    helm_values: str = ""
    services: tuple[str, ...] = ()
    seed_data: str = ""


@dataclasses.dataclass(frozen=True)
class SystemEnvInfo:
    """Runtime details of a provisioned system environment."""

    env_id: str
    tier: str
    namespace: str
    endpoints: dict[str, str] = dataclasses.field(default_factory=dict)
    provisioned: bool = True


def resolve_env_tier(
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    """§10: resolve minimal vs full env tier.

    FULL for infra/cross-cutting epics and release candidates.
    Profile can force tier via rules.system_env.force_tier.
    """
    rules = (profile.get("rules") or {}).get("system_env") or {}
    force = rules.get("force_tier", "")
    if force in (ENV_TIER_MINIMAL, ENV_TIER_FULL):
        return force

    epic_type = epic_metadata.get("type", "")
    if epic_type in _FULL_TIER_EPIC_TYPES:
        return ENV_TIER_FULL

    if epic_metadata.get("release_candidate"):
        return ENV_TIER_FULL

    return ENV_TIER_MINIMAL


def build_env_config(
    project_root: str,
    commit_sha: str,
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
) -> SystemEnvConfig:
    """Build a SystemEnvConfig for the given epic and profile."""
    tier = resolve_env_tier(epic_metadata, profile)
    sha_prefix = commit_sha[:8] if commit_sha else "unknown"
    epic_id = epic_metadata.get("id", "epic")
    namespace = f"gate-{epic_id}-{sha_prefix}"

    rules = (profile.get("rules") or {}).get("system_env") or {}
    compose_file = str(rules.get("compose_file", ""))
    helm_values = str(rules.get("helm_values", ""))
    services = tuple(rules.get("services") or ())
    seed_data = str(rules.get("seed_data", ""))

    return SystemEnvConfig(
        tier=tier,
        namespace=namespace,
        compose_file=compose_file,
        helm_values=helm_values,
        services=services,
        seed_data=seed_data,
    )


def provision_system_env(
    config: SystemEnvConfig,
    project_root: str,
) -> SystemEnvInfo:
    """Provision an ephemeral environment for system-altitude checks."""
    assert_host_context("provision_system_env")
    env_id = f"sysenv-{uuid.uuid4().hex[:8]}"
    if config.tier == ENV_TIER_MINIMAL:
        return _provision_minimal(config, project_root, env_id)
    return _provision_full(config, project_root, env_id)


def _provision_minimal(
    config: SystemEnvConfig,
    project_root: str,
    env_id: str,
) -> SystemEnvInfo:
    compose = config.compose_file or "docker-compose.yaml"
    cmd = ["docker", "compose", "-f", compose, "-p", config.namespace, "up", "-d"]
    result = subprocess.run(
        cmd, cwd=project_root, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return SystemEnvInfo(
            env_id=env_id, tier=ENV_TIER_MINIMAL,
            namespace=config.namespace, provisioned=False,
        )
    return SystemEnvInfo(
        env_id=env_id, tier=ENV_TIER_MINIMAL, namespace=config.namespace,
    )


def _provision_full(
    config: SystemEnvConfig,
    project_root: str,
    env_id: str,
) -> SystemEnvInfo:
    kind_cmd = ["kind", "create", "cluster", "--name", config.namespace]
    result = subprocess.run(
        kind_cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return SystemEnvInfo(
            env_id=env_id, tier=ENV_TIER_FULL,
            namespace=config.namespace, provisioned=False,
        )
    if config.helm_values:
        helm_cmd = [
            "helm", "install", config.namespace, ".",
            "-f", config.helm_values, "-n", config.namespace,
        ]
        subprocess.run(
            helm_cmd, cwd=project_root, capture_output=True, text=True, timeout=600,
        )
    return SystemEnvInfo(
        env_id=env_id, tier=ENV_TIER_FULL, namespace=config.namespace,
    )


def teardown_system_env(
    env_info: SystemEnvInfo,
    project_root: str,
) -> None:
    """Tear down a provisioned ephemeral environment."""
    assert_host_context("teardown_system_env")
    if env_info.tier == ENV_TIER_MINIMAL:
        subprocess.run(
            ["docker", "compose", "-p", env_info.namespace, "down", "-v"],
            cwd=project_root, capture_output=True, text=True, timeout=120,
        )
    elif env_info.tier == ENV_TIER_FULL:
        subprocess.run(
            ["kind", "delete", "cluster", "--name", env_info.namespace],
            capture_output=True, text=True, timeout=120,
        )


@contextmanager
def system_env(config: SystemEnvConfig, project_root: str):
    """Context manager: provision -> yield -> teardown."""
    info = provision_system_env(config, project_root)
    try:
        yield info
    finally:
        teardown_system_env(info, project_root)
