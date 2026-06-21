"""Check OTel instrumentation wiring in source code.

Standalone script invoked by the otel-wiring-observability collector.
Scans source files for OpenTelemetry SDK usage patterns.
Exit 0 = all required signals wired, exit 1 = missing, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_SIGNAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "traces": [
        re.compile(r"(?:from\s+opentelemetry\s+import\s+trace|opentelemetry.*trace)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*trace", re.IGNORECASE),
        re.compile(r"import\s*\{[^}]*\btrace\b[^}]*\}.*@opentelemetry", re.IGNORECASE),
        re.compile(r"get_tracer\s*\(", re.IGNORECASE),
    ],
    "metrics": [
        re.compile(r"(?:from\s+opentelemetry\s+import\s+metrics|opentelemetry.*metrics)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*metrics", re.IGNORECASE),
        re.compile(r"import\s*\{[^}]*\bmetrics\b[^}]*\}.*@opentelemetry", re.IGNORECASE),
        re.compile(r"get_meter\s*\(", re.IGNORECASE),
    ],
    "logs": [
        re.compile(r"(?:import\s+logging|from\s+logging\s+import)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*logs", re.IGNORECASE),
        re.compile(r"import\s*\{[^}]*\blogs\b[^}]*\}.*@opentelemetry", re.IGNORECASE),
        re.compile(r"getLogger|get_logger", re.IGNORECASE),
    ],
}

_SOURCE_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})


def check_otel_wiring(
    checkout: str,
    required_signals: list[str],
) -> list[str]:
    """Check that required OTel signals are wired. Returns missing signals."""
    found: set[str] = set()
    for root, _dirs, files in os.walk(checkout):
        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in _SOURCE_EXTENSIONS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            for signal, patterns in _SIGNAL_PATTERNS.items():
                if signal in found:
                    continue
                for pat in patterns:
                    if pat.search(content):
                        found.add(signal)
                        break
    missing: list[str] = []
    for signal in required_signals:
        if signal not in found:
            missing.append(f"MISSING signal: {signal}")
    return missing


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: otel_check.py <checkout> [required_signals_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            required: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid signals list: {args[1]}")
            return 2
    else:
        required = ["traces", "metrics", "logs"]
    missing = check_otel_wiring(checkout, required)
    for m in missing:
        print(m)
    if missing:
        print(f"{len(missing)} OTel signal(s) not wired")
        return 1
    print(f"all {len(required)} OTel signal(s) wired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
