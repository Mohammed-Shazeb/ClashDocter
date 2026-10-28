import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PairEvidence from './PairEvidence.jsx';

const similarity = {
  mode: 'live',
  methods: {
    taste_blend:
      'Estimated taste similarity: weighted average of per-category Jaccard scores over genre .55 / audience .20 / style .15 / other music .10, renormalized across only the categories both artists have.',
  },
  coverage: {
    profiles_total: 3,
    profiles_with_data: 2,
    profiles_missing: 1,
    pairs_total: 3,
    pairs_scored: 1,
    pairs_missing: 2,
    pairs_low_confidence: 1,
    thin_categories: ['audience', 'other music'],
    category_coverage: {
      genre: { label: 'music genre', artists: 2, of: 3, weight: 0.55 },
      audience: { label: 'audience', artists: 1, of: 3, weight: 0.2 },
      style: { label: 'style', artists: 2, of: 3, weight: 0.15 },
      music: { label: 'other music', artists: 0, of: 3, weight: 0.1 },
    },
  },
  profiles: [
    { entity_id: 'e1', name: 'Alpha Waves', missing: false },
    { entity_id: 'e2', name: 'Beta Waves', missing: false },
    { entity_id: 'e3', name: 'No Profile', missing: true },
  ],
  pairs: [
    {
      a: 'e1',
      b: 'e2',
      taste_similarity: 0.6333,
      genre_similarity: 0.5,
      combined_similarity: 0.4,
      categories_compared: ['genre', 'audience'],
      low_confidence: true,
      confidence_note: 'only 5 tag(s) available across both artists — thin evidence',
      skipped_categories: [
        { category: 'style', label: 'style', reason: 'only Beta Waves has style tags' },
      ],
      signals: [
        {
          category: 'genre',
          label: 'music genre',
          weight: 0.55,
          normalized_weight: 0.7333,
          jaccard: 0.5,
          shared_count: 2,
          union_count: 4,
          contribution: 0.3667,
          shared_tags: ['dream pop', 'shoegaze'],
        },
        {
          category: 'audience',
          label: 'audience',
          weight: 0.2,
          normalized_weight: 0.2667,
          jaccard: 1,
          shared_count: 1,
          union_count: 1,
          contribution: 0.2667,
          shared_tags: ['festival goers'],
        },
      ],
      missing: false,
      missing_reason: null,
      genre_backed: true,
      shared_tags: ['dream pop', 'shoegaze', 'festival goers'],
      shared_tag_count: 3,
      shared_generic_tags: ['festival goers'],
      shared_generic_tag_count: 1,
      generic_share: 0.3333,
      shared_specific_tags: ['dream pop', 'shoegaze'],
      shared_specific_tag_count: 2,
      shared_broad_tags: ['festival goers'],
      broad_share: 0.3333,
      profile_sources: { a: 'qloo-insights', b: 'qloo-search' },
      evidence_limitations: ['only 3 tag(s) available across both artists'],
    },
    {
      a: 'e1',
      b: 'e3',
      taste_similarity: null,
      genre_similarity: null,
      combined_similarity: null,
      categories_compared: [],
      low_confidence: false,
      signals: [],
      skipped_categories: [],
      missing: true,
      missing_reason: 'e3: missing taste profile',
    },
  ],
};

const acts = [
  { id: 'a1', entity_id: 'e1', name: 'Alpha Waves' },
  { id: 'a2', entity_id: 'e2', name: 'Beta Waves' },
];

