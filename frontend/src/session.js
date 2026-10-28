// The whole working session — lineup, assignment, priorities, locks and the
// last measurement — survives a refresh. Bump the version whenever the saved
// shape changes; older payloads are ignored rather than half-restored.
export const SESSION_KEY = 'clashdoctor.session';
export const SESSION_VERSION = 1;

const defaultStorage = () => window.localStorage;

export function saveSession(state, storage = defaultStorage()) {
  try {
    storage.setItem(
      SESSION_KEY,
      JSON.stringify({ version: SESSION_VERSION, saved_at: new Date().toISOString(), ...state }),
    );
  } catch {
    // Private mode or a full quota: persistence is a convenience, not a requirement.
  }
}

export function loadSession(storage = defaultStorage()) {
  try {
    const raw = storage.getItem(SESSION_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || data.version !== SESSION_VERSION) return null;
    const festival = data.festival;
    if (
      !festival ||
      !Array.isArray(festival.stages) ||
      !Array.isArray(festival.slots) ||
      !Array.isArray(festival.acts)
    ) {
      return null;
    }
    return {
      festival,
      preferences: data.preferences ?? null,
      lockSources:
        data.lockSources && typeof data.lockSources === 'object' ? data.lockSources : {},
      applied: Boolean(data.applied),
      analysis: data.analysis ?? null,
      similarity: data.similarity ?? null,
    };
  } catch {
    return null;
  }
}

export function clearSession(storage = defaultStorage()) {
  try {
    storage.removeItem(SESSION_KEY);
  } catch {
    // Nothing to do: an unreadable store should not break a reset.
  }
}
