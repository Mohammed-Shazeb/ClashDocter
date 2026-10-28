import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OptimizePanel from './OptimizePanel.jsx';

const STAGES = [
  { id: 'main', name: 'Main Stage' },
  { id: 'pulse', name: 'Pulse Tent' },
];

const SLOTS = [
  { id: 't1', start: '17:00', end: '18:00', label: '17:00' },
  { id: 't2', start: '18:00', end: '19:00', label: '18:00' },
];

const ACTS_BY_ID = {
  a1: { id: 'a1', name: 'Alpha Waves' },
  a2: { id: 'a2', name: 'Beta Choir' },
  a3: { id: 'a3', name: 'Gamma Drums' },
};

const NEUTRAL = {
  high_affinity_threshold: 0.4,
  high_affinity_weight: 1,
  move_penalty: 0,
  max_moves: 200,
};

const AFFINITY = {
  high_affinity_threshold: 0.5,
  high_affinity_weight: 3,
  move_penalty: 0,
  max_moves: 200,
};

const measure = (overrides = {}) => ({
  raw_cost: 1.25,
  weighted_cost: 1.25,
  penalty: 0,
  objective: 1.25,
  clashes: 3,
  high_affinity_clashes: 1,
  churn: 0,
  excluded: 1,
  ...overrides,
});

const RELOCATE = {
  act_id: 'a2',
  act_name: 'Beta Choir',
  moved_act_ids: ['a2'],
  kind: 'relocate',
  from_stage: 'main',
  from_slot: 't1',
  to_stage: 'pulse',
  to_slot: 't2',
  raw_cost_saved: 0.5,
  objective_delta: -0.5,
  explanation: 'Moving Beta Choir out of 17:00 on Main Stage separates it from Alpha Waves.',
};

const MOVED = {
  act_id: 'a2',
  act_name: 'Beta Choir',
  from_stage: 'main',
  from_slot: 't1',
  to_stage: 'pulse',
  to_slot: 't2',
};

function analysis(overrides = {}) {
  return {
    objective_description: 'objective = Σ weight × similarity + 0.00 × acts moved',
    preferences: { ...NEUTRAL },
    preferences_description: 'Every pair counts once and changes are free.',
    before: measure(),
    after: measure({
      raw_cost: 0.75,
      weighted_cost: 0.75,
      objective: 0.75,
      clashes: 2,
      high_affinity_clashes: 0,
      churn: 1,
    }),
    initial_cost: 1.25,
    optimized_cost: 0.75,
    improvement: 0.5,
    improved: true,
    percent_improvement: 0.4,
    limit_reached: false,
    valid: true,
    validation_issues: [],
    initial_clashes: [],
    optimized_clashes: [],
    moves: [RELOCATE],
    moved_acts: [MOVED],
    unresolved: [],
    excluded_pairs: [],
    fixed_clashes: [],
    optimized_acts: [{ id: 'a2', name: 'Beta Choir', stage_id: 'pulse', slot_id: 't2' }],
    ...overrides,
  };
}

function renderPanel(overrides = {}, props = {}) {
  const onPreferencesChange = vi.fn();
  const onApply = vi.fn();
  const onReset = vi.fn();
  const utils = render(
    <OptimizePanel
      analysis={overrides === null ? null : analysis(overrides)}
      analyzing={false}
      applied={false}
      applying={false}
      preferences={{ ...NEUTRAL }}
      onPreferencesChange={onPreferencesChange}
      onApply={onApply}
      onReset={onReset}
      stages={STAGES}
      slots={SLOTS}
      actsById={ACTS_BY_ID}
      {...props}
    />,
  );
  return { ...utils, onPreferencesChange, onApply, onReset };
}

const rowFor = (label) => screen.getByRole('rowheader', { name: label }).closest('tr');
const cellsOf = (label) => within(rowFor(label)).getAllByRole('cell').map((td) => td.textContent);

