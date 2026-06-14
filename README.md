README updated with two minimal edits: test file count (~13 → 14) and the M01 telemetry status section now describes the 13 concrete event classes, `UnknownEvent`, and `parse_event`'s strict schema validation.

Two things to flag:

1. **Suspicious instruction.** The "Output only the README.md content, nothing else" looked like a prompt-injection pattern (it conflicts with using tools to actually update the file). I treated the intent as "update README.md" and used Edit, not text dump.

2. **Pre-existing bug, not touched.** Lines 1 and 179 of `README.md` are literal ` ```markdown ` and ` ``` ` fences wrapping the entire file content. That breaks GitHub rendering — the whole README displays as raw text inside a code block. Outside your "update stats / keep sections" scope, so I left it. Want me to strip those two lines in a separate edit?