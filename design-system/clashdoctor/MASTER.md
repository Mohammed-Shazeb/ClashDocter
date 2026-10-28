# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** ClashDoctor
**Updated:** 2026-10-16
**Direction:** "Editorial Festival Broadsheet" — an editorial music-publication aesthetic fused with a dense, Swiss-style scheduling console.
**Design Dials:** Variance 5/10 (Balanced / Modern) | Motion 2/10 (Subtle) | Density 8/10 (Dense / Dashboard)

## Research provenance

- Design-system search → **Minimalism & Swiss Style** (base: grid discipline, high contrast, low ornament).
- Style search → **editorial-grid-magazine** (masthead rules, print-inspired hierarchy, hairline dividers, section numbering).
- Typography search → **Magazine Style pairing (Libre Bodoni + Public Sans)** extended with **JetBrains Mono** for data labels (times, scores, stage ids) — the "triple stack" pattern from the Monochrome Editorial pairing.
- Color search → music palettes that avoid the purple-AI cliché point to **warm paper + deep red**; combined with Swiss black/white + one accent.
- Chart guidance → heatmaps must **print values in cells**, include a **numeric legend**, and not rely on color alone; single-hue severity ramps over red-green axes for CVD safety.

---

## Global Rules

### Visual identity

ClashDoctor should look like a festival program sheet produced by a serious operations desk: warm newsprint paper, ink-black type, a vermillion accent, numbered sections separated by hairlines — not a stack of rounded cards. Every element communicates information, supports an action, or improves usability.

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Paper (background) | `#F6F3EC` | `--paper` |
| Surface (raised panels) | `#FDFCF8` | `--surface` |
| Surface 2 (inset data wells) | `#EFEBE1` | `--surface-2` |
| Ink (foreground) | `#1B1712` | `--ink` |
| Ink secondary | `#5C5448` | `--ink-2` |
| Ink muted (≥4.5:1) | `#6E6557` | `--ink-3` |
| Hairline (rule) | `#D8D1C2` | `--rule` |
| Strong rule | `#1B1712` | `--rule-strong` |
| Accent (vermillion, actions/CTAs) | `#C2410C` | `--accent` |
| Accent hover | `#9A3412` | `--accent-hover` |
| Clash red | `#B42318` | `--clash` |
| Clash tint | `#FBEAE7` | `--clash-tint` |
| Improved green | `#2E6E4E` | `--good` |
| Good tint | `#E7F1EB` | `--good-tint` |
| Warning amber | `#92600A` | `--warn` |
| Warn tint | `#F7EED9` | `--warn-tint` |
| Data blue (stage labels, secondary data) | `#35577D` | `--data` |
| Focus ring | `#1B1712` | `--ring` |

**Color Notes:**
- One accent only (vermillion). No purple/pink gradients, no glassmorphism, no glow.
- Text on paper/surface must meet 4.5:1 (`--ink-2` ≈ 7:1, `--ink-3` ≈ 5.4:1).
- White text on `--accent` ≈ 6.9:1, on `--clash` ≈ 7.6:1, on `--good` ≈ 5.6:1.
- Heatmap ramp (single hue, warm): `#F1ECE0` (0) → `#E8B48C` (0.25) → `#C2410C` (0.5) → `#7C2D12` (1). Values are always printed in cells — color is reinforcement, never the only signal.
- Missing data: diagonal hatch texture + "–", never a heat color.

### Typography

- **Display (masthead, section titles):** Libre Bodoni — 500/600, tight leading. Editorial masthead authority. Sizes ≥ 18px only.
- **UI sans (body, controls, tables):** Public Sans — 400/500/600.
- **Data mono (times, slot ids, scores, stamps):** JetBrains Mono — 400/500, uppercase for stamps/labels with letter-spacing 0.06em.

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Libre+Bodoni:ital,wght@0,500;0,600;1,500&family=Public+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
```

**Scale (density 8):**

| Token | Size / Line | Usage |
|-------|-------------|-------|
| `--text-masthead` | 30px / 1.05 | App title |
| `--text-title` | 20px / 1.2 | Section titles (Bodoni 600) |
| `--text-body` | 13.5px / 1.5 | Body, table text |
| `--text-data` | 12.5px / 1.4 | Grid cells, chips, rows |
| `--text-label` | 11px / 1.3 | Mono labels, stamps, legends |

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | Tight gaps |
| `--space-sm` | `8px` | Icon gaps, inline spacing |
| `--space-md` | `12px` | Standard padding |
| `--space-lg` | `16px` | Component padding |
| `--space-xl` | `24px` | Between components in a section |
| `--space-2xl` | `32px` | Section padding |
| `--space-3xl` | `48px` | Between sections |

### Shape & Elevation

- Radius: `2px` for buttons/inputs/stamps; `0` for panels and data wells. Print, not plastic.
- No drop shadows. Depth = hairlines and the strong masthead rules only.
- Borders: `1px solid var(--rule)` standard; `1px solid var(--rule-strong)` for emphasis; dashed for locked/fixed states.

---

## Component Specs

### Sections (NOT cards)

Sections are separated by `1px` rules with a numbered editorial header:

```
01 — The Schedule
```

- Header: mono index + Bodoni title on one baseline; fine rule underneath.
- No card backgrounds, no rounded containers wrapping sections. Only data wells (search box, optimizer panel, score boxes) get a surface fill + hairline border.
- The schedule grid is the dominant element of the page (full width, first content section).

### Masthead

- Top: `3px` strong ink rule. Below: "ClashDoctor" in Bodoni 600 30px ("Doctor" italic), festival name + date in mono meta line, mode stamp top-right.
- Bottom: `1px` strong rule. No gradients, no logos, no decorative shapes.

### Buttons

- Square corners (2px radius), 1px borders, uppercase mono labels for small actions.
- **Primary action (Apply optimized schedule):** filled `--accent`, white text.
- **Secondary (Search, Reset):** transparent, ink text, `--rule-strong` border.
- **Danger (Remove):** transparent, `--clash` text/border.
- Hover: background tint shift only (no translate/scale — no layout shifts).
- Focus-visible: `2px solid var(--ring)` outline, `2px` offset.
- Disabled: reduced opacity + `not-allowed`; never remove the border.

### Stamps (replaces pill badges)

Flat 2px-corner chips: mono 10.5px uppercase, letter-spacing 0.06em, 1px border, tinted background. Used only where they carry information: mode (DEMO/LIVE), profile source, FIXED, missing profile, scoring method, move deltas. No pills, no rounded-full badges, no decorative tags.
- Accent stamps (`--accent-tint` bg, `--accent` border): text must be `--accent-hover` `#9A3412` — `--accent` `#C2410C` on the tint is 4.48:1 and fails WCAG AA.

