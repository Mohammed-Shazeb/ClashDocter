import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ClashSummary from './ClashSummary.jsx';

const signal = {
  category: 'genre',
  label: 'music genre',
  weight: 0.55,
  normalized_weight: 0.7333,
  jaccard: 0.5,
  shared_count: 2,
  union_count: 4,
  contribution: 0.3667,
  shared_tags: ['urn:tag:genre:music:shoegaze', 'urn:tag:genre:music:dream pop'],
};

const clash = {
  a_id: 'a1',
  a_name: 'Alpha Waves',
  b_id: 'a2',
  b_name: 'Beta Waves',
  stage_a: 'main',
  stage_b: 'pulse',
  slot_a: 't3',
  slot_b: 't3',
  similarity: 0.6333,
  method: 'taste_blend',
  signals: [signal],
};

describe('ClashSummary', () => {
  it('explains which signals produced each clash', () => {
    const { container } = render(<ClashSummary clashes={[clash]} excluded={[]} actsById={{}} />);
    const line = container.querySelector('.clash-signals');
    expect(line.textContent).toContain('music genre 0.500 × 0.733 = +0.367');
    expect(line.textContent).toContain('shared: shoegaze (music genre), dream pop (music genre)');
    expect(container.textContent).not.toContain('urn:tag');
  });

  it('bands severity and marks the scoring method', () => {
    render(<ClashSummary clashes={[clash]} excluded={[]} actsById={{}} />);
    expect(screen.getByText('High')).toBeInTheDocument(); // >= 0.4
    expect(screen.getByText('63%')).toBeInTheDocument();
    expect(screen.getByText('taste_blend')).toBeInTheDocument();
    expect(screen.queryByText('thin evidence')).not.toBeInTheDocument();
  });

  it('names the stages and slots instead of printing their ids', () => {
    const { container } = render(
      <ClashSummary
        clashes={[clash]}
        excluded={[]}
        actsById={{}}
        stages={[{ id: 'main', name: 'Main Stage' }, { id: 'pulse', name: 'Pulse Tent' }]}
        slots={[{ id: 't3', label: '19:00', start: '19:00', end: '20:00' }]}
      />,
    );
    const stages = container.querySelectorAll('.clash-stage');
    expect(stages[0].textContent).toBe('Main Stage @ 19:00');
    expect(stages[1].textContent).toBe('Pulse Tent @ 19:00');
    expect(container.textContent).not.toContain('t3');
  });

  it('still shows the id when a stage is no longer in the lineup', () => {
    const { container } = render(
      <ClashSummary
        clashes={[clash]}
        excluded={[]}
        actsById={{}}
        stages={[{ id: 'pulse', name: 'Pulse Tent' }]}
        slots={[]}
      />,
    );
    expect(container.querySelector('.clash-stage').textContent).toBe('main @ t3');
  });

  it('flags a clash whose score rests on thin evidence', () => {
    render(
      <ClashSummary
        clashes={[
          {
            ...clash,
            low_confidence: true,
            confidence_note: 'compared on 1 signal only (music genre) — thin evidence',
          },
        ]}
        excluded={[]}
        actsById={{}}
      />,
    );
    const stamp = screen.getByText('thin evidence');
    expect(stamp).toHaveClass('stamp-warn');
    expect(stamp.getAttribute('title')).toBe(
      'compared on 1 signal only (music genre) — thin evidence',
    );
  });

  it('marks a clash that two locked headliners cannot resolve', () => {
    render(
      <ClashSummary
        clashes={[clash]}
        excluded={[]}
        actsById={{ a1: { id: 'a1', fixed: true }, a2: { id: 'a2', fixed: true } }}
      />,
    );
    expect(screen.getByText('fixed')).toBeInTheDocument();
  });

  it('gives fixed-headliner clashes their own category, not a missing-data label', () => {
    render(
      <ClashSummary
        clashes={[]}
        excluded={[]}
        fixedClashes={[
          {
            a_id: 'a1',
            a_name: 'Alpha Waves',
            b_id: 'a2',
            b_name: 'Beta Waves',
            similarity: 0.6,
          },
        ]}
        actsById={{}}
      />,
    );
    expect(screen.getByText('Fixed by organizer (locked headliners)')).toBeInTheDocument();
    expect(screen.queryByText('Excluded from scoring (missing data)')).not.toBeInTheDocument();
    expect(screen.getByText('locked')).toHaveClass('stamp-fixed');
    expect(screen.getByText(/both acts are locked/)).toBeInTheDocument();
  });

  it('lists excluded pairs instead of scoring them as zero', () => {
    render(
      <ClashSummary
        clashes={[]}
        excluded={[
          {
            a_name: 'Alpha Waves',
            b_name: 'No Profile',
            reason: 'Missing taste profile for at least one artist — excluded from the objective.',
          },
        ]}
        actsById={{}}
      />,
    );
    expect(screen.getByText('Excluded from scoring (missing data)')).toBeInTheDocument();
    expect(screen.getByText('excluded')).toBeInTheDocument();
    expect(screen.getByText(/Missing taste profile/)).toBeInTheDocument();
  });

  it('says so when there is nothing to report', () => {
    render(<ClashSummary clashes={[]} excluded={[]} actsById={{}} />);
    expect(screen.getByText('No clashes in this schedule.')).toBeInTheDocument();
  });

  it('marks resolved clashes when the optimized schedule is applied', () => {
    render(<ClashSummary clashes={[]} excluded={[]} applied actsById={{}} />);
    expect(
      screen.getByText('No clashes in this schedule — every fixable overlap was resolved.'),
    ).toBeInTheDocument();
  });
});