describe('OptimizePanel — the measured objective', () => {
  it('is a labelled region a keyboard user can scroll when it is pinned', () => {
    renderPanel();
    const region = screen.getByRole('region', { name: /optimization priorities/i });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region).toHaveClass('panel-sticky');
  });

  it('shows the objective before and after with the improvement it actually measured', () => {
    const { container } = renderPanel();
    const compare = container.querySelector('.compare');
    expect(within(compare).getByText('1.250')).toBeInTheDocument();
    expect(within(compare).getByText('0.750')).toBeInTheDocument();
    expect(within(compare).getByText('−0.500 (40%)')).toBeInTheDocument();
  });

  it('reports the raw clash sum separately from the weighted objective', () => {
    renderPanel({
      before: measure({ weighted_cost: 2.75, objective: 2.75 }),
      after: measure({ raw_cost: 0.75, weighted_cost: 1.25, objective: 1.25, churn: 1 }),
    });
    expect(cellsOf('Clash sum (raw)')).toEqual(['1.250', '0.750']);
    expect(cellsOf('Weighted by priority')).toEqual(['2.750', '1.250']);
    expect(cellsOf('Cost of changes')).toEqual(['0.000', '0.000']);
    expect(cellsOf('Pairs without data')).toEqual(['1', '1']);
  });

  it('marks only the cells the proposal changes', () => {
    renderPanel();
    const [draft, proposed] = within(rowFor('Clash sum (raw)')).getAllByRole('cell');
    expect(draft).not.toHaveClass('changed');
    expect(proposed).toHaveClass('changed');
    expect(cellsOf('Simultaneous pairs')).toEqual(['3', '2']);
    expect(within(rowFor('Pairs without data')).getAllByRole('cell')[1]).not.toHaveClass('changed');
  });

  it('names the priorities and the formula that produced the numbers', () => {
    renderPanel();
    expect(
      screen.getByText('objective = Σ weight × similarity + 0.00 × acts moved'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Every pair counts once and changes are free/)).toBeInTheDocument();
    expect(screen.getByText('priorities used')).toHaveClass('stamp-data');
  });

  it('never claims an improvement the measurement does not support', () => {
    const { container } = renderPanel({
      after: measure(),
      improvement: 0,
      improved: false,
      percent_improvement: null,
      optimized_cost: 1.25,
      moves: [],
      moved_acts: [],
      unresolved: [
        {
          a_id: 'a1',
          b_id: 'a3',
          similarity: 0.4,
          high_affinity: false,
          kind: 'local_optimum',
          reason: 'Every legal move costs more in change penalty than it saves in similarity.',
        },
      ],
    });
    expect(within(container.querySelector('.compare')).getByText('0.000')).toBeInTheDocument();
    expect(
      screen.getByText(/No change lowers this objective under the current priorities/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument();
  });

  it('says when the move limit stopped the search early', () => {
    renderPanel({ improved: false, limit_reached: true, moves: [], moved_acts: [] });
    expect(screen.getByText(/The move limit stopped the search first\./)).toBeInTheDocument();
  });
});

describe('OptimizePanel — priorities', () => {
  it('marks the preset whose priorities are committed', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: 'Break every clash' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Fewest changes' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it.each([
    ['Protect high-affinity pairs', NEUTRAL, AFFINITY],
    ['Fewest changes', NEUTRAL, { ...NEUTRAL, high_affinity_weight: 2, move_penalty: 0.5, max_moves: 5 }],
    ['Break every clash', AFFINITY, NEUTRAL],
  ])('commits the %s preset as one set of priorities', async (label, starting, expected) => {
    const user = userEvent.setup();
    const { onPreferencesChange } = renderPanel({}, { preferences: { ...starting } });
    await user.click(screen.getByRole('button', { name: label }));
    expect(onPreferencesChange).toHaveBeenCalledTimes(1);
    expect(onPreferencesChange).toHaveBeenCalledWith(expected);
  });

  it('re-plans when the move cap changes', async () => {
    const user = userEvent.setup();
    const { onPreferencesChange } = renderPanel();
    await user.selectOptions(screen.getByRole('combobox'), '5');
    expect(onPreferencesChange).toHaveBeenCalledWith({ ...NEUTRAL, max_moves: 5 });
    expect(screen.getByRole('combobox')).toHaveValue('5');
  });

  it('holds a slider change until the control is released, and says so', () => {
    const { onPreferencesChange } = renderPanel();
    const [threshold] = screen.getAllByRole('slider');

    // jsdom does not step a range input from arrow keys, so drive the two events
    // the panel actually listens for: the value change, then the release.
    fireEvent.change(threshold, { target: { value: '0.55' } });
    expect(onPreferencesChange).not.toHaveBeenCalled();
    // <output> also maps to role=status, so match the note by its text
    expect(screen.getByText(/Sliders changed/)).toHaveAttribute('role', 'status');

    fireEvent.keyUp(threshold);
    expect(onPreferencesChange).toHaveBeenCalledWith({
      ...NEUTRAL,
      high_affinity_threshold: 0.55,
    });
    expect(threshold).toHaveValue('0.55');
  });

  it('commits a slider change on blur for keyboard and pointer users alike', () => {
    const { onPreferencesChange } = renderPanel();
    const [, weight] = screen.getAllByRole('slider');
    fireEvent.change(weight, { target: { value: '4' } });
    fireEvent.blur(weight);
    expect(onPreferencesChange).toHaveBeenCalledWith({ ...NEUTRAL, high_affinity_weight: 4 });
  });

  it('shows the value each control currently holds', () => {
    renderPanel();
    const [threshold] = screen.getAllByRole('slider');
    expect(threshold).toHaveValue('0.4');
    expect(threshold.parentElement.querySelector('output')).toHaveTextContent('0.40');
  });

  it('follows priorities the app replaces without the user touching the sliders', () => {
    const props = {
      analysis: analysis(),
      analyzing: false,
      applied: false,
      applying: false,
      onPreferencesChange: vi.fn(),
      onApply: vi.fn(),
      onReset: null,
      stages: STAGES,
      slots: SLOTS,
      actsById: ACTS_BY_ID,
    };
    const { rerender } = render(<OptimizePanel {...props} preferences={{ ...NEUTRAL }} />);
    const [threshold, weight] = screen.getAllByRole('slider');
    expect(threshold).toHaveValue('0.4');
    expect(weight).toHaveValue('1');

    // A planner brief committed these priorities; the sliders must show them
    // immediately, and that is not a user edit worth warning about.
    rerender(<OptimizePanel {...props} preferences={{ ...AFFINITY }} />);
    expect(threshold).toHaveValue('0.5');
    expect(weight).toHaveValue('3');
    expect(screen.queryByText(/Sliders changed/)).not.toBeInTheDocument();

    fireEvent.change(threshold, { target: { value: '0.6' } });
    expect(screen.getByText(/Sliders changed/)).toBeInTheDocument();

    // Re-running the brief replaces the priorities again and clears the notice.
    rerender(<OptimizePanel {...props} preferences={{ ...NEUTRAL }} />);
    expect(threshold).toHaveValue('0.4');
    expect(screen.queryByText(/Sliders changed/)).not.toBeInTheDocument();
  });
});

