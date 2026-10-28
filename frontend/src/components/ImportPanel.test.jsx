import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ImportPanel from './ImportPanel.jsx';
import { api } from '../services/api.js';

vi.mock('../services/api.js', () => ({
  api: {
    importParse: vi.fn(),
    importResolve: vi.fn(),
  },
}));

function act(overrides = {}) {
  return {
    id: 'a1',
    row: 2,
    name: 'Radiohead',
    entity_id: '',
    stage_id: 'main-stage',
    stage_name: 'Main Stage',
    slot_id: 't1',
    start: '19:00',
    end: '20:00',
    duration_min: 60,
    fixed: false,
    ...overrides,
  };
}

function parsed(overrides = {}) {
  return {
    source_format: 'csv',
    festival_name: 'Sample Festival',
    stages: [{ id: 'main-stage', name: 'Main Stage' }],
    slots: [{ id: 't1', label: '19:00', start: '19:00', end: '20:00', duration_min: 60 }],
    acts: [act()],
    issues: [],
    valid: true,
    summary: '1 artist(s) · 1 stage(s) · 1 time slot(s) parsed from CSV',
    ...overrides,
  };
}

function renderPanel(props = {}) {
  const defaults = { qlooConfigured: true, busy: false, onImport: vi.fn() };
  return render(<ImportPanel {...defaults} {...props} />);
}

async function parseInto(user, text = 'Radiohead,Main Stage,19:00,20:00') {
  await user.type(screen.getByLabelText(/paste a lineup/i), text);
  await user.click(screen.getByRole('button', { name: /parse lineup/i }));
}

