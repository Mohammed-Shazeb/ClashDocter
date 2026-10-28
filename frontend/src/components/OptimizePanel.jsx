import { useEffect, useState } from 'react';
import {
  ArrowCounterClockwise,
  ArrowsLeftRight,
  CheckCircle,
  ShieldCheck,
} from '@phosphor-icons/react';

const KIND_STAMP = {
  both_fixed: { label: 'locked', className: 'stamp-clash' },
  no_legal_cell: { label: 'no legal cell', className: 'stamp-clash' },
  worse_objective: { label: 'not worth a change', className: 'stamp-warn' },
  move_limit: { label: 'move limit', className: 'stamp-warn' },
  local_optimum: { label: 'needs more moves', className: 'stamp-warn' },
};

const PRESETS = [
  {
    id: 'clashes',
    label: 'Break every clash',
    hint: 'Treat all estimated similarities equally and ignore how many acts move.',
    preferences: {
      high_affinity_threshold: 0.4,
      high_affinity_weight: 1,
      move_penalty: 0,
      max_moves: 200,
    },
  },
  {
    id: 'affinity',
    label: 'Protect high-affinity pairs',
    hint: 'Pairs at or above the threshold count three times, so they are separated first.',
    preferences: {
      high_affinity_threshold: 0.5,
      high_affinity_weight: 3,
      move_penalty: 0,
      max_moves: 200,
    },
  },
  {
    id: 'churn',
    label: 'Fewest changes',
    hint: 'Each moved act costs the objective, and the search stops after 5 changes.',
    preferences: {
      high_affinity_threshold: 0.4,
      high_affinity_weight: 2,
      move_penalty: 0.5,
      max_moves: 5,
    },
  },
];

const MOVE_CAPS = [3, 5, 10, 20, 200];

const samePreferences = (a, b) =>
  ['high_affinity_threshold', 'high_affinity_weight', 'move_penalty', 'max_moves'].every(
    (key) => Number(a[key]) === Number(b[key]),
  );

const num = (value) => (value == null ? 'n/a' : Number(value).toFixed(3));

const signed = (value) =>
  `${value < 0 ? '−' : '+'}${Math.abs(Number(value)).toFixed(3)}`;

