# Dashboard Page Overrides

> **PROJECT:** ClashDoctor
> **Page Type:** Single-page organizer dashboard (data-dense)

> **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Composition

The single dashboard page follows the Master layout exactly:

1. **Masthead** — 3px top rule, "ClashDoctor" (Bodoni, italic "Doctor"), festival name + slot range in mono meta, mode stamp right, 1px rule below.
2. **Workflow strip** — five mono numbered steps (Lineup → Schedule → Clashes → Optimize → Similarity) as anchor links.
3. **01 — The Schedule** — dominant, full width. When an analysis exists and has not been applied: render **draft and proposed grids side by side** (stacked <1120px), each with a header label ("DRAFT — current" / "PROPOSED — N moves"). Moved acts in the proposed grid get an accent left-edge mark. When applied: single grid labelled "APPLIED".
4. **02 — Clash Report + 03 — Optimize** — two-column zone (2fr / 1fr); optimizer panel is a surface-filled data well with a hairline border, `position: sticky; top: 16px` on desktop only.
5. **04 — Similarity Evidence** — full-width heatmap.
6. **05 — Lineup** — full-width dense editor table (not cards).

### Overrides

- **Max Width:** 1400px
- **Content Density:** High — Master density 8 tokens apply; lineup rows 36px tall; grid cells compact.
- **Clash pairs in heatmap:** add a 2px ink ring (from the Optimize analysis clash list) — the only heatmap decoration.
- **Heatmap scroll affordance:** the grid is wider than any laptop, so `.hm-corner` and `.hm-row-label` are `position: sticky; left: 0` on the paper background (`z-index: 2`). Without it the artist a row belongs to scrolls out of view exactly when the interesting cells scroll in.
- **Heatmap absences are not zeros:** a cell with no pair entry, a `missing` pair, or a null score renders "–" with the title "no comparable taste data" and never dereferences a score. Only scored cells carry `role="img"` and the estimated-similarity label.
- **Clash report wording:** rows print stage and slot **names** ("Main Stage @ 19:00"), falling back to the id only when an act references a stage the lineup no longer has — the optimizer answers in ids, the report must read like the grid on screen. Its percentage keeps a two-line title stating that it is the 0–1 blend rescaled to 100 and not a measured audience-overlap share.
- **Before/after framing:** draft uses paper background, proposed uses a `--good-tint` wash on the grid well header only (never the cells) to distinguish states without changing data colors.
- **Sticky:** only the Optimize panel sticks on desktop; masthead does not stick (preserves the broadsheet feel). Because the panel grows with every proposed move, at ≥1121px it also gets `max-height: calc(100vh - 32px)` with `overflow-y: auto` so a pinned panel can never hold its own Apply button off-screen. It is a `role="region"` with an accessible label and `tabindex="0"`, so keyboard users can scroll it.
- **Optimizer priorities:** a `--surface-2` well with a hairline border inside the panel (controls sit on `--surface`, so they read as raised). Presets are rectangular `btn-small` buttons (`aria-pressed`); the committed one takes the accent tint + accent border + `--accent-hover` text — never a pill, never a filled accent block. Sliders are native `input[type=range]` with a 6px surface track, 1px ink border and a 12×18px vermillion thumb (2px radius); the value sits in a mono `<output>`. Values commit on release/blur, not on every input event, and until then the panel says the figures above are still the previous plan.
- **Objective table:** `table-layout: fixed`, ink rules above the header and below the last row, hairline rules between rows, mono tabular numerals right-aligned. Only cells the proposal changes get the accent tint + 2px accent left edge — a weighting choice must never recolor the whole table.
- **Planning brief (top of 04 Optimize):** a `--surface` well with a `--rule-strong` hairline border and `--radius`, sitting above the priority controls, not a new section and not a chat panel. The instruction field reuses `.import-label` + `.import-textarea` (2 rows, `maxLength` 2000) and the examples reuse `.preset-row` + `btn btn-small preset`, so a free-text request reads like the import workflow an organizer already knows. Interpretation appears in a `.plan-result` block separated by a top hairline: summary paragraph in `--text-body`, one `--surface-2` item per interpreted priority with the value in mono, the unit in `--ink-3`, and the quoted phrase in `--font-mono` with `overflow-wrap: anywhere` — the quotation is the evidence, so it never gets truncated with an ellipsis. Stamps classify provenance only: `stamp-fixed` for a phrase rule, `stamp-data` for a model value the backend re-checked, `stamp-warn` for a question. Unsupported requests use the `--warn-tint` item with a warn border and the reason plus "Instead:" in `--ink-2`; nothing about them is styled as an error, because declining politely is not a failure. Hard-constraint and lock lines are one `.panel-note` sentence each, and an already-fixed act is named once, not repeated as two facts. The backend's provenance line (`llm_note`) renders under the summary as a `.panel-note`, and takes `warn` styling when `llm_ok` is false: the header stamp only says whether a provider is *configured*, which is not the same as whether it produced *this* plan, so a model failure must be visible in the result itself rather than implied by a stamp colour.
- **Interpretation vs measurement:** the run control is a `btn-small btn-primary` beside a `role="status"` line that is always explicit — "Not measured yet: the objective table below still shows an earlier run." until the optimizer has actually run with those priorities, then "Measured — the table below is this plan. Applying it stays your decision." or "Measured and applied — the grid above is this plan." The planner never renders an Apply control.
- **Conflict stamps:** hard blocks (`both_fixed`, `no_legal_cell`) use `stamp-clash`; soft ones (`worse_objective`, `move_limit`, `local_optimum`) use `stamp-warn`. Objective and priority figures use `stamp-data` (`--data` on `--data-tint`).
- **Validation failure:** a `role="alert"` note in clash tint with a 3px clash left edge; Apply stays disabled and the schedule is untouched.

### Empty / missing states

- No analysis (empty lineup): schedule grid well shows mono "Add artists to build the schedule."
- Missing profiles: hatch + "–" in heatmap; "missing profile" stamp in lineup; excluded pairs listed verbatim in the clash report.

### Component Overrides

- Avoid: Leave UI frozen with no feedback (every analysis shows "Re-analyzing…" while running)
- Avoid: Make dragging the only way to reorder — all schedule edits are select-based

---

## Page-Specific Components

- Workflow strip (numbered anchor nav, mono labels)
- Planning brief well (free-text instruction, quoted evidence, measured/not-measured status)
- Draft/Proposed grid comparison headers
- Heatmap clash rings

---

## Recommendations

- Effects: Row highlighting on hover in lineup and grid (tint only, no transforms)
- Animation: Spinner for loading, none for data entry
- Accessibility: All controls are native buttons/selects/inputs with visible focus; heatmap values are real text
