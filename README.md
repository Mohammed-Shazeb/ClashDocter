# ClashDoctor

ClashDoctor helps music festival organizers reduce scheduling conflicts between
artists likely to appeal to similar audiences. It uses **Qloo tag similarity as a
proxy for taste affinity** — an *estimate*, never a claim of verified audience
overlap, shared-fan percentages, or attendance forecasts.

Built for the Qloo Agentic Hackathon — "Agents, but with taste."

## Features

- **Real lineup import** — drop in a CSV file or paste a schedule (tab/comma/
  semicolon/pipe separated, spaced-dash or `@` separated free text, with or
  without a header row). The parser builds stages from the stage names and time
  slots from the distinct start–end pairs it finds, then validates artist names,
  set durations against slot length, double bookings, and same-stage overlaps.
  Every problem is reported per row with a severity; rows that cannot be placed
  are rejected and counted, never silently dropped
- **Real artist search** — search Qloo's artist catalog from the UI, pick from
  ranked candidates, and add real artists to the lineup. Ambiguous names are
  flagged and never auto-selected: the backend returns no `best_match`, and the
  row waits for an explicit Add on the candidate you meant
- **Confirmed artist matching** — imported names are resolved through the same
  Qloo `/search` integration in bounded concurrent batches (cached per name).
  An ambiguous name is returned with its candidates and **must be chosen by the
  user**; a name with no confirmed match keeps a local placeholder id and is
  reported as missing data rather than guessed
- **Live taste-similarity analysis** — taste tags fetched per artist from Qloo
  `/v2/insights` (with search-result tags as a fallback), cached for an hour;
  genre ids from every provider namespace are normalized to one canonical
  `urn:tag:genre:music:*` id before comparison, while the raw ids stay on the
  profile as provenance. Distinct labels (`folk` vs `indie_folk`) are never
  merged. Artists with no usable tags are reported as **missing data**, never
  zero similarity; partial API failures surface per-artist warnings
- **Dynamic festival lineup** — add/remove artists, stages, and time slots;
  acts on removed cells are re-placed automatically into free cells; a usable
  initial schedule is generated from your lineup while respecting the
  optimizer's hard constraints (fixed acts never move, over-capacity is an
  explicit error)
- Stage-versus-time-slot schedule grid with clash highlighting
- Pairwise **estimated taste similarity** heatmap: a documented multi-signal
  blend of per-category Jaccard scores, computed only over the tag categories
  both artists actually have (the genre-only and pooled-combined Jaccards are
  still reported alongside it as references)
- **Evidence panel** — data coverage per category, the strongest affinities with
  the tag-level arithmetic that produced each score, which categories were
  skipped for lack of data, and low-confidence stars on thin evidence. Every
  pair also states whether both sides had genre data (`genre-backed` or
  `no genre comparison`), how many shared tags are generic versus specific to
  this lineup, what share of the shared tags are generic, and which profile
  source each side came from
- Clash summary listing high-similarity acts performing simultaneously, each with
  the contributing signals and shared tags behind its score, plus the same
  genre-backed, generic-share and profile-source evidence
- **Constraint-aware schedule optimizer** (steepest-descent local search over
  relocations and swaps) with priorities you set: how much high-affinity pairs
  count, what moving one act costs, and how many changes are allowed
- Before-and-after measurement of the **same** objective, with the raw clash sum
  reported beside the weighted one, an explanation and both cost figures for
  every proposed move, the full list of acts that move, and the conflicts that
  survive with the reason why
- **Brief the optimizer in plain English** — "Keep both headliners fixed and
  reduce high-affinity clashes" comes back as the exact priorities it read, each
  one quoted from your own sentence, plus the acts it would lock and a plain
  statement of anything the optimizer cannot do. Interpretation and measurement
  stay visibly separate: the brief never touches the schedule, running it goes
  through the same `/api/optimize` call, and Apply stays a human decision
- Every proposal is validated against the hard constraints before it can be
  applied, and the frontend re-checks it before writing it to the schedule
- **Explicit demo/live modes** — without a key the app runs on a clearly
  labelled seeded demo dataset and the UI says so; with `QLOO_API_KEY` set, the
  banner switches to live mode and real Qloo data flows through search,
  similarity, clash analysis, and optimization

## Disclaimer (read me)

- Similarity scores are **estimated taste similarity** computed from tag overlap
  (Jaccard). They are not verified audience-overlap data, shared-fan
  percentages, or attendance forecasts.
- Artists with missing or low-quality Qloo profiles are **excluded** from scoring
  and reported as missing — never scored as zero similarity. The same rule
  applies per category: a dimension Qloo returned for only one artist is skipped
  and its weight renormalized, so absent data never registers as disagreement.
- Genre ids are normalized **by provider namespace only** — `urn:tag:genre:`,
  `urn:tag:genre:qloo:` and `urn:tag:genre:music:` forms of the same slug are
  compared as one genre. Raw ids remain on the profile, and different labels
  (`folk` vs `indie_folk`) are never merged. A namespace mismatch is a bug in
  the comparison, not evidence that two artists differ.
- A score and its **confidence** are separate. A positive score built on a
  single shared tag, or whose shared tags are all generic in the lineup, is
  labelled low confidence; the numeric estimate is unchanged. Generic is
  lineup-local: a tag carried by at least a quarter of the tagged acts (minimum
  3 carriers and 6 tagged acts) marks a broad category, not a specific
  affinity. The stricter 50%-of-lineup "broad" annotation is still reported
  separately. These are evidence thresholds, not a fitted reliability model.
- The optimizer compares the initial and optimized schedules using the **same
  objective and the same hard constraints**. It only reports improvement when the
  score actually decreased. Fixed (locked) acts never move. Pairs with no
  comparable tag category are excluded from the objective and reported as
  missing data rather than counted as cost 0.
- The optimizer acts on the lineup **you** built in the UI — it never silently
  falls back to the seeded lineup.
- Imported artist names are **never invented**. Names that the user has not
  confirmed against a Qloo entity carry a local `unmatched:<act id>` placeholder
  (never sent to the API), are excluded from scoring, and appear as missing-data
  warnings. Similarity is only ever computed from tags Qloo actually returned.

## Data provenance

Every value in the app can be traced to one of four sources, and the UI labels
which one is in play:

| Source | Label in the UI | What it means |
|--------|-----------------|---------------|
| `demo` | `DEMO MODE` / mode `demo` | Seeded fictional artists with hand-written tag sets. No API key needed; clearly marked so nobody mistakes it for real data. |
| `qloo-insights` | mode `live` | Taste tags returned by Qloo `/v2/insights` for a confirmed entity id. Primary source. |
| `qloo-search` | mode `live`, per-artist note | Tags embedded in Qloo `/search` results, used only when `/v2/insights` yields nothing relevant. Still real Qloo data; the note says which fallback was used. |
| `unmatched` | mode `unmatched`, `no profile` stamp | Imported name with no confirmed Qloo entity, or an entity whose profiles are empty / whose fetch failed. **Absence of data, never zero similarity.** |

A lineup that mixes live and unmatched acts is still reported as `live` (with
missing-data warnings): "unmatched" describes missing data, not a data source.
A lineup that mixes demo and live acts is reported as `mixed`.

Genre canonicalization changes the namespace a tag is compared under, never its
label or source. `/api/profiles` returns both raw `genre_tags` and
`canonical_genre_tags`; the probe records raw `tags` and canonical
`canonical_tags` per category.

Cached values (search records, profiles, name resolutions) live in an
in-process TTL cache with a 1-hour lifetime and are cleared when the server
restarts. Nothing is written to disk or a database.

## Stack

| Layer     | Tech |
|-----------|------|
| Frontend  | React 18 + Vite 6 (JavaScript), plain CSS |
| Backend   | Python 3, FastAPI, HTTPX, Pydantic v2 |
| Storage   | In-memory TTL cache (no Redis/DB/Docker) |
| Optimizer | Greedy steepest-descent local search (no OR-Tools) |

