import { prettyTag } from '../tagLabels.js';
import { signalMath } from '../signalMath.js';

function severity(value) {
  if (value >= 0.4) return { label: 'High', stamp: 'stamp-clash' };
  if (value >= 0.15) return { label: 'Medium', stamp: 'stamp-accent' };
  return { label: 'Low', stamp: '' };
}

const signalLines = (clash) =>
  (clash.signals ?? []).map((signal) => `${signal.label} ${signalMath(signal)}`);

const sharedNames = (clash) =>
  (clash.signals ?? [])
    .flatMap((signal) => signal.shared_tags.map((tag) => `${prettyTag(tag)} (${signal.label})`))
    .slice(0, 6);

export default function ClashSummary({
  clashes,
  excluded,
  fixedClashes = [],
  applied,
  actsById,
  stages,
  slots,
}) {
  // The optimizer reports stage and slot ids; the report must read like the grid
  // the user is looking at, not like the database row behind it.
  const stageName = (id) => (stages ?? []).find((s) => s.id === id)?.name ?? id;
  const slotName = (id) => (slots ?? []).find((s) => s.id === id)?.label ?? id;
  const sorted = [...(clashes ?? [])].sort((a, b) => b.similarity - a.similarity);
  const fixedSet = new Set(
    Object.values(actsById ?? {})
      .filter((a) => a.fixed)
      .map((a) => a.id),
  );

  if (!sorted.length && !(excluded ?? []).length && !fixedClashes.length) {
    return (
      <p className="empty-state ok">
        No clashes in this schedule{applied ? ' — every fixable overlap was resolved.' : '.'}
      </p>
    );
  }

  return (
    <div>
      {sorted.length === 0 ? (
        <p className="empty-state ok">No simultaneous similar-artist pairs in this schedule.</p>
      ) : (
        <ul className="clash-list">
          {sorted.map((clash, index) => {
            const bothFixed = fixedSet.has(clash.a_id) && fixedSet.has(clash.b_id);
            const sev = severity(clash.similarity);
            return (
              <li key={`${clash.a_id}-${clash.b_id}-${index}`} className="clash-row">
                <span
                  className={`stamp ${sev.stamp}`}
                  title={`Estimated taste similarity band: ${sev.label}`}
                >
                  {sev.label}
                </span>
                <span className="clash-pair">
                  <strong>{clash.a_name}</strong>{' '}
                  <span className="clash-stage">
                    {stageName(clash.stage_a)} @ {slotName(clash.slot_a)}
                  </span>
                  {' vs '}
                  <strong>{clash.b_name}</strong>{' '}
                  <span className="clash-stage">
                    {stageName(clash.stage_b)} @ {slotName(clash.slot_b)}
                  </span>
                </span>
                <span
                  className="clash-sim"
                  title={`Estimated taste similarity, not a measured audience-overlap share\n${signalLines(clash).join('\n')}`}
                >
                  {(clash.similarity * 100).toFixed(0)}%
                </span>
                <span
                  className="stamp"
                  title={`Scoring method: ${clash.method} — weighted Jaccard over the tag categories both artists have`}
                >
                  {clash.method}
                </span>
                {clash.low_confidence && (
                  <span className="stamp stamp-warn" title={clash.confidence_note ?? ''}>
                    thin evidence
                  </span>
                )}
                {bothFixed && (
                  <span className="stamp stamp-fixed" title="Locked headliners — cannot move">
                    fixed
                  </span>
                )}
                {(clash.signals ?? []).length > 0 && (
                  <div className="clash-signals">
                    {signalLines(clash).join(' · ')}
                    {sharedNames(clash).length > 0 && ` — shared: ${sharedNames(clash).join(', ')}`}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {fixedClashes.length > 0 && (
        <div className="excluded-block fixed-block">
          <h3>Fixed by organizer (locked headliners)</h3>
          <ul className="excluded-list">
            {fixedClashes.map((pair, index) => (
              <li key={`${pair.a_id}-${pair.b_id}-${index}`}>
                <span className="stamp stamp-fixed">locked</span>
                <span>
                  {pair.a_name} × {pair.b_name} — both acts are locked, so the optimizer
                  cannot separate them.
                  {pair.similarity != null ? ` Estimated similarity ${(pair.similarity * 100).toFixed(0)}%.` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(excluded ?? []).length > 0 && (
        <div className="excluded-block">
          <h3>Excluded from scoring (missing data)</h3>
          <ul className="excluded-list">
            {excluded.map((pair, index) => (
              <li key={`${pair.a_name}-${pair.b_name}-${index}`}>
                <span className="stamp stamp-missing">excluded</span>
                <span>
                  {pair.a_name} × {pair.b_name} — {pair.reason}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
