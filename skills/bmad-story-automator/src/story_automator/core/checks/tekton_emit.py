"""Emit a Tekton CI pipeline definition for gate collectors (§8 module 5).

Generates a Tekton PipelineRun YAML that runs each registered
gate collector as a separate Tekton Task. Output is written to stdout
or a file path. Does not execute the pipeline.
Exit 0 = emitted, exit 2 = usage.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys


def _tekton_task(collector_id: str, category: str, cmd: list[str]) -> dict:
    safe_name = collector_id.replace("_", "-")
    return {
        "name": safe_name,
        "taskSpec": {
            "steps": [{
                "name": "run-collector",
                "image": "python:3.11-slim",
                "command": cmd[:1],
                "args": cmd[1:],
            }],
        },
    }


def emit_pipeline(
    collectors: list[dict[str, str]],
    pipeline_name: str = "gate-pipeline",
) -> str:
    tasks = []
    for c in collectors:
        task = _tekton_task(
            c.get("collector_id", "unknown"),
            c.get("category", "unknown"),
            c.get("cmd", ["echo", "no-op"]),
        )
        tasks.append(task)

    pipeline = {
        "apiVersion": "tekton.dev/v1beta1",
        "kind": "PipelineRun",
        "metadata": {"generateName": f"{pipeline_name}-"},
        "spec": {
            "pipelineSpec": {
                "tasks": tasks,
            },
        },
    }
    lines = [
        "# Auto-generated Tekton pipeline for factory gate",
        f"# Collectors: {len(collectors)}",
        json.dumps(pipeline, indent=2),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: tekton_emit.py <collectors_json> [output_path]")
        return 2

    collectors_path = args[0]
    output_path = args[1] if len(args) > 1 else None

    if not os.path.isfile(collectors_path):
        print(f"collectors file not found: {collectors_path}")
        return 2

    try:
        with open(collectors_path, encoding="utf-8") as f:
            collectors = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read collectors: {exc}")
        return 2

    content = emit_pipeline(collectors)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Tekton pipeline written to {output_path}")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