## Architecture

The frontend is a thin view: it never calls Qloo and never sees the API key.
All Qloo traffic, validation and scoring happens in FastAPI.

```
paste/CSV text
      │
      ▼  POST /api/import/parse          (offline, deterministic)
 stages + slots + acts + issues
      │
      ▼  POST /api/import/resolve        (Qloo /search, cached, ≤4 concurrent)
 candidates → user confirms ambiguous names → entity ids
      │
      ▼  POST /api/schedule/assign       (re-validates hard constraints)
 placed lineup
      │
      ├─▶ POST /api/profiles             (Qloo /v2/insights → search-tag fallback)
      ├─▶ POST /api/similarity           (pairwise estimated taste similarity)
      ├─▶ POST /api/plan/interpret       (plain-English brief → validated
      │                 │                  priorities + locks, nothing executed)
      └─▶ POST /api/optimize             (measures the objective under your
                │                         priorities + constraint-preserving moves)
                ▼  POST /api/schedule/validate  (re-checked before it is written back)
           applied lineup
```

`unmatched:<act id>` placeholders and `demo:` ids are short-circuited inside the
backend (`app/main.py`) and are never sent to Qloo.

`/api/plan/interpret` never returns a schedule. It returns the priorities it read
out of your sentence, the acts it would lock, and everything it could not do — the
existing `/api/optimize` call is still the only thing that measures numbers, and
Apply is still the only thing that writes them back.

## Project structure

```
backend/
  app/
    main.py         # FastAPI app + endpoints
    config.py       # env configuration (QLOO_API_KEY etc.)
    models.py       # Pydantic request/response models
    qloo.py         # Qloo search + insights client, genre-namespace
                    # canonicalization, tag filtering, caching, rate-limit
                    # retry (429)
    importer.py     # CSV / pasted-text lineup parser + validation (offline,
                    # deterministic, no Qloo calls)
    similarity.py   # per-category Jaccard + weighted taste blend, explanations,
                    # evidence/confidence rules, coverage statistics
    optimizer.py    # clash objective + user priorities, constraint-preserving
                    # local search, schedule validation, initial-schedule assignment
    planner.py      # plain-English brief → validated priorities and locks:
                    # documented phrase rules, optional OpenAI-compatible JSON
                    # extraction, schema/range/lineup validation, unsupported list
    cache.py        # thread-safe in-memory TTL cache
    demo_data.py    # seeded demo festival + demo profiles + festival template
  probe/            # standalone Qloo coverage/taste-signal validation probe
    dataset.json    # 50 documented artists + editorial expected pairs
    fixtures/       # synthetic Qloo-shaped payloads for offline mock mode
    core.py         # resolve → profile → score → coverage → evidence diagnostics
    report.py       # JSON + Markdown + CSV artifacts
    run.py          # python -m probe.run [--live]
  tests/            # unit tests (mocked Qloo, run offline)
  .env.example
  requirements.txt
frontend/
  src/
    components/     # ImportPanel (CSV/paste import + artist matching review),
                    # LineupEditor (artist search with explicit ambiguity
                    # confirmation + structure editor),
                    # StructureEditor, ScheduleGrid, SimilarityHeatmap,
                    # PairEvidence (coverage, evidence confidence + score
                    # breakdowns), ClashSummary,
                    # PlanningPanel (brief in plain English → interpreted priorities,
                    # quoted evidence, unsupported requests, run-on-approval),
                    # OptimizePanel (priorities, measured objective, moves,
                    # unresolved conflicts, validation gate), ModeBanner
    tagLabels.js    # renders Qloo urn:tag:* ids as readable labels
    signalMath.js   # the one "jaccard × weight = +contribution" format used by
                    # the heatmap, evidence panel and clash rows
    services/api.js # backend API client
    test/           # vitest + Testing Library tests (mocked API client)
    pages/          # (reserved; single-page dashboard lives in App.jsx)
    App.jsx
    main.jsx
design-system/
  clashdoctor/
    MASTER.md           # design system source of truth ("Editorial Festival
                        # Broadsheet": paper/ink/vermillion, Bodoni + Public
                        # Sans + JetBrains Mono, tokens, component specs)
    pages/dashboard.md  # dashboard page rules (layout, compare view, states)
```

## Setup

### 1. Backend

```bash
cd backend
py -m venv .venv                       # Windows; use python3 on macOS/Linux
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip
```

Create `.env` from the example (place it in `backend/.env` — it is git-ignored):

```bash
cp .env.example .env
```

For live Qloo data, put a valid key in `backend/.env`:

```
QLOO_API_KEY=your_key_here
```

**Without a key the app still runs** on the seeded demo dataset and labels
itself "DEMO MODE". Live Qloo endpoints return a clear configuration error
until the key is added.

The plain-English planner works **without** any language model: it reads your
brief with a documented table of phrase rules. If you want it to also catch
priorities that table misses, point it at any OpenAI-compatible JSON endpoint:

```
PLANNER_API_KEY=your_key_here      # required to enable the model path
PLANNER_MODEL=your_model_name      # required to enable the model path
PLANNER_BASE_URL=https://api.openai.com/v1   # optional, defaults to OpenAI
PLANNER_TIMEOUT_SECONDS=20         # optional
```

Both keys must be set or the model path stays off, and `/health` plus the panel
stamp say which mode is in use. The model only ever proposes a number or the name
of an act already in your lineup; the backend validates every value against the
same ranges the sliders use, phrase rules win any field they matched, and a
provider error falls back to the rules with the failure reported. No key leaves
the backend.

Start the server:

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000     # macOS/Linux: .venv/bin/python
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # serves http://localhost:5173, proxies /api → :8000
```

Open http://localhost:5173. The dashboard loads the seeded demo festival
automatically and labels itself "Demo mode — no API key". If the backend has a
Qloo key, the banner switches to live mode and you can search real artists,
build a lineup, and optimize against live tag data.

### 3. Tests

```bash
cd backend
.venv/Scripts/python -m pytest     # macOS/Linux: .venv/bin/python -m pytest

