import { useMemo, useState } from 'react';
import { LockOpen, LockSimple, MagnifyingGlass } from '@phosphor-icons/react';
import { api } from '../services/api.js';
import StructureEditor from './StructureEditor.jsx';

const toMinutes = (value) => {
  const [hours, minutes] = String(value ?? '').split(':').map(Number);
  return Number.isFinite(hours) && Number.isFinite(minutes) ? hours * 60 + minutes : null;
};

function slotInterval(slot, durationMin) {
  if (!slot) return null;
  const start = toMinutes(slot.start);
  const end = toMinutes(slot.end);
  if (start == null || end == null) return null;
  return [start, Math.min(end, start + durationMin)];
}

// The backend rejects a move that would double-book a cell, ignore an act's
// stage/slot restrictions, or overlap another set on the same stage. Pickers
// must not offer any of those in the first place.
function moveIssue({ act, stageId, slotId, acts, stages, slots }) {
  const stage = stages.find((entry) => entry.id === stageId);
  if (!stage) return 'Unknown stage.';
  if (act.allowed_stages != null && !act.allowed_stages.includes(stageId)) {
    return `Stage not allowed for ${act.name}.`;
  }
  const slot = slots.find((entry) => entry.id === slotId);
  if (!slot) return 'Unknown slot.';
  if (act.allowed_slots != null && !act.allowed_slots.includes(slotId)) {
    return `Slot not allowed for ${act.name}.`;
  }
  const duration = act.duration_min ?? 60;
  const bounds = slotInterval(slot, duration);
  if (bounds && duration > bounds[1] - bounds[0] + 0.0001) {
    return `${slot.label} is too short for this ${duration}-minute set.`;
  }
  const occupant = acts.find(
    (other) =>
      other.id !== act.id &&
      other.stage_id === stageId &&
      other.slot_id === slotId,
  );
  if (occupant) {
    return `${stage.name} ${slot.label} is already occupied by ${occupant.name}.`;
  }
  if (bounds) {
    const [start, end] = bounds;
    const overlapping = acts.find((other) => {
      if (other.id === act.id || other.stage_id !== stageId) return false;
      const otherBounds = slotInterval(
        slots.find((entry) => entry.id === other.slot_id),
        other.duration_min ?? 60,
      );
      return otherBounds != null && start < otherBounds[1] && otherBounds[0] < end;
    });
    if (overlapping) {
      return `Overlaps ${overlapping.name} on ${stage.name}.`;
    }
  }
  return null;
}

