import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import { api } from './services/api.js';
import { SESSION_KEY } from './session.js';

vi.mock('./services/api.js', () => ({
  api: {
    health: vi.fn(),
    demoFestival: vi.fn(),
    templateFestival: vi.fn(),
    searchArtists: vi.fn(),
    similarity: vi.fn(),
    optimize: vi.fn(),
    interpretPlan: vi.fn(),
    validateSchedule: vi.fn(),
    assignSchedule: vi.fn(),
    importParse: vi.fn(),
    importResolve: vi.fn(),
  },
}));

const STAGES = [
  { id: 'main', name: 'Main Stage' },
  { id: 'pulse', name: 'Pulse Tent' },
];
const SLOTS = [
  { id: 't1', start: '17:00', end: '18:00', label: '17:00' },
  { id: 't2', start: '18:00', end: '19:00', label: '18:00' },
  { id: 't3', start: '19:00', end: '20:00', label: '19:00' },
];

const NEUTRAL = {
  high_affinity_threshold: 0.4,
  high_affinity_weight: 1,
  move_penalty: 0,
  max_moves: 200,
};
const AFFINITY = { ...NEUTRAL, high_affinity_weight: 3, high_affinity_threshold: 0.5 };

// Two simultaneous pairs: 17:00 on both stages, 18:00 on both stages. The
// proposal can only break the first one (the second stage is full at 19:00 in
// this fixture's fiction), so a schedule that has been applied still holds one
// clash while the next proposal claims it could reach zero.
const DRAFT_ACTS = [
  { id: 'a1', name: 'Alpha Waves', entity_id: 'e1', stage_id: 'main', slot_id: 't1', duration_min: 60, fixed: false },
  { id: 'a2', name: 'Beta Choir', entity_id: 'e2', stage_id: 'pulse', slot_id: 't1', duration_min: 60, fixed: false },
  { id: 'a3', name: 'Gamma Drums', entity_id: 'e3', stage_id: 'main', slot_id: 't2', duration_min: 60, fixed: false },
  { id: 'a4', name: 'Delta Set', entity_id: 'e4', stage_id: 'pulse', slot_id: 't2', duration_min: 60, fixed: false },
];
const APPLIED_ACTS = DRAFT_ACTS.map((a) => (a.id === 'a2' ? { ...a, slot_id: 't3' } : a));
const NEXT_ACTS = APPLIED_ACTS.map((a) => (a.id === 'a4' ? { ...a, stage_id: 'main', slot_id: 't3' } : a));

const clash = (a, b, sim) => ({
  a_id: a.id,
  a_name: a.name,
  b_id: b.id,
  b_name: b.name,
  stage_a: a.stage_id,
  slot_a: a.slot_id,
  stage_b: b.stage_id,
  slot_b: b.slot_id,
  similarity: sim,
  method: 'taste_blend',
  signals: [],
  low_confidence: false,
  confidence_note: null,
});

const CLASH_12 = clash(DRAFT_ACTS[0], DRAFT_ACTS[1], 0.62);
const CLASH_34 = clash(DRAFT_ACTS[2], DRAFT_ACTS[3], 0.31);

const measure = (overrides = {}) => ({
  raw_cost: 0.93,
  weighted_cost: 0.93,
  penalty: 0,
  objective: 0.93,
  clashes: 2,
  high_affinity_clashes: 1,
  churn: 0,
  excluded: 0,
  ...overrides,
});

const move = (act, fromStage, fromSlot, toStage, toSlot, saved, delta) => ({
  act_id: act.id,
  act_name: act.name,
  moved_act_ids: [act.id],
  kind: 'relocate',
  from_stage: fromStage,
  from_slot: fromSlot,
  to_stage: toStage,
  to_slot: toSlot,
  raw_cost_saved: saved,
  objective_delta: delta,
  explanation: `Moving ${act.name} out of ${fromSlot} stops it playing against another stage.`,
});