cd ../frontend
npm test                          # vitest + Testing Library (jsdom)
```

All tests mock Qloo responses — they run offline with no API key and never
make live API calls. Frontend tests mock the API client module. The app-level
live checks are listed under *Live integration smoke tests*; the standalone
probe below did complete live Qloo requests on 2026-10-23, but that checklist
itself has not been run.

Current status (last run on this machine, 2026-10-23): **276 backend tests
passed (32 of them the probe's offline suite), 115 frontend tests passed**,
`npm run build` clean. Backend suites cover
import parsing and validation (`test_importer.py`), artist resolution — dedupe,
caching, per-name failure, rate-limit retry, and ambiguous names producing no
selected entity (`test_qloo.py`, `test_api.py`), missing-data handling and the
multi-signal blend: renormalization, skipped categories, cross-namespace genre
canonicalization without merging distinct labels, single-shared-tag,
all-generic-tag and all-broad-tag confidence, generic-versus-broad detection,
generic/specific shared-tag counts, no misclassification of a rare specific
genre, missing-genre generic evidence, genre-backed coverage counts, coverage
arithmetic, and a varied real-world lineup used to check the ordering is
meaningful (`test_similarity.py`, `test_api.py`), and the optimizer: constraint
preservation including the fixed-headliner clash, the objective definition,
excluded-pair reasons, how each preference changes the verdict (weighting flips
which clash is fixed first, a move penalty can price a fix out, a move cap stops
the search and says so), churn accounting for swaps, clamping of out-of-range
preferences, unresolved-conflict reporting, and standalone schedule validation
(`test_optimizer.py`, `test_api.py`), and the planner: the range table mirrored
against the preference model, every shipped example interpreted without a
question, explicit numbers beating presets, out-of-range clamping disclosed,
contradictory priorities and vague counts turned into questions, unsupported
requests (stage weights, genres, durations, lineup edits, ticket data, "shared-fan
percentage") never smuggled in as a quiet preference, lock phrases resolved only
against real lineup names while blanket quantifiers lock nobody, the model reply
validated field by field with rules winning any field they matched, provider
failures degrading to the documented rules with `llm_ok: false`, 401/403/429/500
mapped without echoing the key, a plan carrying no acts/stages/slots keys at all,
and a round trip through the real optimizer that re-checks fixed acts never move,
`improved` only when the measured objective strictly drops, and the proposal still
passes `/api/schedule/validate` (`test_planner.py`), plus the standalone Qloo
validation probe: dataset validation, resolution states, search-tag fallback,
canonical genre ids preserved alongside raw ids, missing-profile pair exclusion,
category-skip renormalization, evidence fields and limitations, coverage
arithmetic including genre-backed and single-shared-tag counts, percentiles,
zero-inflated verdict qualification, generic-tag flags, timeout/500/non-JSON
provider failures, 401 aborts with key redaction, and mock/live report artifacts
(`test_probe.py`). Frontend suites cover the import panel flow
(`ImportPanel.test.jsx`), artist search and lineup editing including the
explicit choice required for ambiguous results (`LineupEditor.test.jsx`), the
demo/live mode banner (`ModeBanner.test.jsx`), the clash rows and their signal
breakdown (`ClashSummary.test.jsx`), the coverage and evidence panel — including
genre-backed versus no-genre comparisons, generic/specific shared-tag counts,
generic share, profile sources and limitations (`PairEvidence.test.jsx`), the
optimizer panel — measured
objective, raw-vs-weighted rows, presets, slider commit-on-release, move
explanations, unresolved conflicts, Apply gating on validation, and empty /
loading / applied states (`OptimizePanel.test.jsx`), the planning brief — typed
instruction reaches the interpreter, quoted evidence per priority, the
measured/not-measured distinction, hard-constraint and lock lines including the
already-locked dedupe, unsupported and clarification rendering, the
needs-approval note, the provenance line that separates a model that answered
from a configured model that failed and fell back to the rules, and the fact that
the panel offers no Apply control of its own
(`PlanningPanel.test.jsx`), the heatmap — a text alternative per cell, missing
data never drawn as zero, and a matrix entry that is absent altogether (`SimilarityHeatmap.test.jsx`),
the whole-app wiring — the clash count always describes the schedule on screen,
Apply re-arms after a brief, an edited act drops a previewed plan, and a stale
similarity matrix cannot overwrite a newer one (`App.test.jsx`), Qloo tag-label cleanup
(`tagLabels.test.js`) and the API client (`api.test.js`).

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Status + whether Qloo is configured, plus `planner_configured` and the `planner_mode` the UI stamps |
| `/api/demo/festival` | GET | Seeded demo festival (fictional artists) |
| `/api/festival/template` | GET | Empty live template (3 stages, 6 slots, no acts) |
| `/api/artists/search` | POST | Search Qloo, returns ranked, disambiguated candidates |
| `/api/import/parse` | POST | Parse + validate CSV or pasted schedule text (offline, no Qloo calls) |
| `/api/import/resolve` | POST | Resolve imported artist names to Qloo entities; ambiguous names come back with candidates for confirmation |
| `/api/profiles` | POST | Fetch structured taste tags per artist (cached) |
| `/api/similarity` | POST | Pairwise taste-blend matrix with per-pair signal explanations, evidence/confidence fields, reference scores, `coverage` stats and partial-failure warnings |
| `/api/plan/interpret` | POST | Turn a plain-English brief into validated priorities, the acts it would lock, quoted evidence, an unsupported list and questions — returns no schedule and applies nothing |
| `/api/optimize` | POST | Clash analysis + optimized schedule + move explanations under your `preferences`; measures the objective before and after, validates the proposal, and reports what it could not resolve |
| `/api/schedule/validate` | POST | Check a schedule against every hard constraint without moving or scoring anything; returns all issues at once |
| `/api/schedule/assign` | POST | Place a lineup on stages/slots; re-places displaced acts, errors on over-capacity |

Rate limiting: on HTTP 429 the Qloo client retries once, honoring `Retry-After`
(capped at 2s), then reports a clear error.

Failure handling, per layer:

- **Transport / timeout / non-2xx / non-JSON** → `QlooUpstreamError` with a
  message that names the endpoint. A batch resolve reports it per name
  (`status: "error"`) so one failure never voids the rest; `/api/profiles`
  degrades that artist to a missing profile with the reason in `note`.
- **Missing key** → `/health` says `qloo_configured: false`, the UI stays in
  demo mode, and any live endpoint returns HTTP 503 `QLOO_NOT_CONFIGURED`
  instead of inventing data.
- **Empty or irrelevant tags** → profile `missing: true`. Every pair involving it
  stays in the matrix with `taste_similarity: null` and a `missing_reason`, and
  simultaneous pairs are listed in `/api/optimize`'s `excluded_pairs` instead of
  contributing 0 to the objective.

## Import formats

`/api/import/parse` accepts any of these shapes (all columns except artist,
stage and set time are optional):

```csv
# name: Sample Festival
artist,stage,start,end,duration_min,fixed
Radiohead,Main Stage,19:00,20:00,60,yes
Slowdive,Tent,20:00,21:00,45,no
```

```text
Radiohead, Main Stage, 19:00-20:00, 60min
Slowdive — Tent — 20:00–21:00 (45 min)
Big Wolf (Building)    Tent    21:00    22:00
```

- Delimiters detected per file: `,` `;` `|` tab, or free text split on double
  spaces / spaced dashes / `@`.
- Header aliases: `artist|name|act|performer|band`, `stage|venue|tent|room`,
  `start|begin|from`, `end|finish|until`, `time|slot|set_time`,
  `duration|length|set_length|minutes`, `fixed|locked|headliner|pinned`.
- Times are 24h `HH:MM` (`24:00` allowed for closing sets); ranges may use
  `-`, `–`, `—`, `to` or `until`. Durations accept `60`, `60 min`, `1.5h`,
  `90 minutes`; an absent duration is assumed equal to the slot length and
  reported as an `info`.
- `# comment` lines are ignored; the first one names the festival.
- Limits: 200 KB of text, 500 rows, set lengths 15–480 minutes.

## Demo workflow

### No key — the eight-step demo (works out of the box)

Start both servers (see *Setup*), open `http://localhost:5173`, and keep the DevTools
network tab in view. Nothing below needs a credential, and every figure here was read
off this machine with no `QLOO_API_KEY` set. The seeded bill is **fictional**
(`demo:` entity ids, hand-written tag profiles) and the UI stamps it `DEMO MODE`:
these are not live Qloo results.

1. **Load the lineup.** The app boots straight into *Qloo Fest 2026* — 20 acts, 4
   stages, 6 slots. **02 The Schedule** header reads `12 clashes`: twelve pairs of
   artists play simultaneously on different stages.
2. **Review the matches and the taste signals.** In *Lineup*, nineteen rows carry a
   green `demo profile` stamp, the locked headliners carry `fixed`, and one row
   (*Enigma Collective*) shows amber `missing profile`. Under **05 Similarity
   Evidence**, *Data coverage* states `19/20 acts carry taste tags · 171/190 pairs
   comparable · 19 excluded`, and the *Partial data warnings* block repeats the
   missing artist. Missing here means *no evidence*, never *dissimilar*.
3. **Read the heatmap and the explanations.** The grid is 20 × 400 cells; the
   simultaneously-scheduled ones are ringed, and the row labels stay pinned while you
   scroll sideways. Hover any ringed cell — e.g. *Neon Cascade vs Pulse Machine —
   estimated taste similarity 0.458* followed by the tag arithmetic
   (`music genre 0.500 × 0.550 = +0.275 (dance, electronic)`). Each cell also carries
   that sentence as its accessible name, so the colour is never the only signal.
4. **Give a planning brief.** In **04 Optimize**, type
   `Keep both headliners fixed and reduce high-affinity clashes.` and press
   **Interpret**.
