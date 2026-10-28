import { useState } from 'react';
import { CheckCircle, Lightning, ShieldCheck, XCircle } from '@phosphor-icons/react';

// Mirrors planner.EXAMPLES in the backend, so every button here produces a plan
// the rule table actually understands.
const EXAMPLES = [
  'Keep both headliners fixed and reduce high-affinity clashes.',
  'Minimize schedule changes, even if some clashes remain.',
  'Allow at most three acts to move and ignore how much disruption that causes.',
];

const PREF_KEYS = ['high_affinity_threshold', 'high_affinity_weight', 'move_penalty', 'max_moves'];

const samePreferences = (a, b) =>
  Boolean(a && b) && PREF_KEYS.every((key) => Number(a[key]) === Number(b[key]));

const shown = (field, value) =>
  field === 'max_moves' ? String(Math.round(Number(value))) : Number(value).toFixed(2);

export default function PlanningPanel({
  plan,
  planning,
  planError,
  analysis,
  running,
  applied,
  acts,
  plannerMode,
  onInterpret,
  onClear,
  onRun,
}) {
  const [text, setText] = useState('');
  const instruction = text.trim();
  const disabled = !instruction || planning || !acts.length;
  const freshLocks = (plan?.requested_locks ?? []).filter((lock) => !lock.already_locked);
  const heldLocks = (plan?.requested_locks ?? []).filter((lock) => lock.already_locked);
  // "Locked already" already lists every fixed act; repeating the same names as a
  // second sentence reads like two different facts.
  const heldNames = heldLocks.map((lock) => lock.act_name);
  const heldRestates =
    heldNames.length > 0 &&
    heldNames.length === (plan?.locked_acts.length ?? 0) &&
    heldNames.every((name) => plan.locked_acts.includes(name));
  const heldWorthSaying = heldNames.length > 0 && !heldRestates;
  // The plan is only measured once the optimizer has run with exactly these
  // priorities; until then the panel must not imply a result exists.
  const measured = Boolean(plan && analysis && samePreferences(analysis.preferences, plan.preferences));

  function submit(event) {
    event.preventDefault();
    if (disabled) return;
    onInterpret(instruction);
  }

  return (
    <form
      className="planner"
      onSubmit={submit}
      role="region"
      aria-label="Plan the run in plain English"
    >
      <div className="planner-head">
        <span className="pane-label">Brief the optimizer in plain English</span>
        {plannerMode && (
          <span className={`stamp stamp-long ${plan?.source === 'rules+llm' ? 'stamp-data' : 'stamp-missing'}`}>
            {plannerMode}
          </span>
        )}
      </div>

      <label className="import-label" htmlFor="planner-instruction">
        One scheduling priority, in your own words
      </label>
      <textarea
        id="planner-instruction"
        className="import-textarea"
        rows={2}
        value={text}
        maxLength={2000}
        placeholder="Keep the headliners fixed and separate the most similar pairs."
        onChange={(event) => setText(event.target.value)}
      />

      <div className="preset-row" role="group" aria-label="Example briefs">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="btn btn-small preset"
            onClick={() => setText(example)}
            title={example}
          >
            {example.length > 34 ? `${example.slice(0, 33)}…` : example}
          </button>
        ))}
      </div>

      <div className="import-actions">
        <button className="btn btn-small btn-primary" type="submit" disabled={disabled}>
          <Lightning size={13} aria-hidden="true" />
          Interpret
        </button>
        {(plan || planError || instruction) && (
          <button
            className="btn btn-small"
            type="button"
            onClick={() => {
              setText('');
              onClear();
            }}
          >
            Clear
          </button>
        )}
        {planning && (
          <span className="panel-note" role="status" aria-live="polite">
            Reading the request…
          </span>
        )}
      </div>

      {planError && (
        <p className="panel-note panel-note-invalid" role="alert">
          <XCircle size={13} aria-hidden="true" /> {planError}
        </p>
      )}

      {!acts.length && <p className="panel-note">Add at least one artist to plan a run.</p>}

      {plan && (
        <div className="plan-result">
          <p className="plan-summary">{plan.summary}</p>

          {/* The stamp only says whether a provider is configured, which is not the
              same as whether it produced this plan; a model failure would otherwise
              read as a model answer. */}
          {plan.llm_note && (
            <p className={`panel-note${plan.llm_ok === false ? ' warn' : ''}`}>{plan.llm_note}</p>
          )}

          <h3 className="pane-label">Interpreted priorities</h3>
          {plan.evidence.length ? (
            <ul className="plan-list">
              {plan.evidence.map((entry) => (
                <li className="plan-item" key={`${entry.field}-${entry.rule}-${entry.value}`}>
                  <span className="plan-value">
                    {entry.label}: <strong>{shown(entry.field, entry.value)}</strong>
                    <span className="plan-unit">{entry.unit}</span>
                  </span>
                  <span className="plan-phrase">“{entry.phrase}”</span>
                  <span className={`stamp ${entry.source === 'llm' ? 'stamp-data' : 'stamp-fixed'}`}>
                    {entry.source === 'llm' ? 'model, re-checked' : 'phrase rule'}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="panel-note">
              No priority changes. The run would use the current controls as they are.
            </p>
          )}

          <p className="panel-note">
            <ShieldCheck size={13} aria-hidden="true" /> Always enforced: {plan.enforced_constraints.length}{' '}
            hard constraints — {plan.enforced_constraints.join('; ')}.
          </p>

          {(heldNames.length > 0 || freshLocks.length > 0 || plan.locked_acts.length > 0) && (
            <p className="panel-note">
              Locked already: {plan.locked_acts.length ? plan.locked_acts.join(', ') : 'none'}.
              {freshLocks.length > 0 && (
                <> Run would additionally lock: {freshLocks.map((lock) => lock.act_name).join(', ')}.</>
              )}
              {heldWorthSaying && <> Your brief asked for {heldNames.join(', ')} by name.</>}
            </p>
          )}

          {plan.unsupported.length > 0 && (
            <>
              <h3 className="pane-label">This backend cannot do that</h3>
              <ul className="plan-list">
                {plan.unsupported.map((entry) => (
                  <li className="plan-item plan-item-unsupported" key={entry.phrase}>
                    <span className="plan-phrase">“{entry.phrase}”</span>
                    <span>{entry.reason}</span>
                    <span className="plan-alt">Instead: {entry.alternative}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {plan.clarifications.length > 0 && (
            <>
              <h3 className="pane-label">Worth checking</h3>
              <ul className="plan-list">
                {plan.clarifications.map((entry, index) => (
                  <li className="plan-item plan-item-clarify" key={`${entry.kind}-${index}`}>
                    <span className="stamp stamp-warn">{entry.kind.replace(/_/g, ' ')}</span>
                    <span>{entry.question}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <div className="plan-actions">
            <button
              className="btn btn-small btn-primary"
              type="button"
              onClick={onRun}
              disabled={running || !acts.length}
              title="Runs the existing optimizer with these priorities. Nothing is applied to the schedule."
            >
              <Lightning size={13} aria-hidden="true" />
              Run with these priorities
            </button>
            <span className="panel-note" role="status" aria-live="polite">
              {running ? (
                'Running the optimizer…'
              ) : measured ? (
                <>
                  <CheckCircle size={13} aria-hidden="true" />{' '}
                  {applied
                    ? 'Measured and applied — the grid above is this plan.'
                    : 'Measured — the table below is this plan. Applying it stays your decision.'}
                </>
              ) : (
                'Not measured yet: the objective table below still shows an earlier run.'
              )}
            </span>
          </div>
          {plan.requires_confirmation && (
            <p className="panel-note warn">
              This brief needs your approval: it changes which acts are locked, or asks something
              ambiguous. Running it only re-plans; the Apply button stays separate.
            </p>
          )}
        </div>
      )}
    </form>
  );
}
