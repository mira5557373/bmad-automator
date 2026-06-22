# Round-3 fix-now list (locked before any fix lands)

> Per gap C-M-08 from spec-review-2026-06-22-C: committing the chosen
> ≤5 slugs *before* any fix lands makes "while I was here" expansion
> visible. Adding a 6th slug requires editing this file in a separate
> visible commit.

| Rank | Slug | Lens | Module | Severity | Confidence |
|---|---|---|---|---|---|
| 1 | `c-1-quarantine-mkdir-honest` | M | `core/gate_orchestrator.py` | HIGH | HIGH |
| 2 | `c-2-ceilings-single-pass` | K | `core/budget_ceilings.py` | HIGH | HIGH |
| 3 | `c-3-recover-cleanup-honest` | M | `core/gate_orchestrator.py` | MED-HIGH | HIGH |

Total: 3 of 5 fix-now slots used. No expansion permitted without a
separate amending commit to this file.