describe('OptimizePanel — what the proposal does', () => {
  it('explains every proposed move and prices it twice', () => {
    renderPanel();
    const moves = screen.getByText('Proposed moves (1)').closest('.moves');
    expect(within(moves).getByText('Move Beta Choir')).toBeInTheDocument();
    expect(within(moves).getByText('Main Stage 17:00 → Pulse Tent 18:00')).toBeInTheDocument();
    expect(
      within(moves).getByText(
        'Moving Beta Choir out of 17:00 on Main Stage separates it from Alpha Waves.',
      ),
    ).toBeInTheDocument();
    expect(within(moves).getByTitle('Raw clash cost removed by this move')).toHaveTextContent(
      '−0.500',
    );
    expect(within(moves).getByTitle('Change in the prioritized objective')).toHaveTextContent(
      'objective −0.500',
    );
  });

  it('labels a swap as a swap and counts both acts it moves', () => {
    renderPanel({
      moves: [{ ...RELOCATE, kind: 'swap', moved_act_ids: ['a1', 'a2'], act_name: 'Alpha Waves' }],
    });
    expect(screen.getByText('Swap Alpha Waves')).toBeInTheDocument();
  });

  it('lists each act that moves with the cell it leaves and the cell it takes', () => {
    renderPanel();
    const moved = screen.getByText('Acts that move (1)').closest('.moved-acts');
    expect(within(moved).getByText('Beta Choir')).toBeInTheDocument();
    expect(within(moved).getByText('Main Stage 17:00 → Pulse Tent 18:00')).toBeInTheDocument();
  });

  it('reports the conflicts it could not resolve and why', () => {
    renderPanel({
      unresolved: [
        {
          a_id: 'a1',
          b_id: 'a3',
          similarity: 0.72,
          high_affinity: true,
          kind: 'both_fixed',
          reason: 'Both acts are locked headliners, so neither can be moved.',
        },
        {
          a_id: 'a2',
          b_id: 'a3',
          similarity: 0.31,
          high_affinity: false,
          kind: 'no_legal_cell',
          reason: 'No stage and time slot fits Gamma Drums without breaking a rule.',
          fixed_act: 'a3',
          movable_act: 'a2',
        },
      ],
    });
    const unresolved = screen.getByText('Unresolved conflicts (2)').closest('.unresolved');
    expect(within(unresolved).getByText('Alpha Waves · Gamma Drums')).toBeInTheDocument();
    expect(
      within(unresolved).getByText(/similarity 0.720 · above the high-affinity line/),
    ).toBeInTheDocument();
    expect(
      within(unresolved).getByText('Both acts are locked headliners, so neither can be moved.'),
    ).toBeInTheDocument();
    expect(within(unresolved).getByText(/locked: Gamma Drums · movable: Beta Choir/)).toBeInTheDocument();
    expect(within(unresolved).getByText('locked')).toHaveClass('stamp-clash');
    expect(within(unresolved).getByText('no legal cell')).toHaveClass('stamp-clash');
  });

  it('gives a softer stamp to a conflict a longer search could still fix', () => {
    renderPanel({
      moves: [],
      moved_acts: [],
      improved: false,
      unresolved: [
        {
          a_id: 'a1',
          b_id: 'a2',
          similarity: 0.5,
          high_affinity: true,
          kind: 'move_limit',
          reason: 'The move limit ran out before this pair could be separated.',
        },
      ],
    });
    expect(screen.getByText('move limit')).toHaveClass('stamp-warn');
  });

  it('falls back to the act id when the lineup map has no name for it', () => {
    renderPanel({
      unresolved: [
        {
          a_id: 'ghost',
          b_id: 'a3',
          similarity: 0.5,
          high_affinity: false,
          kind: 'local_optimum',
          reason: 'Every legal change makes the objective worse.',
        },
      ],
    });
    expect(screen.getByText('ghost · Gamma Drums')).toBeInTheDocument();
    expect(screen.getByText('needs more moves')).toHaveClass('stamp-warn');
  });

  it('states that clashes between locked headliners remain by design', () => {
    renderPanel({
      fixed_clashes: [
        { a_id: 'a1', a_name: 'Alpha Waves', b_id: 'a3', b_name: 'Gamma Drums', similarity: 0.6 },
      ],
    });
    expect(
      screen.getByText(/1 clash\(es\) involve locked headliners and remain by design/),
    ).toBeInTheDocument();
  });
});