5. **See what was understood — and what was not.** The panel lists three interpreted
   priorities, each quoting the phrase it came from and stamped `phrase rule`:
   threshold `0.50`, weight `3.00×`, cost of moving `0.00`. Below:
   `Locked already: Aurora Lane, Skyline.` and the six always-enforced constraints.
   The mode stamp reads `phrase rules only (no PLANNER_API_KEY/PLANNER_MODEL)`. To
   show the honest refusal path, try `Reduce clashes but prioritise the main stage.`
   — it returns *"This backend cannot do that: prioritise the main stage — the
   objective has no per-stage weight"* with the nearest supported alternative. And
   `Give techno more room than house.` comes back with `interpreted: false` plus a
   question, because genre only enters through an act's tags.
6. **Run the real optimizer.** Press **Run with these priorities**. This is the same
   deterministic search the sliders drive — no second implementation, no seeded
   answer. Measured against the plan: raw clash sum `3.575 → 0.542`, weighted by
   priority `5.742 → 1.625`, simultaneous pairs `12 → 1`, high-affinity pairs
   `2 → 1`, acts moved `0 → 8` across 4 proposed moves, pairs without data `3 → 3`
   (unchanged — exclusions are not a saving). Running it twice returns byte-identical
   numbers.
7. **Read the objective, the moves and what is left.** *Proposed moves (4)* explains
   each move in a sentence; *Unresolved conflicts (1)* names *Aurora Lane · Skyline*
   at `similarity 0.542`, both fixed, with `1 clash(es) involve locked headliners and
   remain by design`. The status line says `Measured — the table below is this plan.
   Applying it stays your decision.`
8. **Apply, once, deliberately.** **Apply optimized schedule** first calls
   `/api/schedule/validate` (the button reads `Checking constraints…` and stays
   disabled, with the reason in its tooltip, if the proposal breaks a rule). On
   success the grid re-renders, the button becomes `Applied to schedule`, **03 Clash
   Report** is stamped `applied schedule`, and **02 The Schedule** now reads
   `1 clash` — the clash that actually remains on the accepted schedule, not the zero
   a further proposal might reach. Nothing applies itself: there is no auto-apply
   anywhere in the app.

To reset, use *Load demo festival*. To compare against a real file, *01 Import* →
*Load sample* → *Parse & preview* → *Build schedule*.

**With a key:**

1. *01 Import* → paste a schedule or choose a CSV → **Parse & preview**. Fix any
   blocking problems the validator reports (double bookings, sets that do not
   fit their slot) before building; the build button stays disabled while rows
   are rejected.
2. **Match artists on Qloo** — names are searched in batches. Green *matched*
   rows are confirmed automatically; amber *needs confirmation* rows show their
   candidates with disambiguation text and entity ids, and you pick one. Rows
   with no match are kept, flagged, and will be reported as missing data.
3. **Build schedule** — the lineup is placed on the stage/slot grid through
   `/api/schedule/assign`, which re-validates every hard constraint.
4. **03 Clash Report** lists simultaneous high-affinity acts with the signal
   breakdown that produced each score, and the excluded pairs with the reason
   they could not be compared. **04 Optimize** proposes constraint-preserving
   moves with a before/after objective and a reason per move. You can set the
   priorities with the sliders, or write them in one sentence in *Brief the
   optimizer in plain English* — **Interpret** shows what it read (with the phrase
   it read it from) before anything runs, **Run with these priorities** feeds the
   same optimizer, and the panel says plainly whether the table below is that
   measurement or an earlier one. The grid in **02
   The Schedule** shows the proposal side by side before you apply it. **05
   Similarity Evidence** shows data coverage per category and the strongest
   affinities with their contributing signals and shared tags — starred heatmap
   cells rest on thin evidence, and the tooltip shows the tag arithmetic.

To prove live mode without touching the real API, the local test suite mocks
Qloo entirely — see *Tests* below.

## Live integration smoke tests

**Neither checklist was executed here.** A temporary `QLOO_API_KEY` was used for
the standalone probe, which called Qloo's search and insights endpoints through
the production client (95/95 requests succeeded), but the app endpoints, browser
flow and product path below were not re-run against live data. No
`PLANNER_API_KEY` is configured, so the provider checklist is untested. Keys go
in `backend/.env` only: never in a chat message, an issue, a URL, a shell
history you share, or a screenshot. The probe key was pasted into a chat during
validation, so treat it as exposed and rotate it before any further use.

`config.py` reads the environment at import, so each change below needs a uvicorn
restart, and the three in-process caches restart with it.

### Qloo, with a rotated key

```
QLOO_API_KEY=<rotated key from the Qloo dashboard>
QLOO_BASE_URL=https://hackathon.api.qloo.com
QLOO_TIMEOUT_SECONDS=30
QLOO_INSIGHTS_TAKE=20
PROFILE_CACHE_TTL_SECONDS=3600
```

`QLOO_INSIGHTS_TAKE=20` is the production default; the saved probe artifact
(`probe/outputs/live/report.json`, `take=20`) measured it truncating profiles:
34 of 44 usable artists carried genre tags, and only 6 of 15 emerging artists
did. An earlier `take=50` run reported more genre-bearing profiles and
confidence-passing pairs, so the value materially changes coverage; that artifact
was later overwritten, so its figures are not reproducible from the files now
saved. The endpoint accepted 30 and 50 on 2026-10-23 and rejected 100 with HTTP
400, so do not assume a higher value will be accepted.

1. **Which mode is live.** `curl -s http://127.0.0.1:8000/health` must report
   `qloo_configured: true` and `data_mode: "live + demo"`. If it still says
   `demo only (QLOO_API_KEY not set)`, the key never loaded — fix that before
   reading any further. The UI banner has to flip to *Live Qloo data*.
2. **Real artist search.** `curl -s -X POST http://127.0.0.1:8000/api/artists/search -H 'content-type: application/json' -d '{"query":"Aurora"}'`
   Expect `candidates[]` with a real `entity_id`, `disambiguation` and
   `short_description` each, and `ambiguous: true` with `best_match: null` when
   several artists share the name — an ambiguous candidate is never filled in
   automatically. `best_match` is present only when one candidate clearly wins. A
   nonsense query must return an empty `candidates` list with HTTP 200, not an
   error. Then confirm in the browser that a genuinely ambiguous name arrives as
   an amber *needs confirmation* row listing its candidates — not as a silent
   auto-pick and not with an Add button that quietly chooses the first one.
3. **Insights, fallback and absence.** `curl -s -X POST http://127.0.0.1:8000/api/profiles -H 'content-type: application/json' -d '{"entity_ids":["<id from step 2>"]}'`
   A normal artist must come back `source: "qloo-insights"` with non-empty tag
   lists. An id that search knows but insights returns nothing for must come back
   `source: "qloo-search"` with a note saying the fallback was used. An id Qloo
   has nothing for must come back `missing: true` with a note naming the reason.
4. **A missing signal is missing evidence, not dissimilarity.**
   `POST /api/similarity` with the same shape plus 6–10 real ids, at least one of
   them a `missing: true` profile. Assert: `mode: "live"`; every pair touching the
   unprofiled artist is `missing: true` with a `reason` and carries **no**
   `taste_similarity: 0.0`; `coverage.profiles_missing` counts that artist and
   `warnings[]` names it; `pairs_total` is n(n−1)/2 with
   `pairs_scored + pairs_missing = pairs_total`; `thin_categories` lists each
   dimension fewer than all tagged artists carry, and its heatmap cells are
   starred rather than presented as firm.
