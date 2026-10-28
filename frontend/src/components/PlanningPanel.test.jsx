import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PlanningPanel from './PlanningPanel.jsx';

const ACTS = [
  { id: 'a1', name: 'Alpha Waves' },
  { id: 'a2', name: 'Beta Choir' },
];

const AFFINITY = {
  high_affinity_threshold: 0.5,
  high_affinity_weight: 3,
  move_penalty: 0,
  max_moves: 200,
};

function plan(overrides = {}) {
  return {
    instruction: 'Keep both headliners fixed and reduce high-affinity clashes.',
    interpreted: true,
    preferences: { ...AFFINITY },
    preferences_description: 'Pairs at or above 0.50 count 3x; a change costs nothing.',
    evidence: [
      {
        field: 'high_affinity_weight',
        label: 'High-affinity weight',
        value: 3,
        unit: 'x',
        phrase: 'high-affinity',
        rule: 'high_affinity',
        source: 'rules',
        note: 'a high-affinity pair counts 3× a normal one',
      },
      {
        field: 'high_affinity_threshold',
        label: 'High-affinity threshold',
        value: 0.5,
        unit: 'estimated similarity',
        phrase: 'high-affinity',
        rule: 'high_affinity',
        source: 'rules',
        note: 'pairs at 0.50 similarity or above are the high-affinity ones',
      },
    ],
    enforced_constraints: [
      'one (stage, slot) cell per act',
      'no cell hosts two acts',
      'set duration fits its slot',
      'stage/slot references exist',
      'allowed_stages and allowed_slots respected',
      'fixed acts keep their assigned cell',
    ],
    locked_acts: ['Aurora Lane'],
    requested_locks: [
      {
        act_id: 'a1',
        act_name: 'Aurora Lane',
        phrase: 'keep both headliners fixed',
        already_locked: true,
        via_role: true,
        source: 'rules',
      },
    ],
    unsupported: [],
    clarifications: [],
    requires_confirmation: false,
    source: 'rules',
    llm_configured: false,
    llm_model: null,
    llm_ok: null,
    llm_note: 'No language model is configured (PLANNER_API_KEY and PLANNER_MODEL are unset).',
    summary:
      'Priorities: a high-affinity pair counts 3× a normal one — “high-affinity”. Already locked, so already obeyed: Aurora Lane. Running it re-plans the schedule below; applying stays your decision.',
    ...overrides,
  };
}

function renderPanel(overrides = {}) {
  const props = {
    plan: null,
    planning: false,
    planError: null,
    analysis: null,
    running: false,
    applied: false,
    acts: ACTS,
    plannerMode: 'phrase rules only (no PLANNER_API_KEY/PLANNER_MODEL)',
    onInterpret: vi.fn(),
    onClear: vi.fn(),
    onRun: vi.fn(),
    ...overrides,
  };
  render(<PlanningPanel {...props} />);
  return props;
}

const box = () => screen.getByRole('region', { name: /plan the run in plain english/i });

