"""Generate consult-fragments + confidence-gate preambles for Generators (§12).

Produces preamble text that gets injected into LLM generators,
embedding TEA's consult-fragment requirements and confidence-gate
scoring directives. Pure text generation — no subprocess calls.
Exit 0 = preamble emitted, exit 2 = usage.

Stdout includes a PREAMBLE_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CONSULT_FRAGMENTS = [
    "network-first.md",
    "selector-resilience.md",
    "data-factories.md",
    "network-recorder.md",
    "pact-consumer-framework-setup.md",
]

_CONFIDENCE_GATE = (
    "CONFIDENCE GATE: Rate your confidence 1-10 for each output. "
    "Confidence < 5 triggers automatic CONCERNS verdict and human review. "
    "Consult the authoritative documentation fragments before answering. "
    "Verify claims against the actual codebase, not training data."
)


def _find_fragments(checkout: str) -> list[str]:
    found: list[str] = []
    search_dirs = [
        os.path.join(checkout, ".tea", "fragments"),
        os.path.join(checkout, "docs", "tea"),
        os.path.join(checkout, "_bmad", "fragments"),
    ]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in sorted(os.listdir(search_dir)):
            if fname in _CONSULT_FRAGMENTS:
                found.append(os.path.join(search_dir, fname))
    return found


def _build_preamble(fragments: list[str]) -> str:
    parts = [_CONFIDENCE_GATE, ""]
    if fragments:
        parts.append("CONSULT FRAGMENTS (verify against these before responding):")
        for frag in fragments:
            name = os.path.basename(frag)
            parts.append(f"  - {name}")
        parts.append("")
    else:
        parts.append("No TEA consult fragments found; use best judgment with explicit confidence scores.")
        parts.append("")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: consult_preamble.py <checkout> [output_path]")
        return 2
    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2
    output_path = args[1] if len(args) > 1 else None

    fragments = _find_fragments(checkout)
    preamble = _build_preamble(fragments)

    result = {
        "fragments_found": len(fragments),
        "fragment_names": [os.path.basename(f) for f in fragments],
        "preamble_length": len(preamble),
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(preamble)
        print(f"preamble written to {output_path}")
    else:
        print(preamble)

    print(f"PREAMBLE_RESULT: {json.dumps(result)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