// Draft: 2 clashes now, 1 after the single proposed move.
const DRAFT_REPORT = {
  objective_description: 'objective = Σ weight × similarity + 0.00 × acts moved',
  preferences: { ...NEUTRAL },
  preferences_description: 'Every pair counts once and changes are free.',
  before: measure(),
  after: measure({
    raw_cost: 0.31,
    weighted_cost: 0.31,
    objective: 0.31,
    clashes: 1,
    high_affinity_clashes: 0,
    churn: 1,
  }),
  initial_cost: 0.93,
  optimized_cost: 0.31,
  improvement: 0.62,
  improved: true,
  percent_improvement: 0.667,
  limit_reached: false,
  valid: true,
  validation_issues: [],
  initial_clashes: [CLASH_12, CLASH_34],
  optimized_clashes: [CLASH_34],
  moves: [move(DRAFT_ACTS[1], 'pulse', 't1', 'pulse', 't3', 0.62, -0.62)],
  moved_acts: [
    { act_id: 'a2', act_name: 'Beta Choir', from_stage: 'pulse', from_slot: 't1', to_stage: 'pulse', to_slot: 't3' },
  ],
  unresolved: [],
  excluded_pairs: [],
  fixed_clashes: [],
  optimized_acts: APPLIED_ACTS,
};

// Measured from the schedule the user accepted: it still holds one clash, and a
// further proposal would clear it — a difference the header must not blur.
const APPLIED_REPORT = {
  ...DRAFT_REPORT,
  before: measure({
    raw_cost: 0.31,
    weighted_cost: 0.31,
    objective: 0.31,
    clashes: 1,
    high_affinity_clashes: 0,
    churn: 0,
  }),
  after: measure({
    raw_cost: 0,
    weighted_cost: 0,
    objective: 0,
    clashes: 0,
    high_affinity_clashes: 0,
    churn: 1,
  }),
  initial_cost: 0.31,
  optimized_cost: 0,
  improvement: 0.31,
  percent_improvement: 1,
  initial_clashes: [CLASH_34],
  optimized_clashes: [],
  moves: [move(APPLIED_ACTS[3], 'pulse', 't2', 'main', 't3', 0.31, -0.31)],
  moved_acts: [
    { act_id: 'a4', act_name: 'Delta Set', from_stage: 'pulse', from_slot: 't2', to_stage: 'main', to_slot: 't3' },
  ],
  optimized_acts: NEXT_ACTS,
};

const festival = (acts) => ({ name: 'Test Fest', mode: 'demo', stages: STAGES, slots: SLOTS, acts });

function matrix(pairs) {
  return {
    mode: 'demo',
    profiles: pairs.map((pair) => ({
      entity_id: pair.a,
      name: 'Alpha Waves',
      found: true,
      source: 'demo',
      genre_tags: ['indie'],
      audience_tags: [],
      style_tags: [],
      music_tags: ['dream pop'],
      note: '',
    })),
    pairs,
    coverage: {
      profiles_total: 4,
      profiles_with_data: 4,
      profiles_missing: 0,
      pairs_total: pairs.length,
      pairs_scored: pairs.length,
      pairs_missing: 0,
      pairs_low_confidence: 0,
      category_coverage: {},
      thin_categories: [],
    },
    methods: { taste_blend: 'weighted jaccard' },
    warnings: [],
  };
}

