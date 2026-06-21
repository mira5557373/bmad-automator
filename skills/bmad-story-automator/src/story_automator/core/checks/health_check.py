"""Check /healthz and /readyz endpoint declarations.

Standalone script invoked by the health-probe-observability collector.
Scans source and config files for health/ready endpoint registrations.
Exit 0 = all endpoints found, exit 1 = missing, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_SOURCE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml",
})


def _build_endpoint_re(endpoint: str) -> re.Pattern[str]:
    escaped = re.escape(endpoint)
    return re.compile(escaped)


def check_health_endpoints(
    checkout: str,
    endpoints: list[str],
) -> list[str]:
    """Check that all required endpoints are declared. Returns missing."""
    patterns = {ep: _build_endpoint_re(ep) for ep in endpoints}
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
            for ep, pat in patterns.items():
                if ep in found:
                    continue
                if pat.search(content):
                    found.add(ep)
    missing: list[str] = []
    for ep in endpoints:
        if ep not in found:
            missing.append(f"MISSING endpoint: {ep}")
    return missing


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: health_check.py <checkout> [endpoints_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            endpoints: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid endpoints list: {args[1]}")
            return 2
    else:
        endpoints = ["/healthz", "/readyz"]
    missing = check_health_endpoints(checkout, endpoints)
    for m in missing:
        print(m)
    if missing:
        print(f"{len(missing)} health endpoint(s) not declared")
        return 1
    print(f"all {len(endpoints)} health endpoint(s) declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