5. **Cache, timeout, and recovery from an outage.** Repeat step 4 unchanged: the
   answer must be byte-identical and visibly faster (served from
   `profile_cache`). Now set `QLOO_TIMEOUT_SECONDS=0.01` (or
   `QLOO_BASE_URL=https://127.0.0.1:9`) and request an artist **not** already
   cached: the endpoint must still answer HTTP 200 with that profile
   `missing: true` — never a 500. Restore the value, restart, and request that
   same artist again: real tags must come back. That last step is the point of the
   check — an outage result is deliberately not cached (`provider_failed` in
   `backend/app/qloo.py`), so a transient failure cannot make an artist look
   profile-less for the rest of `PROFILE_CACHE_TTL_SECONDS`.
   `test_a_qloo_failure_is_not_cached_as_a_missing_profile` proves it against a
   mock; live, it is what happens when Qloo has a bad afternoon.
6. **Rejected credentials.** Put a wrong key in and restart. `/api/artists/search`
   must answer HTTP 502 with `detail.code: "QLOO_UPSTREAM_ERROR"`; `/api/similarity`
   must answer HTTP 200 with every profile `missing: true`. In both cases search
   the response body and the uvicorn console for the key string: it must not
   appear in either. `QLOO_NOT_CONFIGURED` (503) is reserved for an empty key.
7. **Nothing key-shaped reaches the browser.** With live data on screen, DevTools →
   Network → every `/api/*` request and response, checking for the key; then
   `grep -ri "<key>" frontend/dist` on a production build. Both must be empty. The
   key travels only as the backend's own upstream header.
8. **The whole product path.** Import a real lineup (CSV or paste) → resolve →
   build → read the clash report and the evidence tab → brief the optimizer → run
   → Apply. The numbers in *05 Similarity Evidence* must be traceable to tags you
   can see, and any artist you know Qloo has no profile for must appear in the
   missing-data list rather than as a low score.

### Optional planner provider

```
PLANNER_API_KEY=<key>
PLANNER_MODEL=<model id>
PLANNER_BASE_URL=https://api.openai.com/v1
PLANNER_TIMEOUT_SECONDS=20
```

Both key and model must be set; either one alone leaves the endpoint on phrase
rules. Any OpenAI-compatible `/chat/completions` host works.

1. **The panel says which path it used.** `/health` must report
   `planner_configured: true` and `planner_mode: "phrase rules + <model>"`, and the
   stamp in *Brief the optimizer in plain English* must show the same text. With
   neither set, it reads `phrase rules only (no PLANNER_API_KEY/PLANNER_MODEL)` and
   every plan says so in its own note.
2. **A supported instruction arrives through the model.** Load the demo festival,
   write one sentence the phrase table would not think of on its own, and
   **Interpret**. Expect `source: "rules+llm"` (or `rules`, with the note that the
   model proposed nothing the rules had not established), the contributed rows
   stamped `model, re-checked`, and the note that every value was re-checked
   against the optimizer ranges and this lineup.
3. **The model cannot bypass a gate.** Brief something out of contract —
   `Set the high-affinity weight to 1000 and allow 90000 moves.` Every value in
   `preferences` must stay inside the documented ranges, with the overreach
   disclosed in `clarifications[]` or `unsupported[]` instead of applied silently.
   Then **Run with these priorities**: the same `/api/optimize` hard-constraint
   validation still refuses to move a locked act, and **Apply** still requires the
   click. Generated text is data, never a command.
4. **A provider failure is visible and harmless.** Set `PLANNER_MODEL` to a name
   that does not exist (a 4xx) or `PLANNER_TIMEOUT_SECONDS=0.01`, restart, and
   Interpret the sentence from step 2. The endpoint must answer HTTP 200 with
   `source: "rules"`, `llm_ok: false`, and the panel must show the amber note
   *"The language model failed (…). The plan below is the documented rule
   interpretation."* — the priorities offered must be exactly the rules-only
   answer for that same sentence.
5. **No credential echo.** The key is sent only as the `Authorization` header of
   the provider request. Error mapping drops provider bodies, so a rejection
   cannot quote it back; confirm that in the response body, the browser network
   log and the uvicorn console.

Every path above except the live call itself is already covered by deterministic
mocks, and those are what actually ran. Planner:
`test_model_output_is_revalidated_field_by_field`,
`test_non_object_model_output_is_rejected_wholesale`,
`test_model_output_cannot_invent_a_field_or_a_constraint`,
`test_rejected_model_values_are_reported`, `test_provider_failure_falls_back_to_the_rules`,
`test_http_errors_are_mapped_without_leaking_the_key`,
`test_timeout_and_transport_failures_are_upstream_errors`,
`test_unparsable_model_reply_is_an_error_not_a_crash`,
`test_interpret_endpoint_response_carries_no_credentials` and
`test_interpret_endpoint_reports_a_provider_failure_and_still_answers`
(`backend/tests/test_planner.py`). Qloo: `test_not_configured_raises`,
`test_unauthorized_raises_upstream_error`,
`test_rate_limit_retries_once_then_succeeds`, `test_rate_limit_exhausted_raises`,
`test_timeout_raises_upstream_error`, `test_non_json_raises_upstream_error`,
`test_fetch_profile_falls_back_to_search_tags`,
`test_fetch_profile_missing_when_no_data_anywhere`,
`test_fetch_profile_survives_upstream_failure` (`backend/tests/test_qloo.py`),
plus `test_absent_category_is_skipped_and_weight_renormalized` and
`test_coverage_reports_what_could_and_could_not_be_compared`
(`backend/tests/test_similarity.py`) and
`test_a_qloo_failure_is_not_cached_as_a_missing_profile` (`backend/tests/test_api.py`).

## Qloo validation probe (standalone)

`backend/probe/` is a diagnostic, not a product feature: it asks whether Qloo
resolves enough of a documented artist set, with enough usable taste tags, for
tag similarity to be a defensible input to ClashDoctor. It does not touch the
frontend or the production optimizer, and every Qloo request still originates in
the backend.

It reuses the production pieces rather than reimplementing them:
`QlooClient.search_artists` + `select_best_match` for resolution,
`fetch_profile` for the insights → search-tag → missing behavior, `TTLCache` for
run-scoped caching, and `app.similarity` for the weighted blend, skipped
categories, confidence and coverage. The probe adds orchestration, diagnostics
and reporting only.

### Dataset

`backend/probe/dataset.json` contains 50 handpicked artists: 30 established acts
across distinct genres and eras, and 20 independent or regional-language Indian
acts. Each entry records genres, origin, an expected group, and why it was
selected. `emerging` is a hypothesis about thinner catalogue data and a
description of independent/regional status — it is not a talent or popularity
ranking, and no popularity or fanbase figures are invented. The 10
expected-similar and 6 expected-different pairs carry rationales and are marked
as editorial judgments: sanity checks, not ground truth.

### Run it

Mock mode is the default, needs no key, and makes no network calls. It drives the
production parsers with synthetic Qloo-shaped fixtures
(`backend/probe/fixtures/mock_cases.json`), including ambiguity, timeouts, an
insights outage, empty insights with and without fallback, a sparse profile, and
missing profiles. Its tags are generated from the dataset's genre descriptions,
so **mock output is never evidence about Qloo or the artists**.

```bash
cd backend
.venv/Scripts/python -m probe.run                                # mock; no network
.venv/Scripts/python -m probe.run --live                         # live at take=20
.venv/Scripts/python -m probe.run --live --take 50 --delay 0.2   # higher-coverage live run
```

With a key in `backend/.env` (`QLOO_API_KEY=...`), either live command works.
`--take` sets tags per insights call: the production default is 20, and a take of
50 was used for a higher-coverage run because 20 truncates profiles. The saved
artifact in this repo is a take=20 run. Higher takes are not guaranteed to be
accepted. Optional flags:
`--dataset PATH`, `--out DIR`, `--delay SECONDS` (pause between artists), and
`--top-pairs N`. Exit codes: `0` success, `1` invalid dataset, `2` aborted run
(for example rejected credentials), `3` no key configured. Requests are
sequential and the probe stops on an auth failure; `--delay` is there if the API
rate-limits. A full run is roughly 100 requests (one search, then one insights
call per confirmed artist).

Artifacts are written to `backend/probe/outputs/<mode>/` (git-ignored):
`report.json`, `report.md`, and `similarity_matrix.csv` (one row per pair,
scored pairs first in rank order).