const pair = (a, b, value) => ({
  a,
  b,
  taste_similarity: value,
  genre_similarity: value,
  combined_similarity: value,
  signals: [],
  skipped_categories: [],
  missing: false,
  missing_reason: '',
  low_confidence: false,
  confidence_note: null,
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function planFor(instruction, overrides = {}) {
  return {
    instruction,
    interpreted: true,
    preferences: { ...NEUTRAL },
    preferences_description: 'Every pair counts once and changes are free.',
    evidence: [],
    enforced_constraints: ['one act per stage slot', 'set lengths still fit'],
    locked_acts: [],
    requested_locks: [],
    unsupported: [],
    clarifications: [],
    requires_confirmation: false,
    source: 'rules',
    llm_configured: false,
    llm_model: null,
    llm_ok: null,
    llm_note: '',
    summary: 'Nothing new was understood, so the current controls are used as they are.',
    ...overrides,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState({}, '', '/dashboard');
  api.health.mockResolvedValue({
    status: 'ok',
    app: 'ClashDoctor API',
    version: '1.0.0',
    qloo_configured: false,
    data_mode: 'demo only (QLOO_API_KEY not set)',
    planner_configured: false,
    planner_mode: 'phrase rules only (no PLANNER_API_KEY/PLANNER_MODEL)',
  });
  api.demoFestival.mockResolvedValue(festival(DRAFT_ACTS));
  api.templateFestival.mockResolvedValue(festival([]));
  api.searchArtists.mockResolvedValue({ candidates: [], best_match: null, ambiguous: false });
  api.validateSchedule.mockResolvedValue({ valid: true, issues: [] });
  api.assignSchedule.mockImplementation((stages, slots, acts) => Promise.resolve({ acts, note: '' }));
  api.importParse.mockResolvedValue({ valid: true, acts: [], stages: [], slots: [], issues: [] });
  api.importResolve.mockResolvedValue([]);
  api.similarity.mockResolvedValue(matrix([pair('e1', 'e2', 0.62)]));
  api.optimize.mockImplementation((stages, slots, acts) =>
    Promise.resolve(acts.find((a) => a.id === 'a2')?.slot_id === 't3' ? APPLIED_REPORT : DRAFT_REPORT),
  );
  api.interpretPlan.mockResolvedValue(planFor(''));
});

const scheduleClashes = () =>
  waitFor(() => {
    const aside = document.querySelector('#schedule .section-aside');
    expect(aside).not.toBeNull();
    return aside.textContent;
  });

async function runBrief(text) {
  await userEvent.type(screen.getByLabelText(/one scheduling priority/i), text);
  await userEvent.click(screen.getByRole('button', { name: /Interpret/i }));
  await userEvent.click(await screen.findByRole('button', { name: /Run with these priorities/i }));
}

const settlePersistence = () => new Promise((resolve) => window.setTimeout(resolve, 0));

describe('App — the numbers follow the schedule that exists', () => {
  it('counts the clashes of the applied schedule, not of the next proposal', async () => {
    render(<App />);
    expect(await scheduleClashes()).toContain('2 clashes');

    await userEvent.click(await screen.findByRole('button', { name: /Apply optimized schedule/i }));

    // The accepted proposal moved one act; the clash it could not break is still
    // on the grid, so the header must say one — never the zero the next plan aims for.
    expect(await scheduleClashes()).toContain('1 clash');
    expect(api.optimize).toHaveBeenCalledTimes(2);
    const remeasured = api.optimize.mock.calls[1][2];
    expect(remeasured.find((a) => a.id === 'a2').slot_id).toBe('t3');
  });

  it('arms Apply again when a brief produces a new proposal for an applied schedule', async () => {
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Apply optimized schedule/i }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Applied to schedule/i })).toBeDisabled(),
    );

    api.interpretPlan.mockResolvedValue(
      planFor('weight the pairs you like most 3x', {
        preferences: { ...AFFINITY },
        preferences_description: 'pairs at 0.5 count 3.0x; at most 200 moves.',
        summary: 'Priorities: a high-affinity pair counts 3× a normal one.',
      }),
    );

    await userEvent.type(
      screen.getByLabelText(/one scheduling priority/i),
      'weight the pairs you like most 3x',
    );
    await userEvent.click(screen.getByRole('button', { name: /Interpret/i }));
    await userEvent.click(await screen.findByRole('button', { name: /Run with these priorities/i }));

    // The brief re-measured the same acts, so the schedule on screen is a proposal
    // again and Apply must be live rather than stuck on "Applied".
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply optimized schedule/i })).toBeEnabled(),
    );
    expect(screen.queryByRole('button', { name: /Applied to schedule/i })).not.toBeInTheDocument();
  });

  it('drops a previewed brief when an act is moved to another slot', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    api.interpretPlan.mockResolvedValue(
      planFor('lock Beta Choir', {
        locked_acts: ['Alpha Waves'],
        requested_locks: [
          {
            act_id: 'a2',
            act_name: 'Beta Choir',
            phrase: 'lock beta choir',
            already_locked: false,
            via_role: false,
            source: 'rules',
          },
        ],
        requires_confirmation: true,
        summary: 'Needs your approval before the run: lock Beta Choir.',
      }),
    );
    await userEvent.type(screen.getByLabelText(/one scheduling priority/i), 'lock Beta Choir');
    await userEvent.click(screen.getByRole('button', { name: /Interpret/i }));
    await screen.findByText(/Run would additionally lock: Beta Choir/i);

    const slotSelect = screen.getByLabelText('Time slot for Beta Choir');
    await userEvent.selectOptions(
      slotSelect,
      within(slotSelect).getByRole('option', { name: '19:00–20:00' }),
    );

    // That lock was read from a lineup the user has now changed.
    await waitFor(() =>
      expect(
        screen.queryByText(/Run would additionally lock: Beta Choir/i),
      ).not.toBeInTheDocument(),
    );
  });

  it('keeps the newest similarity matrix when an older request answers last', async () => {
    const older = deferred();
    const newer = deferred();
    api.similarity
      .mockResolvedValueOnce(matrix([pair('e1', 'e2', 0.62)]))
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise);
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });

    const removes = await screen.findAllByRole('button', { name: 'Remove' });
    await userEvent.click(removes[0]); // Alpha Waves
    await userEvent.click((await screen.findAllByRole('button', { name: 'Remove' }))[0]); // Beta Choir

    // Out of order: the second edit answers first, the stale matrix lands after it.
    newer.resolve(matrix([pair('e3', 'e4', 0.9)]));
    older.resolve(matrix([pair('e3', 'e4', 0.1)]));

    await waitFor(() => expect(screen.getAllByText('0.90').length).toBeGreaterThan(0));
    expect(screen.queryByText('0.10')).not.toBeInTheDocument();
  });
});

