from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .process import SmokeError


REQUIRED_PACKAGE_FILES = [
    "package.json",
    "README.md",
    "LICENSE",
    "ref.png",
    "install.sh",
    "bin/bmad-story-automator",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "skills/module.yaml",
    "skills/module-help.csv",
    "skills/bmad-story-automator/SKILL.md",
    "skills/bmad-story-automator/README.md",
    "skills/bmad-story-automator/LICENSE",
    "skills/bmad-story-automator/workflow.md",
    "skills/bmad-story-automator/pyproject.toml",
    "skills/bmad-story-automator/scripts/story-automator",
    "skills/bmad-story-automator/data/orchestration-policy.json",
    "skills/bmad-story-automator/data/complexity-rules.json",
    "skills/bmad-story-automator/data/agent-config-presets.json",
    "skills/bmad-story-automator/data/parse/auto.json",
    "skills/bmad-story-automator/data/parse/create.json",
    "skills/bmad-story-automator/data/parse/dev.json",
    "skills/bmad-story-automator/data/parse/retro.json",
    "skills/bmad-story-automator/data/parse/review.json",
    "skills/bmad-story-automator/data/prompts/auto.md",
    "skills/bmad-story-automator/data/prompts/create.md",
    "skills/bmad-story-automator/data/prompts/dev.md",
    "skills/bmad-story-automator/data/prompts/retro.md",
    "skills/bmad-story-automator/data/prompts/review.md",
    "skills/bmad-story-automator/templates/state-document.md",
    "skills/bmad-story-automator/steps-c/step-01-init.md",
    "skills/bmad-story-automator/steps-c/step-01b-continue.md",
    "skills/bmad-story-automator/steps-c/step-02-preflight.md",
    "skills/bmad-story-automator/steps-c/step-02a-preflight-config.md",
    "skills/bmad-story-automator/steps-c/step-02b-preflight-finalize.md",
    "skills/bmad-story-automator/steps-c/step-03-execute.md",
    "skills/bmad-story-automator/steps-c/step-03a-execute-review.md",
    "skills/bmad-story-automator/steps-c/step-03b-execute-finish.md",
    "skills/bmad-story-automator/steps-c/step-03c-execute-complete.md",
    "skills/bmad-story-automator/steps-c/step-04-wrapup.md",
    "skills/bmad-story-automator/steps-e/step-e-01-load.md",
    "skills/bmad-story-automator/steps-v/step-v-01-check.md",
    "skills/bmad-story-automator/steps-v/step-v-02-report.md",
    "skills/bmad-story-automator/src/story_automator/__init__.py",
    "skills/bmad-story-automator/src/story_automator/__main__.py",
    "skills/bmad-story-automator/src/story_automator/cli.py",
    "skills/bmad-story-automator/src/story_automator/adapters/tmux.py",
    "skills/bmad-story-automator/src/story_automator/commands/__init__.py",
    "skills/bmad-story-automator/src/story_automator/commands/agent_config_cmd.py",
    "skills/bmad-story-automator/src/story_automator/commands/basic.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator_state.py",
    "skills/bmad-story-automator/src/story_automator/commands/state.py",
    "skills/bmad-story-automator/src/story_automator/commands/tmux.py",
    "skills/bmad-story-automator/src/story_automator/commands/tmux_monitor.py",
    "skills/bmad-story-automator/src/story_automator/commands/validate_story_creation.py",
    "skills/bmad-story-automator/src/story_automator/core/agent_config.py",
    "skills/bmad-story-automator/src/story_automator/core/agent_config_frontmatter.py",
    "skills/bmad-story-automator/src/story_automator/core/agent_plan.py",
    "skills/bmad-story-automator/src/story_automator/core/common.py",
    "skills/bmad-story-automator/src/story_automator/core/diagnostics.py",
    "skills/bmad-story-automator/src/story_automator/core/epic_parser.py",
    "skills/bmad-story-automator/src/story_automator/core/frontmatter.py",
    "skills/bmad-story-automator/src/story_automator/core/monitoring.py",
    "skills/bmad-story-automator/src/story_automator/core/orchestration_events.py",
    "skills/bmad-story-automator/src/story_automator/core/parse_contracts.py",
    "skills/bmad-story-automator/src/story_automator/core/review_verify.py",
    "skills/bmad-story-automator/src/story_automator/core/runtime_layout.py",
    "skills/bmad-story-automator/src/story_automator/core/runtime_policy.py",
    "skills/bmad-story-automator/src/story_automator/core/session_state.py",
    "skills/bmad-story-automator/src/story_automator/core/sprint.py",
    "skills/bmad-story-automator/src/story_automator/core/state_validation.py",
    "skills/bmad-story-automator/src/story_automator/core/stop_hooks.py",
    "skills/bmad-story-automator/src/story_automator/core/story_keys.py",
    "skills/bmad-story-automator/src/story_automator/core/success_verifiers.py",
    "skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py",
    "skills/bmad-story-automator/src/story_automator/core/utils.py",
    "skills/bmad-story-automator/src/story_automator/core/workflow_paths.py",
    "skills/bmad-story-automator-review/SKILL.md",
    "skills/bmad-story-automator-review/checklist.md",
    "skills/bmad-story-automator-review/contract.json",
    "skills/bmad-story-automator-review/instructions.xml",
    "skills/bmad-story-automator-review/workflow.yaml",
]

