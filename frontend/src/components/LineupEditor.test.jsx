import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LineupEditor from './LineupEditor.jsx';
import { api } from '../services/api.js';

vi.mock('../services/api.js', () => ({
  api: {
    searchArtists: vi.fn(),
  },
}));

const STAGES = [
  { id: 'main', name: 'Main Stage' },
  { id: 'second', name: 'Second Stage' },
];
const SLOTS = [
  { id: 't1', label: '17:00', start: '17:00', end: '18:00' },
  { id: 't2', label: '18:00', start: '18:00', end: '19:00' },
];

function makeAct(overrides = {}) {
  return {
    id: 'a1',
    name: 'Radiohead',
    entity_id: 'E-1',
    stage_id: 'main',
    slot_id: 't1',
    duration_min: 60,
    fixed: false,
    ...overrides,
  };
}

function renderEditor(props = {}) {
  const defaults = {
    acts: [],
    stages: STAGES,
    slots: SLOTS,
    profiles: {},
    onUpdateAct: vi.fn(),
    onRemoveAct: vi.fn(),
    onAddAct: vi.fn(),
    onToggleLock: vi.fn(),
    onClearPlannerLocks: vi.fn(),
    lockSources: {},
    qlooConfigured: true,
    structureBusy: false,
    onAddStage: vi.fn(),
    onRemoveStage: vi.fn(),
    onAddSlot: vi.fn(),
    onRemoveSlot: vi.fn(),
  };
  return render(<LineupEditor {...defaults} {...props} />);
}