describe('App — priorities stay in step with the app', () => {
  it('moves every slider to the priorities a planner run just committed', async () => {
    api.optimize.mockImplementation((stages, slots, acts, prefs) =>
      Promise.resolve({ ...DRAFT_REPORT, preferences: { ...prefs } }),
    );
    api.interpretPlan.mockResolvedValue(
      planFor('weight your favourites 3x', {
        preferences: { ...AFFINITY },
        preferences_description: 'pairs at 0.5 count 3.0x; at most 200 moves.',
        summary: 'Priorities: a high-affinity pair counts 3× a normal one.',
      }),
    );

    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    await runBrief('weight your favourites 3x');

    await waitFor(() => expect(screen.getAllByRole('slider')[0]).toHaveValue('0.5'));
    expect(screen.getAllByRole('slider')[1]).toHaveValue('3');
    expect(screen.queryByText(/Sliders changed/)).not.toBeInTheDocument();
  });

  it('puts the sliders back when the demo is reset', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    await settlePersistence();
    const [threshold] = screen.getAllByRole('slider');
    fireEvent.change(threshold, { target: { value: '0.55' } });
    fireEvent.keyUp(threshold);
    expect(threshold).toHaveValue('0.55');

    await userEvent.click(screen.getByRole('button', { name: /reset demo/i }));
    await waitFor(() => expect(screen.getAllByRole('slider')[0]).toHaveValue('0.4'));
    expect(screen.getAllByRole('slider')[1]).toHaveValue('1');
    expect(screen.queryByText(/Sliders changed/)).not.toBeInTheDocument();
  });
});