describe('PairEvidence', () => {
  it('reports how much of the lineup can actually be compared', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(screen.getByText('Data coverage')).toBeInTheDocument();
    expect(container.textContent).toContain('2/3');
    expect(container.textContent).toContain('1/3');
    expect(container.textContent).toContain('2 excluded · 1 low confidence');
    expect(screen.getAllByText('music genre').length).toBeGreaterThan(0);
    expect(screen.getByText('weight 0.55')).toBeInTheDocument();
  });

  it('marks categories with partial or absent coverage among tagged acts', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(screen.getByText('partial')).toBeInTheDocument(); // audience: 1 of 2 tagged acts
    expect(screen.getByText('no data')).toBeInTheDocument(); // music: no act carries it
    expect(screen.getAllByText('complete')).toHaveLength(2); // genre + style: both tagged acts
    expect(container.textContent).toContain('0 of 2 tagged acts');
    expect(container.textContent).toContain('2 of 2 tagged acts');
    expect(
      screen.getByTitle('An act with taste tags has no audience tags — that category is skipped for those pairs'),
    ).toHaveClass('stamp-warn');
  });

  it('explains which shared signals produced each score', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(screen.getByText('Strongest estimated affinities')).toBeInTheDocument();
    expect(screen.getByText('0.633')).toBeInTheDocument();
    expect(container.textContent).toContain('2/4 shared: dream pop, shoegaze');
    expect(container.textContent).toContain('1/1 shared: festival goers');
    expect(container.textContent).toContain('reference — genre-only 0.500 · combined 0.400');
  });

  it('prints the multiplication a reader can check with what is displayed', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    const math = [...container.querySelectorAll('.signal-math')].map((el) => el.textContent);
    expect(math).toEqual(['0.500 × 0.733 = +0.367', '1.000 × 0.267 = +0.267']);
    for (const line of math) {
      const [, left, weight, shown] = line.match(/([\d.]+) × ([\d.]+) = \+([\d.]+)/);
      // tolerance = one last digit: the product of what is displayed must be what is displayed
      expect(Math.abs(parseFloat(shown) - parseFloat(left) * parseFloat(weight))).toBeLessThan(
        0.001,
      );
    }
  });

  it('flags thin evidence and the categories that were skipped', () => {
    render(<PairEvidence similarity={similarity} acts={acts} />);
    const lowConfidence = screen.getByText('low confidence');
    expect(lowConfidence).toBeInTheDocument();
    expect(lowConfidence.closest('.stamp')).toHaveClass('stamp-warn');
    expect(screen.getByText('no style data')).toBeInTheDocument();
    expect(
      screen.getByTitle('only Beta Waves has style tags — this category is not compared'),
    ).toHaveClass('stamp-missing');
    expect(
      screen.getByText('low confidence — only 5 tag(s) available across both artists — thin evidence'),
    ).toBeInTheDocument();
  });

  it('shows the evidence behind each score, not just the number', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(screen.getByText('genre-backed')).toHaveClass('stamp-ok');
    expect(screen.getByText(/1\/3 generic · 2\/3 specific/)).toBeInTheDocument();
    expect(screen.getByText(/generic share 33%/)).toBeInTheDocument();
    expect(screen.getByText(/sources: qloo-insights \/ qloo-search/)).toBeInTheDocument();
    expect(container.textContent).toContain('only 3 tag(s) available across both artists');
  });

  it('marks a comparison where genre is unavailable on one side', () => {
    const noGenre = {
      ...similarity,
      pairs: [
        {
          ...similarity.pairs[0],
          genre_similarity: null,
          genre_backed: false,
          evidence_limitations: ['no music-genre category on both sides'],
        },
      ],
    };
    render(<PairEvidence similarity={noGenre} acts={acts} />);
    expect(screen.getByText('no genre comparison')).toHaveClass('stamp-warn');
  });

  it('keeps the disclaimer and the documented method visible', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(container.textContent).toContain('not shared fans or verified audience overlap');
    expect(container.textContent).toContain('renormalized across only the categories both artists have');
  });

  it('omits missing pairs from the affinity ranking', () => {
    const { container } = render(<PairEvidence similarity={similarity} acts={acts} />);
    expect(container.querySelectorAll('.affinity-row')).toHaveLength(1);
    expect(container.textContent).not.toContain('No Profile');
  });

  it('renders nothing without coverage data', () => {
    const { container } = render(<PairEvidence similarity={null} acts={acts} />);
    expect(container.firstChild).toBeNull();
    render(<PairEvidence similarity={{ pairs: [], coverage: {} }} acts={acts} />);
  });
});