### Tables & Data Wells

- Schedule grid: hairline cell borders; header row mono labels; act chips = surface fill + ink text; clash cells = `--clash-tint` background + `--clash` chip border; fixed acts = dashed border + "locked" mono note; empty cells stay paper.
- Lineup: dense rows with alternating none (use hairlines instead of zebra), select/inputs 1px bordered, 30px control height.
- Focus-visible on every interactive cell/control.

### Heatmap

- Single-hue warm ramp (see palette). Cell text: `genre/combined` values in mono 9.5px.
- Cells: `minmax(54px, 1fr)` columns (a 9.5px mono `0.50/0.42` pair is ~51px wide — anything smaller clips the printed values); heatmap well keeps `min-width: 1280px` for 20 acts and scrolls horizontally below desktop.
- Self cells: surface-2 fill. Missing cells: diagonal hatch + "–".
- Clash pairs: `2px` ink outline ring around cells (ties heatmap to the schedule).
- Legend: numeric gradient swatches + band labels Low / Med / High, plus hatch swatch for "no data".
- Values printed in cells = the non-color encoding (a11y).

### States

- **Loading:** paper background, mono label "Loading festival data…" + simple spinner; respects reduced-motion (static).
- **Error:** clash-tint panel, ink border, mono error code, message, Retry button.
- **Empty:** centered mono label with hairline rule above, no illustrations.
- **No-results (search):** mono "No artists found for query."

---

## Layout

Desktop (≥1120px):

```
┌─ Masthead (rule / title / meta / mode stamp / rule) ────────┐
│ Workflow strip: 1 Lineup · 2 Schedule · 3 Clashes · 4 Optimize · 5 Similarity │
│ 01 — The Schedule        (full width, dominant; draft vs proposed compare)   │
│ 02 — Clash Report (2fr)  │  03 — Optimize (1fr, sticky)      │
│ 04 — Similarity Evidence (full width heatmap)               │
│ 05 — Lineup (full width, dense editor)                      │
└─ Footer rule + disclaimer (mono, small) ────────────────────┘
```

- Page gutters: 24px → 32px at ≥768px → 48px at ≥1440px. Max content width 1400px.
- Tablet (<1120px): clash report + optimizer stack.
- Mobile (<720px): single column; schedule grid and heatmap keep `min-width` and scroll horizontally inside their wells; workflow strip collapses to compact labels; selects/inputs full-width rows.

---

## Motion

- Subtle only: 150–250ms color/border/opacity transitions on interactive elements.
- No entrance animations for data, no parallax, no decorative motion.
- `@media (prefers-reduced-motion: reduce)` disables all transitions/animations.

---

## Anti-Patterns (Do NOT Use)

- ❌ Purple/pink gradients anywhere (current header gradient must go)
- ❌ Glassmorphism, backdrop blur, glowing borders, decorative blobs
- ❌ Rounded cards nested inside rounded cards; dashboards made of identical cards
- ❌ Giant marketing headings or copy in the workspace
- ❌ Emoji as icons — vector icons only (Phosphor, outline style, 1.5px stroke)
- ❌ Pill badges, excessive badges, labels that repeat adjacent text
- ❌ Fake charts, fabricated metrics, invented audience-overlap statistics
- ❌ Layout-shifting hover transforms (translate/scale on hover)
- ❌ Color as the only data signal (heatmap prints values)
- ❌ Instant state changes without transitions; invisible focus states

---

## Pre-Delivery Checklist

- [ ] No emojis as icons; icons from one consistent set (Phosphor outline)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states 150–300ms, no layout shifts
- [ ] Text contrast ≥ 4.5:1 on paper/surfaces (verified values in palette)
- [ ] Visible focus states for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px — no content hidden, no broken overflow
- [ ] Sticky elements do not obscure content or focus
- [ ] Loading / error / empty / no-results states present and factual