EXECUTABLE_PACKAGE_FILES = {
    "bin/bmad-story-automator",
    "install.sh",
    "skills/bmad-story-automator/scripts/story-automator",
}

SUPPORTED_SKILL_ROOTS = [".agents/skills", ".claude/skills", ".codex/skills"]
DEPENDENCY_SKILLS = ["bmad-create-story", "bmad-dev-story", "bmad-retrospective"]


def assert_package_contract(root: Path, env: dict[str, str] | None = None) -> dict:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    dry_run = _npm_pack_json(root, ["--dry-run", "--json"], env)
    _assert_pack_metadata(dry_run, package)
    _assert_content(dry_run)

    with tempfile.TemporaryDirectory(prefix="bmad-pack-assert-") as tmp:
        identity = pack_project(root, Path(tmp), env)
        _assert_tarball_checksums(Path(identity["tarball"]), identity["selectedChecksums"])
    return identity


def pack_project(root: Path, pack_dir: Path, env: dict[str, str] | None) -> dict:
    pack_dir.mkdir(parents=True, exist_ok=True)
    for tarball in pack_dir.glob("*.tgz"):
        tarball.unlink()

    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    packed = _npm_pack_json(root, ["--json", "--pack-destination", str(pack_dir)], env)
    _assert_pack_metadata(packed, package)
    _assert_content(packed)
    tarball = pack_dir / packed["filename"]
    if not tarball.is_file():
        raise SmokeError(f"missing packed tarball: {tarball}")
    return _identity_from_pack(root, packed, tarball)


