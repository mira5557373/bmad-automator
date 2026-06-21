from __future__ import annotations

"""Kernel schema for story kernels.

Defines the closed set of required H2 sections that every story kernel
must declare, plus pure helpers to parse, validate, probe, and score a
kernel document. Designed to be the single source of truth for what a
"complete kernel" looks like before a story enters the gate.

The kernel format is Markdown. Sections are introduced by an H2 heading
(``## Section name``). Only the five names in ``REQUIRED_H2_SECTIONS``
are treated as kernel sections; deeper headings (``###`` and below) and
unknown H2 headings are folded into the body of the most recent kernel
section, so author commentary is preserved verbatim.
"""

REQUIRED_H2_SECTIONS: tuple[str, ...] = (
    "Problem",
    "Capabilities",
    "Constraints",
    "Non-goals",
    "Success signal",
)


class KernelSchemaError(ValueError):
    """Raised when a kernel document fails schema validation."""


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise KernelSchemaError(
            f"{name} must be a string, got {type(value).__name__}"
        )
    return value


def _is_required_h2(line: str) -> str | None:
    """Return the section name if ``line`` is a required H2 heading.

    Recognizes exactly ``## <Name>`` with optional trailing whitespace.
    Returns ``None`` for any other line, including deeper headings and
    H2 headings whose name is not in ``REQUIRED_H2_SECTIONS``.
    """
    if not line.startswith("## "):
        return None
    # Reject H3+ ("### ..."); startswith("## ") already excludes "# ".
    if line.startswith("### "):
        return None
    candidate = line[3:].strip()
    if candidate in REQUIRED_H2_SECTIONS:
        return candidate
    return None


def parse_kernel(text: object) -> dict[str, str]:
    """Parse a kernel document into a ``{section_name: body}`` mapping.

    Only required H2 sections appear in the result. Section bodies are
    whitespace-trimmed at the ends. Lines that fall before the first
    recognized section are discarded. Duplicate sections are merged in
    document order (later occurrences are appended with a blank
    separator).
    """
    body = _require_text("kernel text", text)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in body.splitlines():
        name = _is_required_h2(raw_line)
        if name is not None:
            current = name
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append(raw_line)
    return {
        name: "\n".join(lines).strip()
        for name, lines in sections.items()
    }


def validate_kernel(text: object) -> None:
    """Raise ``KernelSchemaError`` if any required section is missing or empty.

    ``text`` must be a string. The error message names every missing or
    empty section so the caller can surface the full gap in one pass.
    """
    sections = parse_kernel(text)
    missing: list[str] = []
    empty: list[str] = []
    for name in REQUIRED_H2_SECTIONS:
        if name not in sections:
            missing.append(name)
        elif not sections[name]:
            empty.append(name)
    if missing or empty:
        parts: list[str] = []
        if missing:
            parts.append("missing sections: " + ", ".join(missing))
        if empty:
            parts.append("empty sections: " + ", ".join(empty))
        raise KernelSchemaError("kernel schema violation — " + "; ".join(parts))


def has_section(text: object, section_name: object) -> bool:
    """Return True if ``section_name`` is declared with a non-empty body.

    Strict on inputs: both arguments must be strings. ``section_name``
    is checked against the parsed section map, so an H2 heading with an
    empty body returns False (the section is structurally present but
    has no content).
    """
    body = _require_text("kernel text", text)
    name = _require_text("section name", section_name)
    sections = parse_kernel(body)
    return bool(sections.get(name))


def kernel_completeness_score(text: object) -> float:
    """Return the fraction of required sections present with non-empty bodies.

    Result is in ``[0.0, 1.0]``. A kernel with all five required
    sections and non-empty bodies scores 1.0; an empty document scores
    0.0. Non-string input raises ``KernelSchemaError``.
    """
    sections = parse_kernel(text)
    total = len(REQUIRED_H2_SECTIONS)
    if total == 0:
        return 0.0
    filled = sum(
        1 for name in REQUIRED_H2_SECTIONS if sections.get(name)
    )
    return filled / total
