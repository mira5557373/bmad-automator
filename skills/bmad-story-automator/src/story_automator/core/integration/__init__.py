"""Integration bridges between TEA gate output and external skills.

Modules in this package translate internal gate verdicts (gate_schema.py
shapes) into payloads consumable by external skills such as the bundled
``bmad-story-automator-review`` adversarial code-review skill. They are
strictly read-only with respect to TEA state: bridges never mutate gate
files, evidence records, or telemetry events.
"""
from __future__ import annotations