describe('PlanningPanel', () => {
  it('keeps Interpret disabled until something is written', () => {
    renderPanel();
    const interpret = screen.getByRole('button', { name: /interpret/i });
    expect(interpret).toBeDisabled();
    expect(screen.getByPlaceholderText(/keep the headliners fixed/i)).toHaveAttribute(
      'maxLength',
      '2000',
    );
  });

  it('sends the typed instruction to the backend interpreter', async () => {
    const props = renderPanel();
    await userEvent.type(screen.getByLabelText(/one scheduling priority/i), 'reduce every clash');
    await userEvent.click(screen.getByRole('button', { name: /interpret/i }));
    expect(props.onInterpret).toHaveBeenCalledTimes(1);
    expect(props.onInterpret).toHaveBeenCalledWith('reduce every clash');
  });

  it('fills the brief from an example button and interprets that text verbatim', async () => {
    const props = renderPanel();
    const example = screen.getByRole('button', {
      name: /minimize schedule changes/i,
    });
    await userEvent.click(example);
    expect(screen.getByLabelText(/one scheduling priority/i)).toHaveValue(
      'Minimize schedule changes, even if some clashes remain.',
    );
    await userEvent.click(screen.getByRole('button', { name: /interpret/i }));
    expect(props.onInterpret).toHaveBeenCalledWith(
      'Minimize schedule changes, even if some clashes remain.',
    );
  });

  it('shows a busy state while the brief is being read', () => {
    renderPanel({ planning: true });
    expect(screen.getByRole('status')).toHaveTextContent(/reading the request/i);
  });

  it('surfaces an interpretation failure as an alert', () => {
    renderPanel({ planError: 'The planning instruction is empty.' });
    expect(screen.getByRole('alert')).toHaveTextContent(/instruction is empty/i);
  });

  it('previews interpreted priorities with their quoted evidence', () => {
    renderPanel({ plan: plan() });
    const values = screen.getAllByText(/high-affinity (weight|threshold)/i);
    expect(values.length).toBe(2);
    expect(within(box()).getByText('3.00')).toBeInTheDocument();
    expect(within(box()).getByText('0.50')).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    for (const item of items) {
      expect(within(item).getByText(/“high-affinity”/)).toBeInTheDocument();
      expect(within(item).getByText('phrase rule')).toBeInTheDocument();
    }
  });

  it('names the hard constraints the run will enforce', () => {
    renderPanel({ plan: plan() });
    expect(within(box()).getByText(/always enforced: 6 hard constraints/i)).toBeInTheDocument();
    expect(within(box()).getByText(/fixed acts keep their assigned cell/)).toBeInTheDocument();
  });

  it('states an already-fixed act once instead of repeating it', () => {
    renderPanel({ plan: plan() });
    const note = within(box()).getByText(/locked already/i);
    expect(note.textContent).toContain('Locked already: Aurora Lane.');
    expect(note.textContent).not.toMatch(/your brief asked for/i);
    expect(within(box()).queryByText(/run would additionally lock/i)).not.toBeInTheDocument();
  });

  it('names the act a brief singled out when the lineup locks more than that', () => {
    renderPanel({
      plan: plan({
        locked_acts: ['Aurora Lane', 'Skyline Drip'],
      }),
    });
    const note = within(box()).getByText(/locked already/i);
    expect(note.textContent).toContain('Locked already: Aurora Lane, Skyline Drip.');
    expect(note.textContent).toContain('Your brief asked for Aurora Lane by name.');
  });

  it('asks for approval when the brief wants a new lock', () => {
    renderPanel({
      plan: plan({
        locked_acts: [],
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
      }),
    });
    expect(within(box()).getByText(/run would additionally lock: beta choir/i)).toBeInTheDocument();
    expect(within(box()).getByText(/needs your approval/i)).toBeInTheDocument();
  });

  it('shows what the backend cannot do instead of hiding it', () => {
    renderPanel({
      plan: plan({
        unsupported: [
          {
            phrase: 'prioritize stage',
            reason: 'the objective has no per-stage weight.',
            alternative: 'Lock the acts that must stay where they are.',
            source: 'rules',
          },
        ],
      }),
    });
    expect(within(box()).getByText(/this backend cannot do that/i)).toBeInTheDocument();
    expect(within(box()).getByText(/no per-stage weight/i)).toBeInTheDocument();
    expect(within(box()).getByText(/instead: lock the acts/i)).toBeInTheDocument();
  });

  it('shows clarifications the organizer should check before running', () => {
    renderPanel({
      plan: plan({
        clarifications: [
          {
            kind: 'out_of_range',
            phrase: 'at most 500 moves',
            question: 'The plan uses 200; set the control if you meant something else.',
            candidates: [],
          },
        ],
      }),
    });
    expect(within(box()).getByText(/out of range/i)).toBeInTheDocument();
    expect(within(box()).getByText(/the plan uses 200/i)).toBeInTheDocument();
  });

  it('labels a model contribution as re-checked rather than as an instruction', () => {
    renderPanel({
      plan: plan({
        source: 'rules+llm',
        llm_configured: true,
        llm_ok: true,
        llm_model: 'gpt-test',
        evidence: [
          {
            field: 'max_moves',
            label: 'Most moves allowed',
            value: 4,
            unit: 'moves',
            phrase: 'proposed by the language model',
            rule: 'llm',
            source: 'llm',
            note: 'the search may propose up to 4 changes',
          },
        ],
      }),
    });
    expect(within(box()).getByText(/model, re-checked/i)).toBeInTheDocument();
    expect(within(box()).getByText(/proposed by the language model/i)).toBeInTheDocument();
  });

  it('says which source produced the plan when the model was consulted', () => {
    renderPanel({
      plan: plan({
        llm_configured: true,
        llm_ok: true,
        llm_model: 'gpt-test',
        llm_note:
          'The language model was consulted; every value was re-checked against the optimizer ranges and this lineup.',
      }),
    });
    expect(within(box()).getByText(/every value was re-checked/i)).toBeInTheDocument();
  });

  it('warns, in the panel itself, when a configured model failed and the rules answered', () => {
    renderPanel({
      plan: plan({
        llm_configured: true,
        llm_ok: false,
        llm_model: 'gpt-test',
        llm_note:
          'The language model failed (provider timeout). The plan below is the documented rule interpretation.',
      }),
    });
    const note = within(box()).getByText(/language model failed/i);
    expect(note).toHaveClass('warn');
    expect(note.textContent).toContain('documented rule interpretation');
  });

  it('says when the objective table is not yet this plan', () => {
    renderPanel({ plan: plan() });
    expect(within(box()).getByText(/not measured yet/i)).toBeInTheDocument();
  });

  it('says when the measured run is exactly this plan', () => {
    renderPanel({
      plan: plan(),
      analysis: { preferences: { ...AFFINITY } },
    });
    expect(within(box()).getByText(/measured — the table below is this plan/i)).toBeInTheDocument();
  });

  it('says so once the plan has actually been applied', () => {
    renderPanel({
      plan: plan(),
      applied: true,
      analysis: { preferences: { ...AFFINITY } },
    });
    expect(within(box()).getByText(/measured and applied/i)).toBeInTheDocument();
    expect(within(box()).queryByText(/applying it stays your decision/i)).not.toBeInTheDocument();
  });

  it('does not claim a match when the table was measured under other priorities', () => {
    renderPanel({
      plan: plan(),
      analysis: {
        preferences: { high_affinity_threshold: 0.4, high_affinity_weight: 1, move_penalty: 0, max_moves: 200 },
      },
    });
    expect(within(box()).getByText(/not measured yet/i)).toBeInTheDocument();
  });

  it('runs the plan through the optimizer only on request', async () => {
    const props = renderPanel({ plan: plan() });
    expect(props.onRun).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /run with these priorities/i }));
    expect(props.onRun).toHaveBeenCalledTimes(1);
  });

  it('has no way to apply a proposal from the brief itself', () => {
    renderPanel({ plan: plan() });
    expect(screen.queryByRole('button', { name: /^apply/i })).not.toBeInTheDocument();
    expect(within(box()).getByText(/applying stays your decision/i)).toBeInTheDocument();
  });

  it('says when there is nothing to plan and nothing to interpret', () => {
    renderPanel({ acts: [] });
    expect(within(box()).getByText(/add at least one artist/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /interpret/i })).toBeDisabled();
  });

  it('clears the brief and the plan together', async () => {
    const props = renderPanel({ plan: plan() });
    fireEvent.change(screen.getByLabelText(/one scheduling priority/i), {
      target: { value: 'reduce clashes' },
    });
    expect(screen.getByRole('button', { name: /interpret/i })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: /^clear$/i }));
    expect(props.onClear).toHaveBeenCalled();
    expect(screen.getByLabelText(/one scheduling priority/i)).toHaveValue('');
  });
});