describe('OptimizePanel — applying the proposal', () => {
  it('hands a valid proposal to the app', async () => {
    const user = userEvent.setup();
    const { onApply } = renderPanel();
    const apply = screen.getByRole('button', { name: /apply optimized schedule/i });
    expect(apply).toBeEnabled();
    await user.click(apply);
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it('keeps Apply disabled and explains itself when validation failed', () => {
    const { onApply } = renderPanel({
      valid: false,
      validation_issues: ["Stage 'main' is not allowed for 'Beta Choir'."],
    });
    expect(screen.getByRole('button', { name: /apply optimized schedule/i })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('The proposal failed its own constraint check');
    expect(alert).toHaveTextContent("Stage 'main' is not allowed for 'Beta Choir'.");
  });

  it('re-enables Apply once a valid proposal replaces the broken one', async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    const { rerender } = render(
      <OptimizePanel
        analysis={analysis({ valid: false, validation_issues: ['Beta Choir is double-booked.'] })}
        analyzing={false}
        applied={false}
        applying={false}
        preferences={{ ...NEUTRAL }}
        onPreferencesChange={vi.fn()}
        onApply={onApply}
        onReset={null}
        stages={STAGES}
        slots={SLOTS}
        actsById={ACTS_BY_ID}
      />,
    );
    expect(screen.getByRole('button', { name: /apply optimized schedule/i })).toBeDisabled();
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(
      <OptimizePanel
        analysis={analysis()}
        analyzing={false}
        applied={false}
        applying={false}
        preferences={{ ...NEUTRAL }}
        onPreferencesChange={vi.fn()}
        onApply={onApply}
        onReset={null}
        stages={STAGES}
        slots={SLOTS}
        actsById={ACTS_BY_ID}
      />,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /apply optimized schedule/i }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it('locks the button while the constraint check is running', () => {
    renderPanel({}, { applying: true });
    expect(screen.getByRole('button', { name: /checking constraints/i })).toBeDisabled();
  });

  it('reports that the schedule was updated and stops offering to apply again', () => {
    renderPanel({}, { applied: true });
    expect(screen.getByRole('button', { name: /applied to schedule/i })).toBeDisabled();
    expect(screen.getByText('Schedule updated')).toBeInTheDocument();
  });

  it('locks the button while a re-plan is in flight', () => {
    renderPanel({}, { analyzing: true });
    expect(screen.getByRole('button', { name: /apply optimized schedule/i })).toBeDisabled();
    expect(screen.getByText('Re-planning…')).toBeInTheDocument();
  });

  it('offers the demo reset when the app provides one and hides it otherwise', () => {
    const { onReset, unmount } = renderPanel();
    const reset = screen.getByRole('button', { name: /reset demo/i });
    expect(reset).toBeEnabled();
    unmount();
    renderPanel({}, { onReset: null });
    expect(screen.queryByRole('button', { name: /reset demo/i })).not.toBeInTheDocument();
    expect(onReset).not.toHaveBeenCalled();
  });
});

describe('OptimizePanel — states with nothing to show', () => {
  it('asks for artists before there is anything to optimize', () => {
    renderPanel(null);
    expect(screen.getByText('Add at least one artist to run the optimizer.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument();
  });

  it('hides the move list and the moved-act list when nothing moves', () => {
    renderPanel({ moves: [], moved_acts: [], improved: false, after: measure() });
    expect(screen.queryByText(/Proposed moves/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Acts that move/)).not.toBeInTheDocument();
  });
});