describe('App — an invalid schedule never survives an edit', () => {
  it('does not offer an occupied cell in the move pickers', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });

    const betaStage = screen.getByLabelText('Stage for Beta Choir');
    const main = within(betaStage).getByRole('option', { name: 'Main Stage' });
    expect(main).toBeDisabled();
    expect(main).toHaveAttribute('title', expect.stringContaining('already occupied by Alpha Waves'));

    const gammaSlot = screen.getByLabelText('Time slot for Gamma Drums');
    const t1 = within(gammaSlot).getByRole('option', { name: '17:00–18:00' });
    expect(t1).toBeDisabled();
  });

  it('keeps the last valid schedule when the backend rejects an edit', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });

    api.optimize.mockRejectedValueOnce(
      Object.assign(new Error("Stage 'pulse' slot 't2' is double-booked."), {
        code: 'INVALID_SCHEDULE',
      }),
    );
    const slot = screen.getByLabelText('Time slot for Beta Choir');
    // Forced past the picker on purpose: the API's rejection is what must recover.
    fireEvent.change(slot, { target: { value: 't2' } });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('That cell is already occupied by Delta Set');
    expect(alert).toHaveTextContent("Stage 'pulse' slot 't2' is double-booked.");
    expect(screen.getByLabelText('Time slot for Beta Choir')).toHaveValue('t1');
    expect(await scheduleClashes()).toContain('2 clashes');
    expect(screen.getAllByText('Delta Set').length).toBeGreaterThan(0);
  });
});

describe('App — locks can always be undone', () => {
  it('shows lock sources and clears planner locks without touching organizer locks', async () => {
    api.demoFestival.mockResolvedValueOnce(
      festival(DRAFT_ACTS.map((a) => (a.id === 'a1' ? { ...a, fixed: true } : a))),
    );
    api.interpretPlan.mockResolvedValue(
      planFor('lock beta and gamma', {
        requested_locks: [
          {
            act_id: 'a2',
            act_name: 'Beta Choir',
            phrase: 'lock beta',
            already_locked: false,
            via_role: false,
            source: 'rules',
          },
          {
            act_id: 'a3',
            act_name: 'Gamma Drums',
            phrase: 'lock gamma',
            already_locked: false,
            via_role: false,
            source: 'rules',
          },
        ],
        requires_confirmation: true,
        summary: 'Needs your approval before the run: lock Beta Choir, Gamma Drums.',
      }),
    );

    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    expect(screen.getByText('organizer lock')).toBeInTheDocument();
    await runBrief('lock beta and gamma');
    await screen.findByText('Clear planner locks (2)');
    expect(screen.getAllByText('planner lock')).toHaveLength(2);

    await userEvent.click(screen.getByRole('button', { name: 'Unlock Beta Choir' }));
    await waitFor(() => expect(screen.getByLabelText('Stage for Beta Choir')).toBeEnabled());
    expect(screen.getByLabelText('Stage for Gamma Drums')).toBeDisabled();
    expect(screen.getByLabelText('Stage for Alpha Waves')).toBeDisabled();
    expect(api.demoFestival).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /clear planner locks \(1\)/i }));
    await waitFor(() => expect(screen.getByLabelText('Stage for Gamma Drums')).toBeEnabled());
    expect(screen.getByLabelText('Stage for Alpha Waves')).toBeDisabled();
    expect(screen.getByText('organizer lock')).toBeInTheDocument();
  });
});