def write_package_identity(workspace: Path, identity: dict) -> Path:
    path = workspace / "PACKAGE_IDENTITY.json"
    path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_installed_package(gunz_dir: Path, identity: dict, workspace: Path) -> Path:
    manifest = {
        "package": {
            key: identity[key]
            for key in ("name", "version", "filename", "integrity", "shasum", "tarballSha256")
            if key in identity
        },
        "roots": [],
    }
    failures: list[str] = []
    for rel_root in SUPPORTED_SKILL_ROOTS:
        root = gunz_dir / rel_root
        deps_present = all((root / dep / "SKILL.md").is_file() for dep in DEPENDENCY_SKILLS)
        story = root / "bmad-story-automator"
        review = root / "bmad-story-automator-review"
        if not deps_present:
            manifest["roots"].append(
                {
                    "root": rel_root,
                    "status": "unsupported",
                    "reason": "missing required dependency skill entrypoints",
                }
            )
            continue
        if not story.is_dir() or not review.is_dir():
            failures.append(f"{rel_root}: automator skills not installed")
            continue

        root_result = {"root": rel_root, "status": "installed", "checksums": {}}
        for package_path, expected in identity["selectedChecksums"].items():
            if not package_path.startswith("skills/"):
                continue
            installed_rel = package_path.removeprefix("skills/")
            installed_path = root / installed_rel
            if not installed_path.is_file():
                failures.append(f"{rel_root}: missing installed file {installed_rel}")
                continue
            actual = _sha256(installed_path)
            root_result["checksums"][installed_rel] = actual
            if actual != expected:
                failures.append(
                    f"{rel_root}: checksum mismatch for {installed_rel}: {actual} != {expected}"
                )
        manifest["roots"].append(root_result)

    if not any(root["status"] == "installed" for root in manifest["roots"]):
        failures.append("no supported skill root installed automator")
    if failures:
        raise SmokeError("installed package verification failed:\n" + "\n".join(failures))

    path = workspace / "INSTALLED_AUTOMATOR_MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _npm_pack_json(root: Path, args: list[str], env: dict[str, str] | None) -> dict:
    result = subprocess.run(
        ["npm", "pack", *args],
        cwd=root,
        env=env,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(
            "failed to parse npm pack JSON"
            f"\nstdout:\n{result.stdout.strip()}"
            f"\nstderr:\n{result.stderr.strip()}"
        ) from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise SmokeError(f"unexpected npm pack JSON: {result.stdout.strip()}")
    return payload[0]


def _assert_pack_metadata(metadata: dict, package: dict) -> None:
    expected_filename = f"{package['name']}-{package['version']}.tgz"
    failures = []
    for key in ("name", "version"):
        if metadata.get(key) != package[key]:
            failures.append(f"{key}: {metadata.get(key)} != {package[key]}")
    if metadata.get("filename") != expected_filename:
        failures.append(f"filename: {metadata.get('filename')} != {expected_filename}")
    if not (metadata.get("integrity") or metadata.get("shasum")):
        failures.append("missing integrity or shasum")
    if failures:
        raise SmokeError("package identity failed:\n" + "\n".join(failures))


def _assert_content(metadata: dict) -> None:
    entries = {entry["path"]: entry for entry in metadata["files"]}
    missing = sorted(set(REQUIRED_PACKAGE_FILES) - set(entries))
    failures = []
    if missing:
        failures.append("missing required files:\n" + "\n".join(missing))
    for path in EXECUTABLE_PACKAGE_FILES:
        if entries.get(path, {}).get("mode") != 493:
            failures.append(f"expected executable mode 493 for {path}")
    forbidden = sorted(path for path in entries if _is_forbidden(path))
    if forbidden:
        failures.append("forbidden generated files:\n" + "\n".join(forbidden))
    if failures:
        raise SmokeError("package content failed:\n" + "\n\n".join(failures))


def _is_forbidden(path: str) -> bool:
    parts = path.split("/")
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or "node_modules" in parts
        or "dist" in parts
        or path.endswith((".pyc", ".pyo", ".tgz", ".DS_Store"))
        or path.startswith(".firecrawl/")
        or path.startswith(".smoke/")
        or path.startswith("skills/bmad-story-automator/build/")
        or ".egg-info" in parts
    )


def _identity_from_pack(root: Path, metadata: dict, tarball: Path) -> dict:
    return {
        "name": metadata["name"],
        "version": metadata["version"],
        "filename": metadata["filename"],
        "integrity": metadata.get("integrity"),
        "shasum": metadata.get("shasum"),
        "tarball": str(tarball),
        "tarballSha256": _sha256(tarball),
        "entryCount": metadata.get("entryCount"),
        "selectedChecksums": _selected_checksums_from_tarball(tarball),
        "sourcePackageJson": str(root / "package.json"),
    }


def _selected_checksums_from_tarball(tarball: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    with tarfile.open(tarball, "r:gz") as archive:
        for member_info in archive.getmembers():
            if not member_info.isfile():
                continue
            package_path = _installed_skill_package_path(member_info.name)
            if package_path is None:
                continue
            member = archive.extractfile(member_info)
            if member is None:
                raise SmokeError(f"missing tarball member: {member_info.name}")
            checksums[package_path] = hashlib.sha256(member.read()).hexdigest()
    return checksums


def _installed_skill_package_path(tar_member_name: str) -> str | None:
    prefix = "package/"
    if not tar_member_name.startswith(prefix):
        return None
    package_path = tar_member_name.removeprefix(prefix)
    if package_path.startswith(
        (
            "skills/bmad-story-automator/",
            "skills/bmad-story-automator-review/",
        )
    ):
        return package_path
    return None


def _assert_tarball_checksums(tarball: Path, checksums: dict[str, str]) -> None:
    with tarfile.open(tarball, "r:gz") as archive:
        for package_path, expected in checksums.items():
            member = archive.extractfile(f"package/{package_path}")
            if member is None:
                raise SmokeError(f"missing tarball member: {package_path}")
            actual = hashlib.sha256(member.read()).hexdigest()
            if actual != expected:
                raise SmokeError(f"tarball checksum mismatch: {package_path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
