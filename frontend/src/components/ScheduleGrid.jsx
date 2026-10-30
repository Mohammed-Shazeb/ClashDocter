import { useMemo } from 'react';

export default function ScheduleGrid({
  stages,
  slots,
  acts,
  clashes,
  proposedActs,
  proposedClashes,
  profiles,
  applied,
  moveCount,
}) {
  const movedIds = useMemo(() => {
    const moved = new Set();
    if (!proposedActs) return moved;
    const proposed = new Map(proposedActs.map((a) => [a.id, `${a.stage_id}|${a.slot_id}`]));
    for (const act of acts) {
      if (proposed.get(act.id) !== `${act.stage_id}|${act.slot_id}`) moved.add(act.id);
    }
    return moved;
  }, [acts, proposedActs]);

  if (!acts.length) {
    return <p className="empty-state">Add artists to build the schedule.</p>;
  }

  const showCompare = Boolean(proposedActs) && !applied;

  return (
    <div className={showCompare ? 'schedule-compare' : ''}>
      <div className="grid-pane">
        <PaneHeader
          label={applied ? 'Applied schedule' : 'Draft — current'}
          count={(clashes ?? []).length}
        />
        <GridView
          stages={stages}
          slots={slots}
          acts={acts}
          clashes={clashes}
          profiles={profiles}
          moved={new Set()}
        />
        <p className="grid-note">
          {applied
            ? 'Applied schedule — clash cells show remaining overlaps.'
            : 'Draft schedule — clash cells are simultaneous acts with similar estimated taste tags, not measured audience overlap.'}
        </p>
      </div>

      {showCompare && (
        <div className="grid-pane grid-pane-proposed">
          <PaneHeader
            label={`Proposed — ${moveCount} move${moveCount === 1 ? '' : 's'}`}
            count={(proposedClashes ?? []).length}
          />
          <GridView
            stages={stages}
            slots={slots}
            acts={proposedActs}
            clashes={proposedClashes}
            profiles={profiles}
            moved={movedIds}
          />
          <p className="grid-note">
            Proposed schedule — moved acts are marked; only remaining clashes appear.
          </p>
        </div>
      )}
    </div>
  );
}

function PaneHeader({ label, count }) {
  return (
    <div className="grid-pane-head">
      <span className="pane-label">{label}</span>
      <span className="pane-count">
        {count} clash{count === 1 ? '' : 'es'}
      </span>
    </div>
  );
}

function GridView({ stages, slots, acts, clashes, profiles, moved }) {
  // A cell can hold more than one act when an edit was forced through; hiding
  // one of them would make the grid look valid when the schedule is not.
  const actsAt = useMemo(() => {
    const map = {};
    for (const act of acts) {
      const key = `${act.stage_id}|${act.slot_id}`;
      map[key] = [...(map[key] ?? []), act];
    }
    return map;
  }, [acts]);

  const clashByActId = useMemo(() => {
    const map = {};
    for (const clash of clashes ?? []) {
      map[clash.a_id] = [...(map[clash.a_id] ?? []), clash];
      map[clash.b_id] = [...(map[clash.b_id] ?? []), clash];
    }
    return map;
  }, [clashes]);

  return (
    <div className="grid-wrap">
      <table className="schedule-grid">
        <thead>
          <tr>
            <th className="corner">Stage</th>
            {slots.map((slot) => (
              <th key={slot.id}>
                {slot.label}
                <span className="slot-end">–{slot.end}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stages.map((stage) => (
            <tr key={stage.id}>
              <th className="stage-label">{stage.name}</th>
              {slots.map((slot) => {
                const cellActs = actsAt[`${stage.id}|${slot.id}`] ?? [];
                if (!cellActs.length) return <td key={slot.id} className="cell empty" />;
                const collision = cellActs.length > 1;
                const clashTitles = cellActs.flatMap((act) =>
                  (clashByActId[act.id] ?? []).map((c) => {
                    const other = c.a_id === act.id ? c.b_name : c.a_name;
                    return `${act.name} vs ${other} (estimated taste similarity ${c.similarity.toFixed(2)})`;
                  }),
                );
                const cellTitle = collision
                  ? `Double-booked: ${cellActs.map((act) => act.name).join(' and ')}`
                  : clashTitles.length
                    ? `Clash: ${clashTitles.join('; ')}`
                    : undefined;
                return (
                  <td
                    key={slot.id}
                    className={`cell${clashTitles.length ? ' clash' : ''}${collision ? ' collision' : ''}${
                      cellActs.some((act) => act.fixed) ? ' fixed' : ''
                    }${cellActs.some((act) => moved.has(act.id)) ? ' moved' : ''}`}
                    title={cellTitle}
                  >
                    {cellActs.map((act) => {
                      const profile = profiles[act.entity_id];
                      const isMoved = moved.has(act.id);
                      return (
                        <div className="act-chip" key={act.id}>
                          <span className="chip-name">{act.name}</span>
                          <span className="chip-meta">
                            {act.duration_min}m{act.fixed ? ' · locked' : ''}
                            {profile?.missing ? ' · no profile' : ''}
                            {isMoved ? ' moved' : ''}
                          </span>
                        </div>
                      );
                    })}
                    {collision && (
                      <span className="stamp stamp-clash cell-collision">double-booked</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