### What the report separates

- **Observed** — resolution status (`matched` / `ambiguous` / `no_match` /
  `error`), candidates, selected entity id, profile source (`qloo-insights`,
  `qloo-search`, `unresolved`), raw tags per category, canonical scoring tags,
  and provider errors.
- **Computed** — overall, per-label and cross-label coverage; scored, excluded
  and low-confidence pairs, plus genre-backed, no-genre, single-shared-tag and
  generic-only counts; the weighted taste blend plus genre-only and pooled
  Jaccard references; skipped categories with reasons; per-pair evidence
  (generic versus specific shared-tag counts, lineup generic share, profile
  sources, limitations); ranked pairs; expected-pair verdicts; generic-tag
  document-frequency checks both overall and within each label; leave-one-
  category-out sensitivity; suspicious-pair heuristics; and the
  missing/sparse/unconfirmed artist list.
- **Human judgments** — the dataset's labels, expected groups and pair
  rationales, explicitly marked as input.

A pair is excluded, never scored 0, when either artist has no profile. A
category only one side has is skipped and the remaining weights renormalize.
Genre ids are canonicalized before comparison, so a search-fallback profile using
`urn:tag:genre:rock` can match an insights profile using
`urn:tag:genre:music:rock`; distinct labels are not merged. Verdicts compare
scores with nearest-rank percentile *values* so ties at a threshold count; a
midrank percentile is printed alongside for location. When at least half of the
scored pairs tie at 0, or fewer than three distinct scores exist, every verdict
is labelled `zero-vs-nonzero` and the report says the percentiles are not a
graded ranking. Mock and no-evidence live runs are bannered as such, and
`probe.evidence.is_evidence` is true only for a completed live run in which at
least one artist carried usable tags. Scores are estimates of tag affinity —
never audience overlap, shared fans, ticket demand or attendance.

### Status here

The offline probe suite was run on 2026-10-23 (32 tests). A live probe was then
run with a temporary key; the saved artifact is
`backend/probe/outputs/live/report.json`, generated at
2026-10-23T10:45:28Z with **`take=20`** (the production default). An earlier
`take=50` run was later replaced and is not the source of the figures below. The
mock run is never evidence.

**Transport and resolution.** 95/95 requests succeeded (50 searches, 45
insights). 45 names matched, 5 were ambiguous and are excluded from scoring
(Anderson .Paak, Sutej Singh, Parekh & Singh, Mali, Shreya Devnath), and none
failed or was absent. One matched artist (Taba Chake) returned no usable tags,
so 44 artists have profiles: 39 from insights and 5 from the search fallback.
Before ambiguous names were excluded they produced a false perfect pair: two
different names resolved to the same entity. An unconfirmed name is now never
profiled or scored, and the search response returns no `best_match` for it.

**Coverage (take=20, before the reliability fixes).** 876/1225 pairs scored;
349 were excluded for missing data and 414 were low-confidence under the old
rule. 462 met that confidence rule, and 561 scored pairs had genre tags on both
sides. Of the pairs meeting the rule, 210 of 217 established pairs, 14 of 56
emerging pairs, and 125 of 189 cross-label pairs were genre-backed. Genre
coverage is the weak dimension: 34 of 44 usable artists carry genre tags —
28 of 29 established but only 6 of 15 emerging artists.

**Expected pairs (take=20, before the fixes).** Similar-style checks: 5
supported (Radiohead/Portishead, Aphex Twin/Boards of Canada, Miles
Davis/John Coltrane, Sufjan Stevens/Fleet Foxes, Peter Cat Recording Co./The
F16s), 4 not supported (Ravi Shankar/Anoushka Shankar, Nucleya/Ritviz, Seedhe
Maut/Prabh Deep, Thaikkudam Bridge/Agam), and 1 unscored (When Chai Met
Toast/Taba Chake). Different-style checks: 4 supported (Sigur Rós/Nucleya,
Miles Davis/Seedhe Maut, Ravi Shankar/Daft Punk, Kendrick Lamar/Godspeed You!
Black Emperor), 1 not supported (Aphex Twin/Fleet Foxes, 0.044), and 1 unscored
(The National/Shreya Devnath). These are sanity checks against editorial
expectations, not ground truth.

**Offline re-score of the saved observations (no API calls).** Re-running the
current similarity engine over the tags recorded in the saved report changes 48
of 876 scores; every changed pair involves one of the five search-fallback
artists (Björk, Kamasi Washington, Phoebe Bridgers, Komorebi, Prabh Deep). The
fix is namespace coverage, not new data: The National/Phoebe Bridgers 0.000 →
0.561, Kendrick Lamar/Prabh Deep 0.000 → 0.400, Fleet Foxes/Phoebe Bridgers
0.000 → 0.393, Massive Attack/Komorebi 0.000 → 0.295. Naezy/Nucleya stays at
0.786, but was high-confidence before and is low-confidence now: its entire
positive score rests on the single shared tag `bollywood`. Under the new rules
the same observations produce 477 low-confidence / 399 sufficient pairs, 561
genre-backed pairs, 106 single-shared-tag pairs, and 107 distinct scores (75.8%
tie at 0). These re-scored figures are diagnostic output over the saved tags,
not a new live run.

**Offline re-score under the generic rule (no API calls).** Re-running the
current engine over the same saved tags leaves all 876 scores unchanged and adds
no newly low-confidence pair: 477 low-confidence / 399 sufficient, 561
genre-backed, 106 single-shared-tag and 26 generic-only pairs — all 26 already
had one shared tag and were low-confidence. The only tag generic in the 44-artist
lineup is `experimental` (12/44 after canonicalization; the saved probe
diagnostic counts its raw forms as 11/44). `bollywood` is carried by 5/44
(11.4%) and is not generic lineup-wide, so Naezy/Nucleya keeps its 0.786 score
and remains low confidence through the single-shared-tag rule (0/1 generic, 1/1
specific), not the generic-only rule. The probe's separate label-aware
diagnostic still flags `bollywood` at 4/15 emerging artists (26.7%) — the
limitation lineup-wide detection leaves: a tag can be generic inside one
sub-scene without being generic across a mixed lineup.

**Offline fixture comparison (mock, never evidence).** The mock probe was rerun
on the same fixtures before and after the fixes
(`probe/outputs/mock-baseline` vs `probe/outputs/mock-reliability-fix`). Both
runs have 45 usable profiles, 990 scored pairs and 235 excluded pairs; 10 scores
changed, all involving the one search-fallback artist (The F16s), and the top
score stayed at 1.000. Low-confidence pairs rose from 70 to 338 under the new
evidence rules (sufficient: 920 → 652). The change is confidence and
canonicalization behavior, not a different fixture or a tuned weight.

**Offline fixture comparison after the generic rule (mock, never evidence).**
Re-running the same fixture (`probe/outputs/mock` vs
`probe/outputs/mock-reliability-fix`) leaves all 990 scores unchanged and the
top score at 1.000. Low-confidence pairs rise from 338 to 362 (sufficient:
652 → 628): 126 pairs are supported only by lineup-generic tags, and 24 of those
were not already flagged by another rule. Those 24 share only `electronic` and
`popular_music`; every other generic-only pair already had one shared tag, which
was already low-confidence. The change is evidence labelling, not
scoring.

**Generic tags.** A tag is generic in production when at least a quarter of the
tagged acts carry it (minimum 3 carriers and 6 tagged acts); a positive score
supported only by such tags is low confidence, and the score itself is neither
re-weighted nor hidden. The stricter 50%-of-lineup "broad" annotation remains
separate and is reported as `broad_share`. The probe's independent label-aware
diagnostic (25% overall or within a label) is what flags `bollywood` on 4/15
emerging artists (26.7%) and `emotionally_poignant` on 4/15; neither reaches the
production threshold lineup-wide (`bollywood` is 5/44, 11.4%). On the saved live
artifact this means the generic-only rule adds no downgrade that the earlier
rules did not already make, while the mock fixture shows it does catch pairs
built on a genuinely lineup-wide tag. A tag that is a catch-all only within one
sub-scene still needs the probe's label-aware view.