describe('ImportPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('parses text and previews the validated schedule', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed({ acts: [act({ fixed: true })] }));
    renderPanel();
    await parseInto(user);

    expect(api.importParse).toHaveBeenCalledWith(expect.stringContaining('Radiohead'), null);
    expect(await screen.findByText(/1 artist\(s\)/)).toBeInTheDocument();
    expect(screen.getByText('validated')).toBeInTheDocument();
    const grid = document.querySelector('.schedule-grid');
    expect(within(grid).getByText('Radiohead')).toBeInTheDocument();
    expect(within(grid).getByText('60m · locked')).toBeInTheDocument();
  });

  it('blocks building and explains rejected rows', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(
      parsed({
        valid: false,
        acts: [],
        summary: '0 artist(s) · 1 stage(s) · 1 time slot(s) parsed from CSV · 2 row(s) rejected',
        issues: [
          {
            severity: 'error',
            row: 2,
            field: 'stage',
            message: 'Double booking: Radiohead and Muse are both on Main Stage at 19:00–20:00.',
          },
          {
            severity: 'error',
            row: 3,
            field: 'stage',
            message: 'Double booking: Muse and Radiohead are both on Main Stage at 19:00–20:00.',
          },
        ],
      }),
    );
    renderPanel();
    await parseInto(user);

    expect(await screen.findByText('2 blocking problem(s)')).toBeInTheDocument();
    expect(screen.getByText(/are never dropped silently/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /build schedule/i })).toBeDisabled();
  });

  it('shows the backend message when parsing fails', async () => {
    const user = userEvent.setup();
    api.importParse.mockRejectedValue(new Error('No readable rows found in this input.'));
    renderPanel();
    await parseInto(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('No readable rows');
    expect(screen.queryByText('validated')).not.toBeInTheDocument();
  });

  it('fills the textarea from the sample and parses it', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed());
    renderPanel();

    await user.click(screen.getByRole('button', { name: /load sample/i }));
    expect(await screen.findByText('validated')).toBeInTheDocument();
    expect(screen.getByLabelText(/paste a lineup/i).value).toContain('Khruangbin');
    expect(api.importParse).toHaveBeenCalledTimes(1);
  });

  it('matches artists and hands only confirmed entity ids to onImport', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(
      parsed({ acts: [act(), act({ id: 'a2', name: 'Muse', row: 3 })] }),
    );
    api.importResolve.mockResolvedValue({
      matches: [
        {
          query: 'Radiohead',
          status: 'matched',
          match: { name: 'Radiohead', entity_id: 'E-RH' },
          candidates: [{ name: 'Radiohead', entity_id: 'E-RH' }],
          note: null,
          cached: false,
        },
        {
          query: 'Muse',
          status: 'ambiguous',
          match: null,
          candidates: [
            { name: 'Muse', entity_id: 'E-M1', short_description: 'English rock band' },
            { name: 'Muse', entity_id: 'E-M2', short_description: 'K-pop group' },
          ],
          note: 'Several plausible matches — confirm which artist this is.',
          cached: false,
        },
      ],
      resolved: 1,
      needs_confirmation: 1,
      unresolved: 0,
      failed: 0,
      note: '',
    });
    const onImport = vi.fn();
    renderPanel({ onImport });
    await parseInto(user);
    await user.click(await screen.findByRole('button', { name: /match artists/i }));

    expect(await screen.findByText(/1 of 2 artist\(s\) matched/)).toBeInTheDocument();
    expect(screen.getByText('needs confirmation')).toBeInTheDocument();

    // ambiguous names are never guessed: building now imports Muse without taste data
    await user.click(screen.getByRole('button', { name: /build schedule/i }));
    expect(onImport).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Sample Festival',
        acts: [
          expect.objectContaining({ name: 'Radiohead', entity_id: 'E-RH' }),
          expect.objectContaining({ name: 'Muse', entity_id: 'unmatched:a2' }),
        ],
        unmatched: 1,
      }),
    );

    onImport.mockClear();
    await parseInto(user);
    await user.click(await screen.findByRole('button', { name: /match artists/i }));
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(2);
    await user.click(radios[1]);
    expect(screen.getByText('→ Muse')).toBeInTheDocument();
    expect(screen.getByText('confirmed')).toBeInTheDocument();
    expect(screen.queryByText('needs confirmation')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /build schedule/i }));
    expect(onImport).toHaveBeenCalledWith(
      expect.objectContaining({
        acts: [
          expect.objectContaining({ entity_id: 'E-RH' }),
          expect.objectContaining({ name: 'Muse', entity_id: 'E-M2' }),
        ],
        unmatched: 0,
      }),
    );
  });

  it('reports not-found and failed lookups, and retries a single name', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(
      parsed({
        acts: [
          act(),
          act({ id: 'a2', name: 'NoSuchBand', row: 3 }),
          act({ id: 'a3', name: 'Broken Act', row: 4 }),
        ],
      }),
    );
    api.importResolve.mockResolvedValue({
      matches: [
        {
          query: 'Radiohead',
          status: 'matched',
          match: { name: 'Radiohead', entity_id: 'E-RH' },
          candidates: [{ name: 'Radiohead', entity_id: 'E-RH' }],
          note: null,
          cached: true,
        },
        {
          query: 'NoSuchBand',
          status: 'not_found',
          match: null,
          candidates: [],
          note: 'Qloo returned no artist for this name.',
          cached: false,
        },
        {
          query: 'Broken Act',
          status: 'error',
          match: null,
          candidates: [],
          note: 'Qloo request timed out: /search',
          cached: false,
        },
      ],
      resolved: 1,
      needs_confirmation: 0,
      unresolved: 1,
      failed: 1,
      note: '',
    });
    renderPanel();
    await parseInto(user);
    await user.click(await screen.findByRole('button', { name: /match artists/i }));

    expect(await screen.findByText('not found')).toBeInTheDocument();
    expect(screen.getByText('lookup failed')).toBeInTheDocument();
    expect(screen.getByText('matched · cached')).toBeInTheDocument();
    expect(screen.getByText(/Check the spelling, or import it as-is/)).toBeInTheDocument();
    expect(api.importResolve).toHaveBeenCalledTimes(1);

    api.importResolve.mockResolvedValueOnce({
      matches: [
        {
          query: 'Broken Act',
          status: 'matched',
          match: { name: 'Broken Act', entity_id: 'E-BA' },
          candidates: [{ name: 'Broken Act', entity_id: 'E-BA' }],
          note: null,
          cached: false,
        },
      ],
      resolved: 1,
      needs_confirmation: 0,
      unresolved: 0,
      failed: 0,
      note: '',
    });
    await user.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText('→ Broken Act')).toBeInTheDocument();
    expect(api.importResolve).toHaveBeenLastCalledWith(['Broken Act']);
  });

  it('imports without Qloo matching when no key is configured', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed());
    const onImport = vi.fn();
    renderPanel({ qlooConfigured: false, onImport });
    await parseInto(user);

    expect(await screen.findByText('no api key')).toBeInTheDocument();
    expect(
      screen.getByText(/excluded from similarity scoring rather than scored as/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /match artists/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /match artists on qloo/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /build schedule/i }));
    expect(onImport).toHaveBeenCalledWith(
      expect.objectContaining({
        acts: [expect.objectContaining({ name: 'Radiohead', entity_id: 'unmatched:a1' })],
        unmatched: 1,
      }),
    );
    expect(api.importResolve).not.toHaveBeenCalled();
  });

  it('surfaces a resolve failure instead of silently continuing', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed());
    api.importResolve.mockRejectedValue(
      Object.assign(new Error('QLOO_API_KEY is not set'), { code: 'QLOO_NOT_CONFIGURED' }),
    );
    renderPanel();
    await parseInto(user);
    await user.click(await screen.findByRole('button', { name: /match artists/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('QLOO_API_KEY is not set');
    expect(screen.queryByText(/artist\(s\) matched/)).not.toBeInTheDocument();
  });

  it('keeps the paste and the preview when the build is refused', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed());
    const onImport = vi.fn().mockResolvedValue(false);
    renderPanel({ onImport });
    await parseInto(user);

    await user.click(await screen.findByRole('button', { name: /build schedule/i }));

    // A refused build used to clear the panel, so the user had to retype a lineup
    // that was never at fault. The paste and the preview must survive the failure.
    expect(await screen.findByRole('status')).toHaveTextContent(/was not built/i);
    expect(screen.getByLabelText(/paste a lineup/i)).toHaveValue('Radiohead,Main Stage,19:00,20:00');
    expect(document.querySelector('.schedule-grid')).not.toBeNull();
    expect(onImport).toHaveBeenCalledTimes(1);
  });

  it('clears the refusal note once the lineup parses again', async () => {
    const user = userEvent.setup();
    api.importParse.mockResolvedValue(parsed());
    renderPanel({ onImport: vi.fn().mockResolvedValue(false) });
    await parseInto(user);
    await user.click(await screen.findByRole('button', { name: /build schedule/i }));
    await screen.findByText(/was not built/i);

    await user.click(screen.getByRole('button', { name: /parse lineup/i }));
    expect(screen.queryByText(/was not built/i)).not.toBeInTheDocument();
  });
});
