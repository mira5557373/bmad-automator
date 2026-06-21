"""Integration package — bridges between story-automator stores and bmad-auto.

Each module here translates between a story-automator internal artefact
(sprint-status.yaml, risk profile, gate file, ...) and a bmad-auto-shaped
representation. They are pure-translator modules: no subprocess, no
network, no audit emission. Calling sites in commands/ wire them into
the orchestrator loop.
"""

from __future__ import annotations