export default function OptimizePanel({
  analysis,
  analyzing,
  applied,
  applying,
  preferences,
  onPreferencesChange,
  onApply,
  onReset,
  stages,
  slots,
  actsById,
}) {
  const [draft, setDraft] = useState(preferences);
  const [dirty, setDirty] = useState(false);

  // The app can replace the priorities without the user touching these controls
  // (a planner brief, a demo reset). The sliders must show the numbers the next
  // plan will use, not the ones they happened to be initialised with.
  useEffect(() => {
    setDraft(preferences);
    setDirty(false);
  }, [preferences]);

  if (!analysis) {
    return <p className="empty-state">Add at least one artist to run the optimizer.</p>;
  }

  // Numbers below were produced by the backend under these priorities — not the
  // ones the sliders currently show, which may still be waiting to be committed.
  const used = analysis.preferences;
  const before = analysis.before;
  const after = analysis.after;
  const pending = dirty && !samePreferences(draft, used);
  const maxObjective = Math.max(before.objective, after.objective, 0.001);
  const objectiveDrop = before.objective - after.objective;
  const percent =
    before.objective > 0 && objectiveDrop > 0
      ? Math.round((objectiveDrop / before.objective) * 1000) / 10
      : null;

  const stageName = (id) => stages.find((s) => s.id === id)?.name ?? id;
  const slotName = (id) => slots.find((s) => s.id === id)?.label ?? id;
  const actName = (id) => actsById?.[id]?.name ?? id;

  const setField = (key, value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };
  const commit = (next) => {
    setDraft(next);
    setDirty(false);
    if (!samePreferences(next, preferences)) onPreferencesChange(next);
  };

  const rows = [
    ['Clash sum (raw)', num(before.raw_cost), num(after.raw_cost)],
    ['Weighted by priority', num(before.weighted_cost), num(after.weighted_cost)],
    ['Cost of changes', num(before.penalty), num(after.penalty)],
    ['Acts moved', String(before.churn), String(after.churn)],
    ['Simultaneous pairs', String(before.clashes), String(after.clashes)],
    [
      'High-affinity pairs',
      String(before.high_affinity_clashes),
      String(after.high_affinity_clashes),
    ],
    ['Pairs without data', String(before.excluded), String(after.excluded)],
  ];

  return (
    <div
      className="panel panel-sticky"
      role="region"
      aria-label="Optimization priorities and the objective they measured"
      tabIndex={0}
    >
      <div className="panel-head">
        <span className="pane-label">Objective, before and after</span>
        {onReset && (
          <button
            className="btn btn-small"
            onClick={onReset}
            title="Reload the seeded demo festival"
          >
            <ArrowCounterClockwise size={13} aria-hidden="true" />
            Reset demo
          </button>
        )}
      </div>

      <fieldset className="priorities">
        <legend className="pane-label">Optimization priorities</legend>
        <div className="preset-row" role="group" aria-label="Priority presets">
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`btn btn-small preset${
                samePreferences(preferences, preset.preferences) ? ' preset-on' : ''
              }`}
              title={preset.hint}
              aria-pressed={samePreferences(preferences, preset.preferences)}
              onClick={() => commit(preset.preferences)}
            >
              {preset.label}
            </button>
          ))}
        </div>

        <label className="priority-field">
          <span>High affinity starts at</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={draft.high_affinity_threshold}
            onChange={(event) => setField('high_affinity_threshold', Number(event.target.value))}
            onPointerUp={() => commit(draft)}
            onKeyUp={() => commit(draft)}
            onBlur={() => commit(draft)}
          />
          <output>{Number(draft.high_affinity_threshold).toFixed(2)}</output>
        </label>

        <label className="priority-field">
          <span>Those pairs count</span>
          <input
            type="range"
            min="1"
            max="10"
            step="0.5"
            value={draft.high_affinity_weight}
            onChange={(event) => setField('high_affinity_weight', Number(event.target.value))}
            onPointerUp={() => commit(draft)}
            onKeyUp={() => commit(draft)}
            onBlur={() => commit(draft)}
          />
          <output>{Number(draft.high_affinity_weight).toFixed(1)}×</output>
        </label>

        <label className="priority-field">
          <span>Cost of moving one act</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={draft.move_penalty}
            onChange={(event) => setField('move_penalty', Number(event.target.value))}
            onPointerUp={() => commit(draft)}
            onKeyUp={() => commit(draft)}
            onBlur={() => commit(draft)}
          />
          <output>{Number(draft.move_penalty).toFixed(2)}</output>
        </label>

        <label className="priority-field">
          <span>Changes allowed</span>
          <select
            value={draft.max_moves}
            onChange={(event) => commit({ ...draft, max_moves: Number(event.target.value) })}
          >
            {MOVE_CAPS.map((cap) => (
              <option key={cap} value={cap}>
                {cap >= 200 ? 'no practical limit' : `at most ${cap}`}
              </option>
            ))}
          </select>
        </label>

        <p className="panel-note">
          <code>{analysis.objective_description}</code>
        </p>
        <p className="panel-note priorities-used">
          <span className="stamp stamp-data">priorities used</span> {analysis.preferences_description}
        </p>
        {pending && (
          <p className="panel-note warn" role="status">
            Sliders changed — the figures above are still the previous plan. Release the control
            to re-plan.
          </p>
        )}
      </fieldset>

      <div className="compare">
        <div className="compare-row">
          <span className="compare-label">Draft</span>
          <span>
            <span className="compare-value before">{num(before.objective)}</span>
            <div className="bar" style={{ marginTop: 4 }}>
              <div
                className="bar-fill before"
                style={{ width: `${(before.objective / maxObjective) * 100}%` }}
              />
            </div>
          </span>
        </div>
        <div className="compare-row">
          <span className="compare-label">Proposed</span>
          <span>
            <span className="compare-value after">{num(after.objective)}</span>
            <div className="bar" style={{ marginTop: 4 }}>
              <div
                className="bar-fill after"
                style={{ width: `${(after.objective / maxObjective) * 100}%` }}
              />
            </div>
          </span>
        </div>
        <div className="compare-row">
          <span className="compare-label">Improvement</span>
          {percent == null ? (
            <span className="compare-value flat">0.000</span>
          ) : (
            <span className="compare-value delta">
              −{num(objectiveDrop)} ({percent}%)
            </span>
          )}
        </div>
      </div>

      <table className="objective-table">
        <thead>
          <tr>
            <th scope="col" className="pane-label">
              Measured
            </th>
            <th scope="col" className="pane-label">
              Draft
            </th>
            <th scope="col" className="pane-label">
              Proposed
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, draftValue, proposed]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{draftValue}</td>
              <td className={draftValue !== proposed ? 'changed' : undefined}>{proposed}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {!analysis.improved && (
        <p className="panel-note warn">
          {analysis.moves.length === 0
            ? 'No change lowers this objective under the current priorities, so nothing is proposed.'
            : 'The objective did not drop, so no improvement is claimed.'}
          {analysis.limit_reached && ' The move limit stopped the search first.'}
        </p>
      )}

      {analysis.moves.length > 0 && (
        <div className="moves">
          <h3>Proposed moves ({analysis.moves.length})</h3>
          <ul>
            {analysis.moves.map((move, index) => (
              <li key={index} className="move-row">
                <span className="move-num">{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <span className="move-title">
                    {move.kind === 'swap' ? 'Swap' : 'Move'} {move.act_name}
                  </span>
                  <span className="move-path">
                    {stageName(move.from_stage)} {slotName(move.from_slot)} →{' '}
                    {stageName(move.to_stage)} {slotName(move.to_slot)}
                  </span>
                  <p className="move-reason">{move.explanation}</p>
                </div>
                <span className="move-cost">
                  <span className="stamp stamp-accent" title="Raw clash cost removed by this move">
                    −{num(move.raw_cost_saved)}
                  </span>
                  <span className="stamp stamp-data" title="Change in the prioritized objective">
                    objective {signed(move.objective_delta)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.moved_acts.length > 0 && (
        <div className="moved-acts">
          <span className="pane-label">Acts that move ({analysis.moved_acts.length})</span>
          <ul>
            {analysis.moved_acts.map((entry) => (
              <li key={entry.act_id}>
                <span className="moved-act-name">{entry.act_name}</span>
                <span className="moved-act-path">
                  {stageName(entry.from_stage)} {slotName(entry.from_slot)} →{' '}
                  {stageName(entry.to_stage)} {slotName(entry.to_slot)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.unresolved.length > 0 && (
        <div className="moves unresolved">
          <h3>Unresolved conflicts ({analysis.unresolved.length})</h3>
          <ul>
            {analysis.unresolved.map((entry, index) => {
              const kind = KIND_STAMP[entry.kind] ?? {
                label: entry.kind,
                className: 'stamp-warn',
              };
              return (
                <li key={index} className="move-row">
                  <span className="move-num">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <span className="move-title">
                      {actName(entry.a_id)} · {actName(entry.b_id)}
                    </span>
                    <span className="move-path">
                      similarity {num(entry.similarity)}
                      {entry.high_affinity ? ' · above the high-affinity line' : ''}
                      {entry.fixed_act
                        ? ` · locked: ${actName(entry.fixed_act)} · movable: ${actName(entry.movable_act)}`
                        : ''}
                    </span>
                    <p className="move-reason">{entry.reason}</p>
                  </div>
                  <span className={`stamp ${kind.className}`}>{kind.label}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {analysis.fixed_clashes.length > 0 && (
        <p className="panel-note warn panel-note-spaced">
          {analysis.fixed_clashes.length} clash(es) involve locked headliners and remain by design
          — the optimizer never moves fixed acts.
        </p>
      )}

      {!analysis.valid && (
        <p className="panel-note panel-note-invalid" role="alert">
          The proposal failed its own constraint check and cannot be applied
          {analysis.validation_issues.length ? `: ${analysis.validation_issues.join(' ')}` : '.'}
        </p>
      )}

      <div className="panel-actions">
        {analysis.moves.length > 0 && (
          <button
            className="btn btn-primary"
            onClick={onApply}
            disabled={applied || analyzing || applying || !analysis.valid}
            title={
              applied
                ? 'This proposal is already in the schedule'
                : analyzing
                  ? 'Waiting for the new measurement'
                  : applying
                    ? 'Checking the proposal against the hard constraints'
                    : !analysis.valid
                      ? 'The proposal breaks a hard constraint, so it cannot be applied'
                      : undefined
            }
          >
            {applied ? (
              <>
                <CheckCircle size={15} aria-hidden="true" />
                Applied to schedule
              </>
            ) : applying ? (
              <>
                <ShieldCheck size={15} aria-hidden="true" />
                Checking constraints…
              </>
            ) : (
              <>
                <ArrowsLeftRight size={15} aria-hidden="true" />
                Apply optimized schedule
              </>
            )}
          </button>
        )}
        {applied && (
          <span className="stamp stamp-ok">
            <CheckCircle size={12} aria-hidden="true" />
            Schedule updated
          </span>
        )}
        {analyzing && (
          <span className="grid-note" role="status" aria-live="polite">
            Re-planning…
          </span>
        )}
      </div>
    </div>
  );
}
