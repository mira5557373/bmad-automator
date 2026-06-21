"""Run mutation testing tool and check score against threshold.

Standalone script invoked by mutation collectors.
Exit 0 = threshold met, exit 1 = below threshold, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import re
import subprocess
import sys

_MUTMUT_KILLED_RE = re.compile(
    r"Killed\s+(\d+)\s+out\s+of\s+(\d+)", re.IGNORECASE,
)
_STRYKER_SCORE_RE = re.compile(
    r"Mutation\s+score:\s+([\d.]+)", re.IGNORECASE,
)
_SUPPORTED_TOOLS = ("mutmut", "stryker")


def parse_mutmut_results(output: str) -> dict:
    """Parse mutmut output for killed/total counts."""
    match = _MUTMUT_KILLED_RE.search(output)
    if match:
        killed = int(match.group(1))
        total = int(match.group(2))
        score = (killed / total * 100) if total > 0 else 100.0
        return {"killed": killed, "total": total, "score": score}
    if "no mutants" in output.lower():
        return {"killed": 0, "total": 0, "score": 100.0}
    return {"killed": 0, "total": 0, "score": -1}


def parse_stryker_results(output: str) -> dict:
    """Parse Stryker output for mutation score."""
    match = _STRYKER_SCORE_RE.search(output)
    if match:
        score = float(match.group(1))
        return {"score": score}
    return {"score": -1}


def check_threshold(
    score: float, threshold: int,
) -> tuple[bool, list[str]]:
    """Check mutation score against threshold."""
    if score < 0:
        return False, ["mutation testing produced no score"]
    if score < threshold:
        return False, [
            f"mutation score {score:.1f}% below threshold {threshold}%"
        ]
    return True, []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print("usage: mutation_check.py <checkout> <tool> <threshold>")
        return 2
    checkout = args[0]
    tool = args[1]
    if tool not in _SUPPORTED_TOOLS:
        print(f"unsupported mutation tool: {tool}")
        return 2
    try:
        threshold = int(args[2])
    except ValueError:
        print(f"invalid threshold: {args[2]}")
        return 2
    if tool == "mutmut":
        cmd = ["mutmut", "run", "--CI"]
    else:
        cmd = ["npx", "stryker", "run"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=1800, cwd=checkout,
        )
    except FileNotFoundError:
        print(f"{tool} not found")
        return 1
    except subprocess.TimeoutExpired:
        print(f"{tool} timed out")
        return 1
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if tool == "mutmut":
        result = parse_mutmut_results(output)
    else:
        result = parse_stryker_results(output)
    ok, issues = check_threshold(result["score"], threshold)
    for issue in issues:
        print(issue)
    if not ok:
        return 1
    print(f"mutation score {result['score']:.1f}% >= {threshold}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
