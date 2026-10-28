import { prettyTag } from '../tagLabels.js';
import { signalMath } from '../signalMath.js';

const MAX_ROWS = 6;

function fmt(value, digits = 3) {
  return value === null || value === undefined ? 'n/a' : value.toFixed(digits);
}

export default function PairEvidence({ similarity, acts }) {
  const pairs = similarity?.pairs ?? [];
  const coverage = similarity?.coverage;
  if (!coverage || !pairs.length) return null;

  const names = {};
  for (const act of acts ?? []) names[act.entity_id] = act.name;
  for (const profile of similarity.profiles ?? []) {
    if (profile.name && !names[profile.entity_id]) names[profile.entity_id] = profile.name;
  }
  const label = (id) => names[id] ?? id;

  const scored = pairs
    .filter((pair) => !pair.missing)
    .sort((a, b) => b.taste_similarity - a.taste_similarity);
  const top = scored.slice(0, MAX_ROWS);

  return (
    <div className="evidence">
      <div className="evidence-coverage">
        <h3>Data coverage</h3>
        <p className="coverage-line">
          <strong>
            {coverage.profiles_with_data}/{coverage.profiles_total}
          </strong>{' '}
          acts carry taste tags ·{' '}
          <strong>
            {coverage.pairs_scored}/{coverage.pairs_total}
          </strong>{' '}
          pairs comparable ·{' '}
          <strong>
            {coverage.pairs_missing} excluded · {coverage.pairs_low_confidence} low confidence
          </strong>
        </p>
        <ul className="coverage-cats">
          {Object.entries(coverage.category_coverage ?? {}).map(([category, stats]) => (
            <li key={category} className="coverage-cat">
              <span className="stamp">{stats.label}</span>
              <span className="coverage-count">
                {stats.artists} of {coverage.profiles_with_data} tagged acts
              </span>
              <span className="coverage-weight">weight {stats.weight.toFixed(2)}</span>
              {stats.artists === 0 ? (
                <span className="stamp stamp-missing">no data</span>
              ) : stats.artists < coverage.profiles_with_data ? (
                <span
                  className="stamp stamp-warn"
                  title={`An act with taste tags has no ${stats.label} tags — that category is skipped for those pairs`}
                >
                  partial
                </span>
              ) : (
                <span className="stamp stamp-ok">complete</span>
              )}
            </li>
          ))}
        </ul>
        {similarity.methods?.taste_blend && (
          <p className="coverage-method">{similarity.methods.taste_blend}</p>
        )}
      </div>

      {top.length > 0 && (
        <div className="evidence-pairs">
          <h3>Strongest estimated affinities</h3>
          <p className="evidence-note">
            Scores are tag-overlap estimates, not shared fans or verified audience overlap. Each
            line shows the tag categories both artists actually have and what each contributed.
          </p>
          <ul className="affinity-list">
            {top.map((pair) => (
              <li key={`${pair.a}|${pair.b}`} className="affinity-row">
                <div className="affinity-head">
                  <span className="affinity-pair">
                    <strong>{label(pair.a)}</strong> × <strong>{label(pair.b)}</strong>
                  </span>
                  {pair.low_confidence && (
                    <span className="stamp stamp-warn" title={pair.confidence_note}>
                      low confidence
                    </span>
                  )}
                  {pair.skipped_categories.map((skipped) => (
                    <span
                      key={skipped.category}
                      className="stamp stamp-missing"
                      title={`${skipped.reason} — this category is not compared`}
                    >
                      no {skipped.label} data
                    </span>
                  ))}
                  <span className="affinity-score" title="Estimated taste similarity">
                    {fmt(pair.taste_similarity)}
                  </span>
                </div>
                {pair.low_confidence && (
                  <div className="affinity-thin">low confidence — {pair.confidence_note}</div>
                )}
                <ul className="affinity-signals">
                  {pair.signals.map((signal) => (
                    <li key={signal.category} className="signal">
                      <span className="signal-label">{signal.label}</span>
                      <span className="signal-math">{signalMath(signal)}</span>
                      <span className="signal-tags">
                        {signal.shared_count
                          ? `${signal.shared_count}/${signal.union_count} shared: ${signal.shared_tags.map(prettyTag).join(', ')}`
                          : `no overlap in ${signal.union_count} tag(s)`}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="affinity-evidence">
                  <span className={`stamp ${pair.genre_backed ? 'stamp-ok' : 'stamp-warn'}`}>
                    {pair.genre_backed ? 'genre-backed' : 'no genre comparison'}
                  </span>
                  <span title="Shared tags are generic when at least a quarter of the tagged acts in this lineup carry them (minimum 3 acts and 6 tagged acts)">
                    {pair.shared_generic_tag_count ?? 0}/{pair.shared_tag_count ?? 0} generic ·{' '}
                    {pair.shared_specific_tag_count ?? 0}/{pair.shared_tag_count ?? 0} specific
                  </span>
                  <span
                    title="Share of shared tags that are generic in this lineup"
                  >
                    generic share {Math.round((pair.generic_share ?? 0) * 100)}%
                  </span>
                  <span>
                    sources: {pair.profile_sources?.a ?? 'unknown'} /{' '}
                    {pair.profile_sources?.b ?? 'unknown'}
                  </span>
                </div>
                {pair.evidence_limitations?.length > 0 && (
                  <ul className="affinity-limits">
                    {pair.evidence_limitations.map((limitation) => (
                      <li key={limitation}>{limitation}</li>
                    ))}
                  </ul>
                )}
                <div className="affinity-refs">
                  reference — genre-only {fmt(pair.genre_similarity)} · combined {fmt(pair.combined_similarity)}
                </div>
              </li>
            ))}
          </ul>
          {scored.length > top.length && (
            <p className="evidence-note">
              Showing the {top.length} strongest of {scored.length} comparable pairs. Hover any
              heatmap cell for the same breakdown.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