describe('LineupEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a configuration message instead of search when Qloo is not configured', () => {
    renderEditor({ qlooConfigured: false });
    expect(screen.getByText(/Live artist search is disabled/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /artist name/i })).not.toBeInTheDocument();
  });

  it('shows search and an empty-lineup message for an empty lineup', () => {
    renderEditor();
    expect(screen.getByLabelText('Artist name to search on Qloo')).toBeInTheDocument();
    expect(screen.getByText(/No artists in the lineup yet/)).toBeInTheDocument();
  });

  it('searches Qloo, lists results and adds an artist', async () => {
    const user = userEvent.setup();
    api.searchArtists.mockResolvedValue({
      query: 'Radiohead',
      candidates: [
        { name: 'Radiohead', entity_id: 'E-1', short_description: 'English rock band' },
        { name: 'Radiohead Tribute', entity_id: 'E-2' },
      ],
      best_match: { entity_id: 'E-1' },
      ambiguous: false,
    });
    const onAddAct = vi.fn();
    renderEditor({ onAddAct });

    await user.type(screen.getByLabelText('Artist name to search on Qloo'), 'Radiohead');
    await user.click(screen.getByRole('button', { name: /search/i }));

    expect(await screen.findByText('Radiohead')).toBeInTheDocument();
    expect(screen.getByText('best match')).toBeInTheDocument();
    expect(screen.getByText('Radiohead Tribute')).toBeInTheDocument();

    const addButtons = screen.getAllByRole('button', { name: /^add/i });
    await user.click(addButtons[0]);
    expect(onAddAct).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Radiohead', entity_id: 'E-1' }),
      'main',
      't1',
    );
  });

  it('shows a search error when the backend request fails', async () => {
    const user = userEvent.setup();
    api.searchArtists.mockRejectedValue(new Error('Qloo returned HTTP 500 for /search.'));
    renderEditor();

    await user.type(screen.getByLabelText('Artist name to search on Qloo'), 'x');
    await user.click(screen.getByRole('button', { name: /search/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 500');
  });

  it('shows an empty-result message for zero candidates', async () => {
    const user = userEvent.setup();
    api.searchArtists.mockResolvedValue({
      query: 'zzz',
      candidates: [],
      best_match: null,
      ambiguous: false,
    });
    renderEditor();

    await user.type(screen.getByLabelText('Artist name to search on Qloo'), 'zzz');
    await user.click(screen.getByRole('button', { name: /search/i }));

    expect(await screen.findByText(/No artists found/)).toBeInTheDocument();
  });

  it('disables Add for artists already in the lineup', async () => {
    const user = userEvent.setup();
    api.searchArtists.mockResolvedValue({
      query: 'Radiohead',
      candidates: [{ name: 'Radiohead', entity_id: 'E-1' }],
      best_match: { entity_id: 'E-1' },
      ambiguous: false,
    });
    const onAddAct = vi.fn();
    renderEditor({ acts: [makeAct()], onAddAct });

    await user.type(screen.getByLabelText('Artist name to search on Qloo'), 'Radiohead');
    await user.click(screen.getByRole('button', { name: /search/i }));

    const results = document.querySelector('.search-results');
    const row = within(results).getByText('Radiohead').closest('.search-result-row');
    expect(within(row).getByText('in lineup')).toBeInTheDocument();
    const addButton = within(row).getByRole('button', { name: /added/i });
    expect(addButton).toBeDisabled();
    await user.click(addButton);
    expect(onAddAct).not.toHaveBeenCalled();
  });

  it('requires an explicit choice when search results are ambiguous', async () => {
    const user = userEvent.setup();
    api.searchArtists.mockResolvedValue({
      query: 'Coldplay',
      candidates: [
        { name: 'Coldplay', entity_id: 'E-1' },
        { name: 'Coldplay Tribute', entity_id: 'E-2' },
      ],
      best_match: null,
      ambiguous: true,
    });
    const onAddAct = vi.fn();
    renderEditor({ onAddAct });

    await user.type(screen.getByLabelText('Artist name to search on Qloo'), 'Coldplay');
    await user.click(screen.getByRole('button', { name: /search/i }));

    expect(await screen.findByText(/Several plausible matches/)).toBeInTheDocument();
    expect(screen.queryByText('best match')).not.toBeInTheDocument();
    expect(screen.getAllByText('ambiguous')).toHaveLength(2);

    // The user confirms by choosing a row; that explicit choice is what is added.
    const addButtons = screen.getAllByRole('button', { name: /^add/i });
    await user.click(addButtons[1]);
    expect(onAddAct).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Coldplay Tribute', entity_id: 'E-2' }),
      'main',
      't1',
    );
  });

  it('removes acts and keeps fixed acts locked', () => {
    const onRemoveAct = vi.fn();
    renderEditor({
      acts: [makeAct(), makeAct({ id: 'a2', name: 'Aurora Lane', entity_id: 'E-2', fixed: true })],
      onRemoveAct,
    });

    const lineup = document.querySelector('.lineup');
    const removeButtons = within(lineup).getAllByRole('button', { name: /remove/i });
    expect(removeButtons[0]).toBeEnabled();
    expect(removeButtons[1]).toBeDisabled();
    removeButtons[0].click();
    expect(onRemoveAct).toHaveBeenCalledWith('a1');
  });

  it('shows demo/live profile stamps from resolved profiles', () => {
    renderEditor({
      acts: [makeAct()],
      profiles: {
        'E-1': {
          entity_id: 'E-1',
          source: 'qloo-insights',
          missing: false,
          genre_tags: ['urn:tag:genre:music:rock'],
          audience_tags: [],
          style_tags: [],
          music_tags: [],
        },
      },
    });
    expect(screen.getByText('qloo-insights')).toBeInTheDocument();
  });

  it('does not offer a move another act already occupies', () => {
    renderEditor({
      acts: [
        makeAct(),
        makeAct({ id: 'a2', name: 'Aurora Lane', entity_id: 'E-2', stage_id: 'second', slot_id: 't1' }),
        makeAct({ id: 'a3', name: 'Night Bus', entity_id: 'E-3', stage_id: 'second', slot_id: 't2' }),
      ],
    });

    const stageForAurora = screen.getByLabelText('Stage for Aurora Lane');
    const main = within(stageForAurora).getByRole('option', { name: 'Main Stage' });
    expect(main).toBeDisabled();
    expect(main).toHaveAttribute('title', expect.stringContaining('already occupied by Radiohead'));
    expect(within(stageForAurora).getByRole('option', { name: 'Second Stage' })).toBeEnabled();

    const slotForAurora = screen.getByLabelText('Time slot for Aurora Lane');
    const t2 = within(slotForAurora).getByRole('option', { name: '18:00–19:00' });
    expect(t2).toBeDisabled();
    expect(t2).toHaveAttribute('title', expect.stringContaining('already occupied by Night Bus'));
  });

  it('respects an act’s allowed stage and slot targets in the pickers', () => {
    renderEditor({
      acts: [makeAct({ allowed_stages: ['main'], allowed_slots: ['t1'] })],
    });

    const stage = screen.getByLabelText('Stage for Radiohead');
    const second = within(stage).getByRole('option', { name: 'Second Stage' });
    expect(second).toBeDisabled();
    expect(second).toHaveAttribute('title', expect.stringContaining('Stage not allowed'));

    const slot = screen.getByLabelText('Time slot for Radiohead');
    const t2 = within(slot).getByRole('option', { name: '18:00–19:00' });
    expect(t2).toBeDisabled();
    expect(t2).toHaveAttribute('title', expect.stringContaining('Slot not allowed'));
  });

  it('names the lock source and lets the user undo either kind', async () => {
    const user = userEvent.setup();
    const onToggleLock = vi.fn();
    const onClearPlannerLocks = vi.fn();
    renderEditor({
      acts: [
        makeAct({ fixed: true }),
        makeAct({ id: 'a2', name: 'Aurora Lane', entity_id: 'E-2', fixed: true }),
      ],
      lockSources: { a2: 'planner' },
      onToggleLock,
      onClearPlannerLocks,
    });

    expect(screen.getByText('organizer lock')).toBeInTheDocument();
    expect(screen.getByText('planner lock')).toBeInTheDocument();
    expect(screen.getByText(/1 act is locked by a planner brief/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Unlock Aurora Lane' }));
    expect(onToggleLock).toHaveBeenCalledWith('a2');
    await user.click(screen.getByRole('button', { name: /clear planner locks \(1\)/i }));
    expect(onClearPlannerLocks).toHaveBeenCalledTimes(1);
  });

  it('offers a lock control on every act, locked or not', async () => {
    const user = userEvent.setup();
    const onToggleLock = vi.fn();
    renderEditor({ acts: [makeAct()], onToggleLock });

    const toggle = screen.getByRole('button', { name: 'Lock Radiohead' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);
    expect(onToggleLock).toHaveBeenCalledWith('a1');
  });

  it('adds and removes stages and slots via the structure editor', async () => {
    const user = userEvent.setup();
    const onAddStage = vi.fn();
    const onAddSlot = vi.fn();
    const onRemoveStage = vi.fn();
    renderEditor({ onAddStage, onAddSlot, onRemoveStage });

    await user.click(screen.getByRole('button', { name: /add stage/i }));
    expect(onAddStage).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /add slot/i }));
    expect(onAddSlot).toHaveBeenCalledWith(
      expect.objectContaining({ start: '19:00', end: '20:00' }),
    );

    const removeStageButtons = screen.getAllByRole('button', { name: /remove .* stage/i });
    expect(removeStageButtons).toHaveLength(2);
    await user.click(removeStageButtons[0]);
    expect(onRemoveStage).toHaveBeenCalledWith('main');
  });
});