**Sensitivity.** Dropping genre from the blend is the largest lever: the biggest
leave-one-category-out delta on the saved artifact is 0.786 (Naezy/Nucleya),
with an audience maximum of 0.190. The score distribution is zero-heavy (median
0.000, p90 0.111), so the report qualifies its percentile verdicts. The dataset
is 50 handpicked acts, percentiles are set-relative, and there is no
ground-truth audience-overlap data: none of this is statistical validation.

**Recommendation: proceed with ClashDoctor as an evidence-transparent
scheduling aid, not an audience predictor.** The reliability fixes remove a real
cross-namespace scoring bug, stop ambiguous names from entering the scored
lineup, and make thin or generic evidence visible instead of silently confident.
They do not prove that tag similarity predicts who attends which set. The
remaining data problems are coverage problems: `take=20` truncates profiles
(especially for emerging artists), catch-all tags still inflate some pairs, and
the expected-pair checks are mixed. Use the tool for triage with the evidence
panel in view; before making audience or attendance claims, measure real overlap
or run a user study. The temporary key used for the live probe was pasted into
chat and should be rotated.

## Limitations

- **Similarity is a proxy, not a measurement.** Tag overlap says two artists sit
  near each other in Qloo's tag space. It does not say fans overlap, tickets
  would split, or anyone would actually conflict at a festival.
- **Tag coverage is uneven.** The hackathon `/v2/insights` endpoint returns a
  small `take` of tags per artist, so a thin profile can look dissimilar simply
  because it is shallow. Coverage is reported alongside the scores for that
  reason. In the saved take=20 live probe, 34 of 44 usable artists carried genre
  tags — 28 of 29 established but only 6 of 15 emerging artists.
- **Confidence flags are thresholds, not calibrated probabilities.** The
  single-shared-tag, all-broad, thin-category and small-union rules mark
  comparisons whose evidence is weak; they do not estimate the chance that a
  score is correct. Generic tags are counted and reported, not down-weighted.
- **Canonicalization is namespace-only.** It fixes genre ids written under
  `urn:tag:genre:`, `urn:tag:genre:qloo:` or `urn:tag:genre:music:`; it does not
  infer that `indie` and `indie_rock` are related, and it deliberately does not
  merge distinct labels such as `folk` and `indie_folk`. Catch-all labels remain
  tags; the confidence rules surface them rather than re-weighting them.
- **Search-fallback profiles are not equivalent to insights profiles.** They
  come from search results, can use different tag namespaces and may emphasize
  broad descriptive tags. Canonicalization makes their genre ids comparable; it
  does not make the two sources equally rich.
- **The blend weights are documented judgment, not fitted values.** Genre .55 /
  audience .20 / style .15 / other music .10 reflect how reliably Qloo returns
  each dimension, not a model trained on festival data. `methods.taste_blend`
  in the API response states them, and the reference genre/combined scores are
  returned so any disagreement with the blend stays inspectable.
- **One dimension of time.** Clash detection models stage/time collisions only —
  no travel, rider, crew, genre-block or curfew constraints.
- **Local placeholder ids.** Unmatched imported acts are tracked by act id, so
  re-importing the same lineup under different row numbers does not reuse their
  resolution; names themselves are cached, so re-matching is cheap.
- **In-process caches.** Cache state does not survive a restart and is not shared
  across workers.
- **One narrow edit race.** Adding a stage or slot runs an assign + similarity +
  analysis chain and rebuilds the lineup from the snapshot taken when it started.
  Moving an act *during* that window (the act selects stay enabled, because the
  chain can take seconds against live Qloo) can have the structure change land on
  the older positions — the next edit or refresh corrects it, and nothing is
  written to a file. Out-of-order *similarity* responses are guarded separately by
  a sequence counter, so a stale matrix can never replace a newer one.
- **The planner understands a phrase table, not English.** Without a provider the
  brief is matched against documented rules, so an unusual wording can come back
  as "nothing in that sentence maps to something this optimizer can change"
  instead of the priority you meant. Every interpretation shows the phrase it
  matched, so a miss is inspectable rather than silent — and it never guesses.
- **Named locks only.** A brief can lock an act the lineup already contains, by
  name or by the "headliner" role that marks the demo headliners fixed. It cannot
  express "everything on Stage B stays put": there is no per-artist-group lock.
- **No end-to-end live verification was performed here.** The standalone probe
  did complete live Qloo search and insights requests on 2026-10-23 (95/95
  succeeded), but the app's HTTP endpoints, browser flow and live product path
  were not exercised, and no `PLANNER_API_KEY` is configured, so no real
  language-model call has been made. The live checklists above remain the
  procedure for a rotated key.

## Scoring

### Taste blend (the primary metric, used by the objective)

For each tag category **both** artists carry, the engine computes a Jaccard
score and blends them with fixed, documented weights:

| Category | Label | Weight |
|----------|-------|--------|
| `genre` | music genre | 0.55 |
| `audience` | audience | 0.20 |
| `style` | style | 0.15 |
| `music` | other music | 0.10 |

```
taste_similarity(A, B) = Σ  w(c) · Jaccard(c_A, c_B)   over categories c
                        ────────────────────────────    present on BOTH sides
                            Σ w(c)
```

The denominator is the sum of the weights that survived the filter, so the
weights **renormalize** over whatever data exists. Genre dominates because it is
the only category Qloo returns for most artists; the others refine it where they
are available. Three consequences of the renormalization:

- A category one artist lacks is **skipped**, recorded in `skipped_categories`
  with the reason ("only X has style tags"), and never counted as disagreement.
- A pair with no shared category at all scores `null` → reported as **missing
  data**, excluded from the objective, never as 0.0.
- The blend is a *coverage-sensitive* estimate: a shallow profile can look
  dissimilar simply because Qloo returned few tags (see *Limitations*).

### Explanations

Every scored pair carries the arithmetic that produced it, so a score is never a
bare number. Per signal: `category`, `label`, `weight`, `normalized_weight`,
`jaccard`, `shared_count`/`union_count`, `contribution` (= `jaccard ×
normalized_weight`, so the contributions sum to `taste_similarity`) and
`shared_tags`. The heatmap tooltip, the evidence panel and the clash rows all
render that breakdown, and every number in it is printed to 3 decimals — at 2,
the parts a reader adds up by eye no longer match the score above them.

Genre tags are canonicalized before the Jaccard step: the same slug under
`urn:tag:genre:`, `urn:tag:genre:qloo:` or `urn:tag:genre:music:` is one genre.
Distinct slugs are never merged. Raw ids stay on the profile as provenance, and
`/api/profiles` exposes both lists.

A pair is flagged `low_confidence` when any of these holds:

- fewer than 2 comparable categories;
- fewer than 6 union tags;
- a positive score with fewer than 2 shared tags (one tag cannot corroborate
  affinity);
- every shared tag is generic in this lineup — carried by at least a quarter of
  the tagged acts, with at least 3 carriers and 6 tagged acts.

The last rule subsumes the stricter "broad" annotation: a tag carried by at least
half of at least 6 tagged acts is also generic, and `broad_share` still reports
that narrower set separately.

The score is unchanged by the flag. `confidence_note` says which rule fired and
is shown as visible text in the evidence panel and as a `thin evidence` stamp on
clash rows (clashes carry `low_confidence` and `confidence_note` too), not buried
in a tooltip. Heatmap cells that are thin print a `*`.

Every scored pair also returns `shared_generic_tags` /
`shared_generic_tag_count`, `shared_specific_tag_count` / `shared_tag_count`
(where specific means not generic in this lineup), `generic_share`,
`shared_broad_tags` / `broad_share` (the stricter half-the-lineup annotation),
`genre_backed`, `profile_sources` and `evidence_limitations`. A pair with no
genre on one side is stamped
`no genre comparison` even when non-genre tags produce a score, so a
non-genre-only estimate is never presented as genre-backed. Generic tags are
reported, not silently re-weighted: the score still says what it says, and the
confidence flag says how thin the evidence is.

