import { Plus, X } from '@phosphor-icons/react';

function fmtTime(totalMinutes) {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

function parseTime(value) {
  const [h, m] = value.split(':').map((n) => Number.parseInt(n, 10));
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

export default function StructureEditor({ stages, slots, busy, onAddStage, onRemoveStage, onAddSlot, onRemoveSlot }) {
  const lastSlot = slots[slots.length - 1];
  const lastEnd = lastSlot ? parseTime(lastSlot.end) : null;
  // Backend accepts HH:MM up to 24:00 (end of day), so the day is full at 24:00.
  const gridFull = lastEnd == null || lastEnd >= 24 * 60;

  const addSlot = () => {
    if (gridFull || lastEnd == null) return;
    const start = fmtTime(lastEnd);
    const end = fmtTime(Math.min(lastEnd + 60, 24 * 60));
    onAddSlot({
      id: `t${Date.now()}`,
      label: start,
      start,
      end,
    });
  };

  return (
    <div className="structure-editor" aria-label="Festival structure">
      <div className="structure-group">
        <span className="structure-label">Stages</span>
        <ul className="structure-list">
          {stages.map((stage) => (
            <li key={stage.id} className="structure-item">
              <span className="structure-name">{stage.name}</span>
              <button
                className="btn btn-small btn-danger"
                type="button"
                onClick={() => onRemoveStage(stage.id)}
                disabled={busy || stages.length <= 1}
                aria-label={`Remove ${stage.name}`}
                title={
                  stages.length <= 1
                    ? 'A festival needs at least one stage'
                    : `Remove ${stage.name} — acts on it are re-placed automatically`
                }
              >
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
        <button className="btn btn-small" type="button" onClick={onAddStage} disabled={busy}>
          <Plus size={12} aria-hidden="true" />
          Add stage
        </button>
      </div>

      <div className="structure-group">
        <span className="structure-label">Time slots</span>
        <ul className="structure-list">
          {slots.map((slot) => (
            <li key={slot.id} className="structure-item">
              <span className="structure-name">
                {slot.label}–{slot.end}
              </span>
              <button
                className="btn btn-small btn-danger"
                type="button"
                onClick={() => onRemoveSlot(slot.id)}
                disabled={busy || slots.length <= 1}
                aria-label={`Remove slot ${slot.label}–${slot.end}`}
                title={
                  slots.length <= 1
                    ? 'A festival needs at least one time slot'
                    : `Remove ${slot.label}–${slot.end} — acts in it are re-placed automatically`
                }
              >
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
        <button
          className="btn btn-small"
          type="button"
          onClick={addSlot}
          disabled={busy || gridFull}
          title={gridFull ? 'The day is full (ends at 24:00)' : 'Add a one-hour slot at the end of the day'}
        >
          <Plus size={12} aria-hidden="true" />
          Add slot
        </button>
        <p className="structure-note">Removing a stage or slot re-places its acts into free cells automatically.</p>
      </div>
    </div>
  );
}
