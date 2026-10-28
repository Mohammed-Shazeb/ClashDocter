import { memo, useMemo } from 'react';
import { prettyTag } from '../tagLabels.js';
import { signalMath } from '../signalMath.js';

// Single-hue warm severity ramp: sand (0) → apricot (0.25) → vermillion (0.5) → burnt umber (1)
const RAMP_STOPS = [
  [0, [241, 236, 224]],
  [0.25, [232, 180, 140]],
  [0.5, [194, 65, 12]],
  [1, [124, 45, 18]],
];

function heatColor(value) {
  let lo = RAMP_STOPS[0];
  let hi = RAMP_STOPS[RAMP_STOPS.length - 1];
  for (let i = 0; i < RAMP_STOPS.length - 1; i++) {
    if (value >= RAMP_STOPS[i][0] && value <= RAMP_STOPS[i + 1][0]) {
      lo = RAMP_STOPS[i];
      hi = RAMP_STOPS[i + 1];
      break;
    }
  }
  const t = (value - lo[0]) / (hi[0] - lo[0] || 1);
  const [r, g, b] = lo[1].map((c, i) => Math.round(c + (hi[1][i] - c) * t));
  return `rgb(${r}, ${g}, ${b})`;
}

// Dark cells get light text; light cells get ink (≥4.5:1 for printed values)
function cellTextColor(value) {
  return value >= 0.45 ? '#fffdf9' : 'var(--ink)';
}

export default function SimilarityHeatmap({ acts, similarity, ringPairs }) {
  const pairMap = useMemo(() => {
    const map = {};
    for (const pair of similarity?.pairs ?? []) {
      map[`${pair.a}|${pair.b}`] = pair;
      map[`${pair.b}|${pair.a}`] = pair;
    }
    return map;
  }, [similarity]);

  if (!acts.length) return <p className="empty-state">Add artists to see similarity.</p>;

  return (
    <div className="heatmap-wrap">
      <div
        className="heatmap"
        style={{
          gridTemplateColumns: `minmax(90px, 150px) repeat(${acts.length}, minmax(54px, 1fr))`,
        }}
      >
        <div className="hm-corner">taste blend</div>
        {acts.map((act) => (
          <div key={act.id} className="hm-head" title={act.name}>
            {act.name}
          </div>
        ))}
        {acts.map((rowAct) => (
          <HeatmapRow
            key={rowAct.id}
            rowAct={rowAct}
            acts={acts}
            pairMap={pairMap}
            ringPairs={ringPairs}
          />
        ))}
      </div>
      <div className="legend">
        <span>estimated taste similarity</span>
        <span className="legend-ramp" role="img" aria-label="Similarity scale from sand to dark red" />
        <span>0</span>
        <span className="legend-band">low</span>
        <span>0.25</span>
        <span className="legend-band">medium</span>
        <span>0.5</span>
        <span className="legend-band">high</span>
        <span>1.0</span>
        <span className="legend-swatch" />
        <span>no data</span>
        <span className="legend-band">* low confidence — thin tag evidence</span>
        <span className="legend-band">ringed cell = clash, both acts play at the same time</span>
      </div>
    </div>
  );
}

// One row builds a multi-line tooltip per cell; with a 50+ act lineup that is
// thousands of strings, so rows only re-render when their own inputs change.
const HeatmapRow = memo(function HeatmapRow({ rowAct, acts, pairMap, ringPairs }) {
  return (
    <>
      <div className="hm-row-label" title={rowAct.name}>
        {rowAct.name}
      </div>
      {acts.map((colAct) => {
        const pair = pairMap[`${rowAct.entity_id}|${colAct.entity_id}`];
        const isSelf = rowAct.entity_id === colAct.entity_id;
        // A matrix can be missing an entry entirely — an act added while the
        // previous lineup's request was still in flight, or a pair the engine
        // never scored. That is absent evidence, not a zero, and it must not
        // dereference a score that is not there.
        const value = pair && !pair.missing ? (pair.taste_similarity ?? null) : null;
        const noData = !isSelf && (pair === undefined || pair.missing || value === null);
        const isRing = ringPairs?.has(`${rowAct.entity_id}|${colAct.entity_id}`) ?? false;
        let title = rowAct.name;
        if (!isSelf && noData) {
          title = `${rowAct.name} vs ${colAct.name}: no comparable taste data${
            pair?.missing_reason ? ` — ${pair.missing_reason}` : ''
          }`;
        } else if (!isSelf && pair) {
          const lines = [
            `${rowAct.name} vs ${colAct.name} — estimated taste similarity ${value.toFixed(3)}`,
            ...pair.signals.map(
              (s) =>
                `  ${s.label} ${signalMath(s)}` +
                (s.shared_tags.length
                  ? ` (${s.shared_tags.map(prettyTag).join(', ')})`
                  : ' (no shared tags)'),
            ),
            ...pair.skipped_categories.map((s) => `  skipped ${s.label}: ${s.reason}`),
            `  reference: genre ${pair.genre_similarity?.toFixed(3) ?? 'n/a'} / combined ${pair.combined_similarity?.toFixed(3) ?? 'n/a'}`,
          ];
          if (pair.low_confidence) lines.push(`  low confidence: ${pair.confidence_note}`);
          if (isRing) lines.push('  clash: scheduled simultaneously');
          title = lines.join('\n');
        }
        const cls = [
          'hm-cell',
          isSelf ? 'self' : '',
          noData ? 'missing' : '',
          pair?.low_confidence ? 'thin' : '',
          isRing ? 'ring' : '',
        ]
          .filter(Boolean)
          .join(' ');
        // The ring and the fill are the only clash cue on the cell, so the cell
        // carries the same facts as text for anyone who cannot see the colour.
        let label = `${rowAct.name} versus ${colAct.name}`;
        if (isSelf) label = `${rowAct.name}, same artist`;
        else if (noData) label += ': no comparable taste data';
        else
          label += `: estimated taste similarity ${value.toFixed(2)}${
            pair.low_confidence ? ', low confidence' : ''
          }${isRing ? ', clash — scheduled simultaneously' : ''}`;
        return (
          <div
            key={colAct.id}
            className={cls}
            role="img"
            aria-label={label}
            style={
              isSelf || noData
                ? undefined
                : { background: heatColor(value), color: cellTextColor(value) }
            }
            title={title}
          >
            {!isSelf &&
              (noData ? '–' : `${value.toFixed(2)}${pair.low_confidence ? '*' : ''}`)}
          </div>
        );
      })}
    </>
  );
});