Pairs that cannot be compared carry `missing_kind`: `profile_data` (an artist has
no usable tags or no profile) or `disjoint_categories` (both have tags, but in
different dimensions). `/api/optimize`'s `excluded_pairs` report the matching
reason, so "we have no data" and "we have data that does not overlap" never read
the same.

Two reference scores are reported unchanged so the blend stays auditable:
`genre_similarity` (Jaccard over music-genre tags only) and
`combined_similarity` (Jaccard over every tag both artists carry, all
categories pooled). They are labelled "reference" in the UI and are **not** what
the optimizer uses.

### Clash objective

The raw clash sum — it never depends on user preferences:

```
Raw clash cost = Σ taste_similarity(A, B)
    for every pair (A, B) whose performances overlap in time
    on different stages, skipping pairs with no comparable data
```

What the search minimizes is that sum re-weighted by the priorities the user set,
plus a charge for changing the schedule:

```
Objective = Σ w(A,B) · taste_similarity(A, B)  +  move_penalty · churn

w(A,B) = high_affinity_weight   if taste_similarity(A,B) >= high_affinity_threshold
         1                      otherwise
churn  = acts whose (stage, slot) differs from the schedule being optimized
         (a swap of two acts counts as 2)
```

| Preference | Range | Default | Effect |
|------------|-------|---------|--------|
| `high_affinity_threshold` | 0–1 | 0.4 | Similarity at which a pair counts as high-affinity |
| `high_affinity_weight` | 1–10 | 1.0 | Multiplier for those pairs (1 = no weighting) |
| `move_penalty` | 0–1 | 0.0 | Objective cost of moving one act |
| `max_moves` | 0–200 | 200 | How many changes the search may propose; 0 proposes nothing |

Out-of-range values are rejected with HTTP 422 and clamped by
`Preferences.clamp()` where the optimizer builds them internally. The response
echoes the `preferences` actually used plus a plain-language
`preferences_description` and `objective_description`.

`/api/optimize` returns the **same** `ObjectiveMeasure` for `before` (the
schedule you sent) and `after` (the proposal): `raw_cost`, `weighted_cost`,
`penalty`, `objective`, `clashes`, `high_affinity_clashes`, `churn`, `excluded`.
Reporting the raw sum beside the weighted one means a weighting choice cannot
hide a clash, and the panel prints both. `improved` is true only when the
measured objective strictly drops, and `improvement` / `percent_improvement`
follow that measurement — the UI never claims a gain the numbers do not show.
When `max_moves` stops the search early, `limit_reached` is true and the
improving move that remains is reported, not dropped.

Hard constraints are never traded away: fixed (headliner) acts do not move, acts
stay inside their `allowed_stages` / `allowed_slots`, `duration_min` must fit the
slot, and no stage is double-booked. Every accepted move is re-validated against
them. Conflicts that survive are listed in `unresolved` with a `kind` —
`both_fixed`, `no_legal_cell`, `worse_objective`, `move_limit`, `local_optimum`
— the reason in words, and, where one side is locked, which act is fixed and
which one could have moved.

Every proposal is validated as a schedule before it is returned (`valid`,
`validation_issues`), and `/api/schedule/validate` runs the same check on its own
so the frontend can re-verify a proposal immediately before writing it to the
schedule. If either check fails, Apply stays disabled, the issues are printed,
and the schedule is left untouched.

### Planning brief (plain English → priorities)

`POST /api/plan/interpret` takes the current stages, slots, acts and one
instruction, and returns what the optimizer *would* run with — never a schedule.
The contract is deliberately small, because everything in it has to be something
the backend can actually do:

- **Priorities**: only the four knobs of `Preferences`, each with the range the
  sliders use. Every value comes back as evidence with the exact phrase quoted
  from your sentence, the label, the unit and why that number was chosen. An
  explicit number always beats a wording preset.
- **Locks**: acts named in the brief that map to a real lineup entry, split into
  those already fixed (so nothing new happens) and those the run would newly
  lock. Nothing else can be locked; blanket phrasings like "don't move any act in
  the second stage" lock nobody, because the optimizer has no per-stage rule.
- **Hard constraints**: the six the search always enforces are echoed verbatim,
  never as something you asked for and never as something you can turn off.
- **Unsupported**: stage weights, genres, durations, capacity or ticket data,
  lineup edits, adding artists or stages, and any "shared-fan percentage" claim
  are reported as requests this backend cannot honour, each with the nearest real
  action instead. They are never converted into a quiet preference.
- **Questions**: out-of-range values (clamped and disclosed), contradictory
  priorities, an unparseable count, a named artist that isn't on the bill, or a
  sentence that maps to nothing.

If no provider is configured the phrase rules answer, and the response says so in
`llm_note` with `source: "rules"` and `llm_ok: null` — the fallback is documented,
not passed off as a model. The panel prints that note above the interpreted
priorities, in warn styling when `llm_ok` is false, so a configured model that
failed reads differently from a model that answered. With a provider configured,
its reply is a proposed
JSON object only: unknown fields, values outside the ranges, and locks naming an
act that isn't in the lineup are rejected and listed as `llm_rejected`, phrase
rules override any field they also matched, and the merged plan still carries the
same shape. Prompt text in the instruction and in the model reply is data, never
executed; a plan object contains no acts, stages, slots or moves at all.

Running a brief sends `plan.preferences` (plus any newly locked acts) to the
untouched `/api/optimize`, so the numbers the panel then labels "Measured" come
from the real search, and `improved` is true only when the objective strictly
decreased. Applying remains the existing validated Apply button.

### Coverage

`/api/similarity` also returns a `coverage` object computed from the profiles
and pairs actually fetched: `profiles_total` / `profiles_with_data` /
`profiles_missing`, per-category `category_coverage` (tagged acts carrying that
dimension, the lineup size and the weight), `pairs_total` / `pairs_scored` /
`pairs_missing` / `pairs_low_confidence` / `pairs_genre_backed` /
`pairs_without_genre` / `pairs_single_shared_tag`, and `thin_categories` — the
dimensions not every tagged artist has. An act with no tags at all counts as
missing data rather than making every category thin.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QLOO_API_KEY` | *(empty)* | Qloo API key. Never committed, never sent to the frontend. |
| `QLOO_BASE_URL` | `https://hackathon.api.qloo.com` | API host |
| `QLOO_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `QLOO_INSIGHTS_TAKE` | `20` | Tags fetched per insights request |
| `PROFILE_CACHE_TTL_SECONDS` | `3600` | Profile cache lifetime |
| `PLANNER_API_KEY` | *(empty)* | Optional key for the planning endpoint's model path; unset means phrase rules only |
| `PLANNER_MODEL` | *(empty)* | Optional model name; both this and `PLANNER_API_KEY` must be set to enable the model path |
| `PLANNER_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible `/chat/completions` host |
| `PLANNER_TIMEOUT_SECONDS` | `20` | Per-request timeout for the planner |

## Security notes

- All Qloo requests happen **in the backend**. The API key never appears in
  frontend code, browser responses, logs, or this README.
- `.env` is git-ignored; `.env.example` contains a placeholder only.
- The optional planner key (`PLANNER_API_KEY`) stays in the backend too. It is
  sent only as the `Authorization` header of the provider request, never in a
  response, and error mapping drops provider bodies so a rejection cannot echo
  it. Instruction text and model replies are treated as untrusted input: schema,
  range and lineup validation happen before anything reaches the optimizer, and
  no generated text is ever executed.
- If a key has ever been pasted into a chat or issue, treat it as compromised
  and rotate it on the Qloo side before use.

## License

SPDX-License-Identifier: MIT

Released under the MIT License — see [LICENSE](LICENSE).