function ArtistSearch({ stages, slots, acts, onAdd }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [lastAdded, setLastAdded] = useState(null);

  const occupied = useMemo(
    () => new Set(acts.map((a) => `${a.stage_id}|${a.slot_id}`)),
    [acts],
  );

  const lineupEntityIds = useMemo(() => new Set(acts.map((a) => a.entity_id)), [acts]);

  const firstFreeCell = useMemo(() => {
    for (const slot of slots) {
      for (const stage of stages) {
        if (!occupied.has(`${stage.id}|${slot.id}`)) return { stage: stage.id, slot: slot.id };
      }
    }
    return null;
  }, [stages, slots, occupied]);

  const runSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const data = await api.searchArtists(query.trim());
      setResults(data);
    } catch (err) {
      setSearchError(err.message);
    } finally {
      setSearching(false);
    }
  };

  const add = (candidate) => {
    if (lineupEntityIds.has(candidate.entity_id)) return;
    const cell = firstFreeCell;
    if (!cell) {
      setSearchError('No free stage slots — remove an act or add a stage/slot first.');
      return;
    }
    onAdd(candidate, cell.stage, cell.slot);
    setLastAdded(candidate.name);
    setResults(null);
    setQuery('');
    window.setTimeout(() => setLastAdded(null), 4000);
  };

  return (
    <div className="artist-search">
      <form onSubmit={runSearch} className="search-form">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Qloo for an artist…"
          aria-label="Artist name to search on Qloo"
        />
        <button className="btn btn-small" type="submit" disabled={searching || !query.trim()}>
          <MagnifyingGlass size={13} aria-hidden="true" />
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>
      {searchError && <p className="search-error" role="alert">{searchError}</p>}
      {lastAdded && (
        <p className="search-feedback">
          <span className="stamp stamp-ok">added</span> {lastAdded} is now in the lineup.
        </p>
      )}
      {results && (
        <div className="search-results">
          {results.ambiguous && (
            <p className="search-note" role="status">
              Several plausible matches — choose the artist you meant. Nothing is
              auto-selected.
            </p>
          )}
          {results.candidates.length === 0 && (
            <p className="empty-state">No artists found for “{query}”. Try a different spelling.</p>
          )}
          {results.candidates.map((candidate) => {
            const inLineup = lineupEntityIds.has(candidate.entity_id);
            return (
              <div key={candidate.entity_id} className="search-result-row">
                <div>
                  <strong>{candidate.name}</strong>
                  {candidate.short_description && <p>{candidate.short_description}</p>}
                  <div className="search-result-tags">
                    {results.best_match?.entity_id === candidate.entity_id && (
                      <span className="stamp stamp-ok">best match</span>
                    )}
                    {results.ambiguous && (
                      <span className="stamp stamp-clash" title="Multiple similar candidates">
                        ambiguous
                      </span>
                    )}
                    {inLineup && (
                      <span className="stamp stamp-fixed" title="This artist is already in the lineup">
                        in lineup
                      </span>
                    )}
                  </div>
                </div>
                <button
                  className="btn btn-small"
                  onClick={() => add(candidate)}
                  disabled={inLineup}
                  title={inLineup ? 'Already in the lineup' : `Add ${candidate.name}`}
                >
                  {inLineup ? 'Added' : 'Add'}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function LineupEditor({
  acts,
  stages,
  slots,
  profiles,
  onUpdateAct,
  onRemoveAct,
  onAddAct,
  onToggleLock,
  onClearPlannerLocks,
  lockSources = {},
  qlooConfigured,
  structureBusy,
  onAddStage,
  onRemoveStage,
  onAddSlot,
  onRemoveSlot,
}) {
  const plannerLocked = acts.filter((act) => lockSources[act.id] === 'planner');
  return (
    <div>
      {qlooConfigured ? (
        <ArtistSearch stages={stages} slots={slots} acts={acts} onAdd={onAddAct} />
      ) : (
        <p className="section-hint">
          Live artist search is disabled — set <code>QLOO_API_KEY</code> in{' '}
          <code>backend/.env</code> and restart the backend to search Qloo and add real artists.
          The seeded demo festival keeps working without a key.
        </p>
      )}

      <StructureEditor
        stages={stages}
        slots={slots}
        busy={structureBusy}
        onAddStage={onAddStage}
        onRemoveStage={onRemoveStage}
        onAddSlot={onAddSlot}
        onRemoveSlot={onRemoveSlot}
      />

      {!acts.length && (
        <p className="empty-state">
          No artists in the lineup yet{qlooConfigured ? ' — search Qloo above to add the first act.' : '.'}
        </p>
      )}

      {plannerLocked.length > 0 && (
        <div className="lock-toolbar" role="group" aria-label="Planner locks">
          <span className="panel-note">
            {plannerLocked.length} act{plannerLocked.length === 1 ? ' is' : 's are'} locked by a
            planner brief.
          </span>
          <button
            className="btn btn-small"
            type="button"
            onClick={() => onClearPlannerLocks?.()}
          >
            Clear planner locks ({plannerLocked.length})
          </button>
        </div>
      )}

      {acts.length > 0 && (
        <div className="lineup">
          <div className="lineup-header lineup-row">
            <span>Artist</span>
            <span>Stage</span>
            <span>Slot</span>
            <span>Profile</span>
            <span />
          </div>
          {acts.map((act) => {
            const profile = profiles[act.entity_id];
            const lockSource = lockSources[act.id] === 'planner' ? 'planner' : 'organizer';
            return (
              <div key={act.id} className="lineup-row">
                <span className="act-name">
                  {act.name}
                  {act.fixed && (
                    <span
                      className={`stamp ${lockSource === 'planner' ? 'stamp-data' : 'stamp-fixed'}`}
                      title={
                        lockSource === 'planner'
                          ? 'Locked by a planner brief — clear planner locks or unlock it here'
                          : 'Locked by the organizer — the optimizer will not move it'
                      }
                    >
                      <LockSimple size={11} className="stamp-icon" aria-hidden="true" />
                      {lockSource} lock
                    </span>
                  )}
                  {act.duration_min !== 60 && <span className="stamp">{act.duration_min}m</span>}
                </span>
                <select
                  value={act.stage_id}
                  disabled={act.fixed}
                  aria-label={`Stage for ${act.name}`}
                  title={
                    act.fixed
                      ? 'Unlock this act to change its stage'
                      : moveIssue({
                          act,
                          stageId: act.stage_id,
                          slotId: act.slot_id,
                          acts,
                          stages,
                          slots,
                        }) ?? undefined
                  }
                  onChange={(e) => onUpdateAct(act.id, { stage_id: e.target.value })}
                >
                  {stages.map((stage) => {
                    const issue =
                      stage.id === act.stage_id
                        ? null
                        : moveIssue({
                            act,
                            stageId: stage.id,
                            slotId: act.slot_id,
                            acts,
                            stages,
                            slots,
                          });
                    return (
                      <option
                        key={stage.id}
                        value={stage.id}
                        disabled={Boolean(issue)}
                        title={issue ?? undefined}
                      >
                        {stage.name}
                      </option>
                    );
                  })}
                </select>
                <select
                  value={act.slot_id}
                  disabled={act.fixed}
                  aria-label={`Time slot for ${act.name}`}
                  title={
                    act.fixed
                      ? 'Unlock this act to change its time slot'
                      : moveIssue({
                          act,
                          stageId: act.stage_id,
                          slotId: act.slot_id,
                          acts,
                          stages,
                          slots,
                        }) ?? undefined
                  }
                  onChange={(e) => onUpdateAct(act.id, { slot_id: e.target.value })}
                >
                  {slots.map((slot) => {
                    const issue =
                      slot.id === act.slot_id
                        ? null
                        : moveIssue({
                            act,
                            stageId: act.stage_id,
                            slotId: slot.id,
                            acts,
                            stages,
                            slots,
                          });
                    return (
                      <option
                        key={slot.id}
                        value={slot.id}
                        disabled={Boolean(issue)}
                        title={issue ?? undefined}
                      >
                        {slot.label}–{slot.end}
                      </option>
                    );
                  })}
                </select>
                <span>
                  {!profile ? (
                    <span className="stamp">loading…</span>
                  ) : profile.missing ? (
                    <span
                      className="stamp stamp-missing"
                      title={profile.note || 'No taste profile available'}
                    >
                      missing profile
                    </span>
                  ) : (
                    <span
                      className="stamp stamp-ok"
                      title={`${profile.genre_tags.length} genre, ${profile.audience_tags.length} audience, ${profile.style_tags.length} style, ${profile.music_tags.length} music tags (${profile.source})`}
                    >
                      {profile.source === 'demo' ? 'demo profile' : profile.source}
                    </span>
                  )}
                </span>
                <span className="lineup-actions">
                  <button
                    className="btn btn-small"
                    type="button"
                    aria-pressed={Boolean(act.fixed)}
                    aria-label={`${act.fixed ? 'Unlock' : 'Lock'} ${act.name}`}
                    onClick={() => onToggleLock?.(act.id)}
                    title={
                      act.fixed
                        ? `Unlock ${act.name} so it can be moved again`
                        : `Lock ${act.name} so the optimizer keeps it in place`
                    }
                  >
                    {act.fixed ? (
                      <LockOpen size={12} aria-hidden="true" />
                    ) : (
                      <LockSimple size={12} aria-hidden="true" />
                    )}
                    {act.fixed ? 'Unlock' : 'Lock'}
                  </button>
                  <button
                    className="btn btn-small btn-danger"
                    onClick={() => onRemoveAct(act.id)}
                    disabled={act.fixed}
                    title={
                      act.fixed
                        ? 'Unlock this act before removing it'
                        : `Remove ${act.name}`
                    }
                  >
                    Remove
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