describe('App — similarity failure is explained, never silent', () => {
  it('names the artists and reason, and the retry brings the grid back', async () => {
    api.similarity.mockRejectedValueOnce(new Error('Qloo request timed out.'));
    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Similarity data could not be loaded');
    expect(alert).toHaveTextContent('Alpha Waves, Beta Choir, Gamma Drums, Delta Set');
    expect(alert).toHaveTextContent('Qloo request timed out.');
    expect(document.querySelector('.heatmap')).toBeNull();

    await userEvent.click(within(alert).getByRole('button', { name: /^retry$/i }));
    await waitFor(() => expect(document.querySelector('.heatmap')).not.toBeNull());
    expect(screen.queryByText(/Similarity data could not be loaded/)).not.toBeInTheDocument();
  });
});

describe('App — the working session survives a refresh', () => {
  it('restores the lineup, assignment and priorities without re-fetching', async () => {
    const first = render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    await settlePersistence();

    const [threshold] = screen.getAllByRole('slider');
    fireEvent.change(threshold, { target: { value: '0.55' } });
    fireEvent.keyUp(threshold);
    const slot = screen.getByLabelText('Time slot for Beta Choir');
    await userEvent.selectOptions(
      slot,
      within(slot).getByRole('option', { name: '19:00–20:00' }),
    );

    await waitFor(() => {
      const saved = JSON.parse(window.localStorage.getItem(SESSION_KEY));
      expect(saved?.festival.acts.find((a) => a.id === 'a2')?.slot_id).toBe('t3');
      expect(saved?.preferences.high_affinity_threshold).toBe(0.55);
    });

    first.unmount();
    api.demoFestival.mockClear();
    api.similarity.mockClear();
    api.optimize.mockClear();

    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText('Time slot for Beta Choir')).toHaveValue('t3'),
    );
    expect(screen.getAllByRole('slider')[0]).toHaveValue('0.55');
    expect(api.demoFestival).not.toHaveBeenCalled();
    expect(api.similarity).not.toHaveBeenCalled();
  });

  it('clears the saved session when the demo is reset', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    await settlePersistence();

    const slot = screen.getByLabelText('Time slot for Beta Choir');
    await userEvent.selectOptions(
      slot,
      within(slot).getByRole('option', { name: '19:00–20:00' }),
    );
    await waitFor(() => expect(window.localStorage.getItem(SESSION_KEY)).not.toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /reset demo/i }));
    await waitFor(() => expect(api.demoFestival).toHaveBeenCalledTimes(2));
    // The demo reload must leave storage empty *after* its effects settle; a
    // late save of the pristine demo would silently defeat the reset.
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(window.localStorage.getItem(SESSION_KEY)).toBeNull();
  });
});

describe('App — intro route and dashboard route', () => {
  it('shows the intro at / and Get Started navigates to /dashboard', async () => {
    window.history.replaceState({}, '', '/');
    render(<App />);
    expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /The Schedule/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /get started/i }));
    await screen.findByRole('heading', { name: /The Schedule/i });
    expect(window.location.pathname).toBe('/dashboard');
  });

  it('renders the dashboard directly at /dashboard', async () => {
    window.history.replaceState({}, '', '/dashboard');
    render(<App />);
    await screen.findByRole('heading', { name: /The Schedule/i });
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument();
  });

  it('returns to the intro when the browser goes back from /dashboard', async () => {
    window.history.replaceState({}, '', '/');
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /get started/i }));
    await screen.findByRole('heading', { name: /The Schedule/i });
    expect(window.location.pathname).toBe('/dashboard');

    window.history.back();
    expect(await screen.findByRole('button', { name: /get started/i })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
  });

  it('redirects unknown paths to the intro at /', async () => {
    window.history.replaceState({}, '', '/somewhere-else');
    render(<App />);
    expect(await screen.findByRole('button', { name: /get started/i })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
  });

  it('still loads demo data behind the intro', async () => {
    window.history.replaceState({}, '', '/');
    render(<App />);
    await waitFor(() => expect(api.health).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('button', { name: /get started/i }));
    await screen.findByRole('heading', { name: /The Schedule/i });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
