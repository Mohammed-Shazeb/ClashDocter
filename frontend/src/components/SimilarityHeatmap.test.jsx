import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SimilarityHeatmap from './SimilarityHeatmap.jsx';

const ACTS = [
  { id: 'a1', name: 'Alpha Waves', entity_id: 'e1' },
  { id: 'a2', name: 'Beta Choir', entity_id: 'e2' },
];

const pair = (a, b, overrides = {}) => ({
  a,
  b,
  taste_similarity: 0.618,
  genre_similarity: 0.6,
  combined_similarity: 0.62,
  signals: [],
  skipped_categories: [],
  missing: false,
  missing_reason: '',
  low_confidence: false,
  confidence_note: null,
  ...overrides,
});

const matrix = (pairs) => ({ mode: 'demo', profiles: [], pairs, coverage: null, warnings: [] });

const cells = () =>
  Array.from(document.querySelectorAll('.hm-cell')).map((cell) => ({
    text: cell.textContent,
    label: cell.getAttribute('aria-label'),
    className: cell.className,
  }));

describe('SimilarityHeatmap', () => {
  it('says what each scored cell means in words, not only in colour', () => {
    // App builds this set from a clash by inserting both orders, so the mirror
    // image of the matrix rings too.
    render(
      <SimilarityHeatmap
        acts={ACTS}
        similarity={matrix([pair('e1', 'e2')])}
        ringPairs={new Set(['e1|e2', 'e2|e1'])}
      />,
    );
    const offDiagonal = cells().filter((cell) => cell.text === '0.62');
    expect(offDiagonal).toHaveLength(2);
    for (const cell of offDiagonal) {
      expect(cell.label).toContain('estimated taste similarity 0.62');
      expect(cell.label).toContain('clash — scheduled simultaneously');
      expect(cell.className).toContain('ring');
    }
  });

  it('marks a thin-evidence score in the label and with the star', () => {
    render(
      <SimilarityHeatmap
        acts={ACTS}
        similarity={matrix([pair('e1', 'e2', { low_confidence: true, confidence_note: 'one tag' })])}
        ringPairs={new Set()}
      />,
    );
    const scored = cells().filter((cell) => cell.text.startsWith('0.62'));
    expect(scored[0].text).toBe('0.62*');
    expect(scored[0].label).toContain('low confidence');
    expect(scored[0].className).toContain('thin');
  });

  it('renders a pair with no comparable tags as missing, never as zero', () => {
    render(
      <SimilarityHeatmap
        acts={ACTS}
        similarity={matrix([pair('e1', 'e2', { taste_similarity: null, missing: true, missing_reason: 'no shared tag categories' })])}
        ringPairs={new Set()}
      />,
    );
    for (const cell of cells().filter((entry) => entry.text === '–')) {
      expect(cell.label).toContain('no comparable taste data');
      expect(cell.className).toContain('missing');
    }
  });

  it('survives a matrix that is missing an entry entirely', () => {
    render(<SimilarityHeatmap acts={ACTS} similarity={matrix([])} ringPairs={new Set()} />);
    const dashes = cells().filter((cell) => cell.text === '–');
    expect(dashes).toHaveLength(2);
    expect(dashes[0].label).toContain('Alpha Waves versus Beta Choir: no comparable taste data');
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
  });

  it('leaves the diagonal blank and names the artist', () => {
    render(<SimilarityHeatmap acts={ACTS} similarity={matrix([pair('e1', 'e2')])} ringPairs={new Set()} />);
    const diagonal = cells().filter((cell) => cell.className.includes('self'));
    expect(diagonal).toHaveLength(2);
    expect(diagonal[0].text).toBe('');
    expect(diagonal.map((cell) => cell.label)).toEqual(['Alpha Waves, same artist', 'Beta Choir, same artist']);
  });

  it('asks for a lineup before drawing anything', () => {
    render(<SimilarityHeatmap acts={[]} similarity={null} ringPairs={new Set()} />);
    expect(screen.getByText(/Add artists to see similarity/)).toBeInTheDocument();
    expect(document.querySelector('.heatmap')).toBeNull();
  });
});
