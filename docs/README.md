# Documentation Index

Operator and contributor documentation for `bmad-story-automator`. Start with the
top-level [README](../README.md) for install and a product overview.

## Getting Started

- [Installation & Layout](./installation-and-layout.md) — install paths, supported skill roots, platform support
- [How It Works](./how-it-works.md) — the orchestration model

## Operating

- [Story Execution](./story-execution.md) — the per-story plan → implement → verify → review → commit loop
- [Review Workflow](./review-workflow.md) — the adversarial review cycle
- [Agents & Monitoring](./agents-and-monitoring.md) — agent selection and session monitoring
- [State & Resume](./state-and-resume.md) — the orchestration-state document and resuming a run
- [Operations & Recovery](./operations.md) — incident runbooks (crash recovery, corrupt marker, audit verification)

## Reference

- [CLI Reference](./cli-reference.md) — the full command surface and the JSON error contract
- [Versioning](./versioning.md) — release/version channels
- [Troubleshooting](./troubleshooting.md) — common issues

## Contributing & Security

- [Development](./development.md) — local verify, smoke tests, packaging
- [Security](../SECURITY.md) — security posture and vulnerability reporting

## Platform support

The Python helper CLI runs on Windows, macOS, and Linux. Full story orchestration
requires `tmux`, so running stories is supported on **Linux and on Windows via WSL**,
not native Windows shells. Quality gates (lint + tests) stay portable across Windows
git-bash, WSL Ubuntu, and Linux CI.
