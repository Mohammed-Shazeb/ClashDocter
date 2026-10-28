import { useMemo, useState } from 'react';
import { api } from '../services/api.js';

const RESOLVE_BATCH = 100;

const SAMPLE = [
  '# name: Sample Festival',
  'artist,stage,start,end,duration_min',
  'Radiohead,Main Stage,21:00,22:30,90',
  'Little Simz,Main Stage,19:00,20:00,60',
  'Floating Points,Pulse Stage,19:00,20:15,75',
  'Sault,Pulse Stage,21:00,22:00,60',
  'Khruangbin,Tent Stage,20:00,21:00,60',
].join('\n');

const nameKey = (name) => name.trim().toLowerCase();

export default function ImportPanel({ qlooConfigured, busy, onImport }) {
  const [text, setText] = useState('');
  const [filename, setFilename] = useState(null);
  const [parsed, setParsed] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState(null);
  const [matches, setMatches] = useState(null);
  const [chosen, setChosen] = useState({});
  const [matching, setMatching] = useState(false);
  const [matchError, setMatchError] = useState(null);
  const [buildFailed, setBuildFailed] = useState(false);

  const issues = parsed?.issues ?? [];
  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');
  const notes = issues.filter((i) => i.severity === 'info');

  const matchByKey = useMemo(() => {
    const map = {};
    for (const match of matches ?? []) map[nameKey(match.query)] = match;
    return map;
  }, [matches]);

  const distinctNames = useMemo(() => {
    const seen = new Map();
    for (const act of parsed?.acts ?? []) {
      const k = nameKey(act.name);
      if (!seen.has(k)) seen.set(k, act.name);
    }
    return [...seen.values()];
  }, [parsed]);

  const matchedCount = distinctNames.filter(
    (name) => matchByKey[nameKey(name)]?.status === 'matched' || chosen[nameKey(name)],
  ).length;
  const needPickCount = distinctNames.filter(
    (name) => matchByKey[nameKey(name)]?.status === 'ambiguous' && !chosen[nameKey(name)],
  ).length;
  const noMatchCount = distinctNames.filter((name) => {
    const match = matchByKey[nameKey(name)];
    return match && ['not_found', 'error'].includes(match.status) && !chosen[nameKey(name)];
  }).length;

  async function handleParse(nextText = text, nextFilename = filename) {
    if (!nextText.trim()) return;
    setParsing(true);
    setParseError(null);
    setBuildFailed(false);
    setMatches(null);
    setChosen({});
    setMatchError(null);
    try {
      const result = await api.importParse(nextText, nextFilename);
      setParsed(result);
    } catch (err) {
      setParsed(null);
      setParseError(err.message);
    } finally {
      setParsing(false);
    }
  }

  async function handleFile(file) {
    if (!file) return;
    const contents = await file.text();
    setFilename(file.name);
    setText(contents);
    await handleParse(contents, file.name);
  }

  async function resolveNames(names) {
    const collected = [];
    for (let i = 0; i < names.length; i += RESOLVE_BATCH) {
      const batch = await api.importResolve(names.slice(i, i + RESOLVE_BATCH));
      collected.push(...batch.matches);
    }
    return collected;
  }

  async function handleMatch() {
    if (!distinctNames.length) return;
    setMatching(true);
    setMatchError(null);
    try {
      const results = await resolveNames(distinctNames);
      setMatches(results);
      setChosen(
        Object.fromEntries(
          results
            .filter((m) => m.status === 'matched' && m.match)
            .map((m) => [nameKey(m.query), m.match]),
        ),
      );
    } catch (err) {
      setMatches(null);
      setMatchError(err.message);
    } finally {
      setMatching(false);
    }
  }

  async function retryName(name) {
    setMatching(true);
    setMatchError(null);
    try {
      const results = await resolveNames([name]);
      setMatches((prev) => [
        ...(prev ?? []).filter((m) => nameKey(m.query) !== nameKey(name)),
        ...results,
      ]);
      const first = results[0];
      if (first?.status === 'matched' && first.match) {
        setChosen((prev) => ({ ...prev, [nameKey(name)]: first.match }));
      }
    } catch (err) {
      setMatchError(err.message);
    } finally {
      setMatching(false);
    }
  }

  function pick(name, candidate) {
    setChosen((prev) => {
      const next = { ...prev };
      if (candidate) next[nameKey(name)] = candidate;
      else delete next[nameKey(name)];
      return next;
    });
  }

  async function handleBuild() {
    if (!parsed?.valid || busy) return;
    const acts = parsed.acts.map((act) => {
      const match = chosen[nameKey(act.name)];
      return {
        id: act.id,
        name: act.name,
        // A local placeholder, never a Qloo id: the backend reports these as
        // missing profiles instead of scoring them as zero affinity.
        entity_id: match?.entity_id || `unmatched:${act.id}`,
        stage_id: act.stage_id,
        slot_id: act.slot_id,
        duration_min: act.duration_min,
        fixed: act.fixed,
      };
    });
    const built = await onImport({
      name: parsed.festival_name || filename || 'Imported festival',
      stages: parsed.stages,
      slots: parsed.slots,
      acts,
      unmatched: acts.filter((a) => a.entity_id.startsWith('unmatched:')).length,
    });
    // A rejected build keeps the pasted lineup and the preview: losing them would
    // force the user to retype everything to retry.
    if (built === false) {
      setBuildFailed(true);
      return;
    }
    setBuildFailed(false);
    setParsed(null);
    setMatches(null);
    setChosen({});
    setText('');
    setFilename(null);
  }

  const canBuild = Boolean(parsed?.valid && parsed?.acts.length) && !busy && !parsing;

  return (
    <div className="import-panel">
      <div className="import-input">
        <label className="import-label" htmlFor="import-text">
          Paste a lineup (CSV, TSV, or free text)
        </label>
        <textarea
          id="import-text"
          className="import-textarea"
          rows={7}
          value={text}
          spellCheck={false}
          placeholder={'artist,stage,start,end,duration_min\nRadiohead,Main Stage,21:00,22:30,90'}
          onChange={(e) => {
            setText(e.target.value);
            setFilename(null);
          }}
        />
        <div className="import-actions">
          <button
            className="btn btn-small btn-primary"
            type="button"
            onClick={() => handleParse()}
            disabled={parsing || !text.trim()}
          >
            {parsing ? 'Parsing…' : 'Parse lineup'}
          </button>
          <label className="btn btn-small import-file">
            Upload CSV
            <input
              type="file"
              accept=".csv,.tsv,.txt,text/csv,text/plain"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </label>
          <button
            className="btn btn-small"
            type="button"
            onClick={() => {
              setText(SAMPLE);
              setFilename(null);
              handleParse(SAMPLE, null);
            }}
            disabled={parsing}
          >
            Load sample
          </button>
          {filename && <span className="import-filename">{filename}</span>}
        </div>
        <p className="import-hint">
          Columns are detected from the header row (artist/act/name, stage/venue, start/begin,
          end/finish, duration/set length, fixed/locked) or by position. Nothing is sent to Qloo
          until you match artists below.
        </p>
        {parseError && (
          <p className="search-error" role="alert">
            {parseError}
          </p>
        )}
      </div>

      {parsed && (
        <div className="import-preview">
          <div className="import-summary">
            <span className="stamp">{parsed.source_format === 'csv' ? 'csv' : 'pasted text'}</span>
            <span>{parsed.summary}</span>
            {parsed.valid ? (
              <span className="stamp stamp-ok">validated</span>
            ) : (
              <span className="stamp stamp-clash">{errors.length} blocking problem(s)</span>
            )}
          </div>

          {issues.length > 0 && (
            <ul className="import-issues">
              {errors.map((issue, i) => (
                <li key={`e${i}`} className="import-issue error">
                  <span className="stamp stamp-clash">error</span>
                  {issue.row != null && <span className="import-row">row {issue.row}</span>}
                  {issue.message}
                </li>
              ))}
              {warnings.map((issue, i) => (
                <li key={`w${i}`} className="import-issue warning">
                  <span className="stamp stamp-accent">warning</span>
                  {issue.row != null && <span className="import-row">row {issue.row}</span>}
                  {issue.message}
                </li>
              ))}
              {notes.map((issue, i) => (
                <li key={`i${i}`} className="import-issue info">
                  <span className="stamp">note</span>
                  {issue.message}
                </li>
              ))}
            </ul>
          )}

          {!parsed.valid && (
            <p className="panel-note warn">
              Rejected rows are not imported. Fix the rows listed above and parse again — artists
              are never dropped silently.
            </p>
          )}

          {parsed.valid && (
            <div className="grid-wrap import-grid-wrap">
              <table className="schedule-grid">
                <caption className="import-caption">
                  {parsed.stages.length} stage(s) · {parsed.slots.length} slot(s)
                </caption>
                <thead>
                  <tr>
                    <th className="corner">Stage</th>
                    {parsed.slots.map((slot) => (
                      <th key={slot.id}>
                        {slot.label}
                        <span className="slot-end">–{slot.end}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {parsed.stages.map((stage) => (
                    <tr key={stage.id}>
                      <th className="stage-label">{stage.name}</th>
                      {parsed.slots.map((slot) => {
                        const act = parsed.acts.find(
                          (a) => a.stage_id === stage.id && a.slot_id === slot.id,
                        );
                        if (!act) return <td key={slot.id} className="cell empty" />;
                        return (
                          <td key={slot.id} className={`cell${act.fixed ? ' fixed' : ''}`}>
                            <div className="act-chip">
                              <span className="chip-name">{act.name}</span>
                              <span className="chip-meta">
                                {act.duration_min}m{act.fixed ? ' · locked' : ''}
                              </span>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="import-match">
            <div className="import-match-head">
              <h3>Match artists on Qloo</h3>
              {qlooConfigured ? (
                <button
                  className="btn btn-small"
                  type="button"
                  onClick={handleMatch}
                  disabled={matching || !distinctNames.length}
                >
                  {matching ? 'Matching…' : matches ? 'Re-run matching' : 'Match artists'}
                </button>
              ) : (
                <span className="stamp stamp-demo">no api key</span>
              )}
            </div>

            {!qlooConfigured && (
              <p className="panel-note">
                <code>QLOO_API_KEY</code> is not set, so imported artists cannot be matched to Qloo
                entities. You can still build this schedule — every act will be flagged{' '}
                <em>no profile</em> and excluded from similarity scoring rather than scored as
                zero affinity. Set the key in <code>backend/.env</code> and restart for live taste
                data.
              </p>
            )}

            {matchError && (
              <p className="search-error" role="alert">
                {matchError}
              </p>
            )}

            {matches && (
              <>
                <p className="import-match-summary" role="status">
                  {matchedCount} of {distinctNames.length} artist(s) matched to a Qloo entity
                  {needPickCount > 0 && ` · ${needPickCount} awaiting your pick`}
                  {noMatchCount > 0 && ` · ${noMatchCount} with no Qloo match`}
                  {' · '}results are cached, re-running costs no extra API calls.
                </p>
                <div className="import-match-list">
                  {distinctNames.map((name) => (
                    <MatchRow
                      key={nameKey(name)}
                      name={name}
                      match={matchByKey[nameKey(name)]}
                      choice={chosen[nameKey(name)]}
                      busy={matching}
                      onPick={pick}
                      onRetry={retryName}
                    />
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="import-build">
            <button
              className="btn btn-primary"
              type="button"
              onClick={handleBuild}
              disabled={!canBuild}
              title={
                parsed.valid
                  ? 'Replace the current schedule with this imported lineup'
                  : 'Fix the blocking problems first'
              }
            >
              {busy ? 'Building…' : 'Build schedule from import'}
            </button>
            <span className="import-build-note">
              {matches
                ? `${parsed.acts.length - (parsed.acts.filter((a) => chosen[nameKey(a.name)]).length)} act(s) will import without taste data.`
                : qlooConfigured
                  ? 'Match artists first, or build now — unmatched acts are imported as “no profile”.'
                  : 'Unmatched acts are imported and reported as missing data.'}
            </span>
            {buildFailed && (
              <p className="panel-note warn" role="status">
                This lineup was not built — the reason is in the banner above. Your paste and the
                preview are still here, so add a stage or slot, or drop the rows that do not fit,
                and build again.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MatchRow({ name, match, choice, busy, onPick, onRetry }) {
  const [expanded, setExpanded] = useState(false);
  if (!match) {
    return (
      <div className="match-row">
        <span className="match-name">{name}</span>
        <span className="stamp stamp-missing">not looked up</span>
      </div>
    );
  }

  const candidates = match.candidates ?? [];
  const showChoices = expanded || match.status === 'ambiguous' || match.status === 'not_found';

  return (
    <div className="match-row">
      <div className="match-head">
        <span className="match-name">{name}</span>
        {match.status === 'matched' && (
          <span className="stamp stamp-ok" title={match.cached ? 'Served from cache' : 'Live Qloo search'}>
            matched{match.cached ? ' · cached' : ''}
          </span>
        )}
        {match.status === 'ambiguous' &&
          (choice ? (
            <span className="stamp stamp-ok" title="You confirmed this artist">
              confirmed
            </span>
          ) : (
            <span className="stamp stamp-accent" title={match.note ?? ''}>
              needs confirmation
            </span>
          ))}
        {match.status === 'not_found' && (
          <span className="stamp stamp-missing" title={match.note ?? ''}>
            not found
          </span>
        )}
        {match.status === 'error' && (
          <span className="stamp stamp-clash" title={match.note ?? ''}>
            lookup failed
          </span>
        )}
        {choice && <span className="match-choice">→ {choice.name}</span>}
        {!choice && match.status !== 'error' && (
          <span className="match-none">imports without taste data</span>
        )}
        {match.status === 'error' && (
          <button
            className="btn btn-small"
            type="button"
            onClick={() => onRetry(name)}
            disabled={busy}
          >
            Retry
          </button>
        )}
        {candidates.length > 1 && match.status !== 'ambiguous' && (
          <button
            className="btn btn-small"
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? 'Hide alternatives' : `${candidates.length} alternatives`}
          </button>
        )}
      </div>

      {match.status === 'error' && match.note && <p className="match-note">{match.note}</p>}

      {showChoices && candidates.length > 0 && (
        <div className="match-candidates">
          {candidates.map((candidate) => {
            const isChoice = choice?.entity_id === candidate.entity_id;
            return (
              <label
                key={candidate.entity_id}
                className={`match-candidate${isChoice ? ' chosen' : ''}`}
              >
                <input
                  type="radio"
                  name={`match-${nameKey(name)}`}
                  checked={isChoice}
                  onChange={() => onPick(name, candidate)}
                />
                <span>
                  <strong>{candidate.name}</strong>
                  {(candidate.disambiguation || candidate.short_description) && (
                    <em> — {candidate.disambiguation || candidate.short_description}</em>
                  )}
                  <span className="match-id">{candidate.entity_id}</span>
                </span>
              </label>
            );
          })}
          {choice && (
            <button
              className="btn btn-small"
              type="button"
              onClick={() => onPick(name, null)}
              title="Import this artist without a Qloo match — it will be reported as missing data"
            >
              No match
            </button>
          )}
        </div>
      )}

      {showChoices && candidates.length === 0 && (
        <p className="match-note">
          Qloo returned no artist for this name. Check the spelling, or import it as-is — it will
          be excluded from similarity scoring, not scored as zero.
        </p>
      )}
    </div>
  );
}
