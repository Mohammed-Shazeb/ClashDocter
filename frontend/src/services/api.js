// Empty in local dev: Vite proxies /api and /health to the backend.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && body.detail;
    const message =
      (detail && typeof detail === 'object' && detail.message) ||
      (typeof detail === 'string' && detail) ||
      `Request failed (HTTP ${response.status})`;
    const error = new Error(message);
    error.code = detail && typeof detail === 'object' && detail.code;
    error.status = response.status;
    throw error;
  }
  return body;
}

export const api = {
  health: () => request('/health'),
  demoFestival: () => request('/api/demo/festival'),
  templateFestival: () => request('/api/festival/template'),
  searchArtists: (query) =>
    request('/api/artists/search', {
      method: 'POST',
      body: JSON.stringify({ query }),
    }),
  similarity: (entityIds, names) =>
    request('/api/similarity', {
      method: 'POST',
      body: JSON.stringify({ entity_ids: entityIds, names }),
    }),
  optimize: (stages, slots, acts, preferences) =>
    request('/api/optimize', {
      method: 'POST',
      body: JSON.stringify({ stages, slots, acts, preferences }),
    }),
  interpretPlan: (stages, slots, acts, instruction) =>
    request('/api/plan/interpret', {
      method: 'POST',
      body: JSON.stringify({ stages, slots, acts, instruction }),
    }),
  validateSchedule: (stages, slots, acts) =>
    request('/api/schedule/validate', {
      method: 'POST',
      body: JSON.stringify({ stages, slots, acts }),
    }),
  assignSchedule: (stages, slots, acts) =>
    request('/api/schedule/assign', {
      method: 'POST',
      body: JSON.stringify({ stages, slots, acts }),
    }),
  importParse: (text, filename = null) =>
    request('/api/import/parse', {
      method: 'POST',
      body: JSON.stringify({ text, filename }),
    }),
  importResolve: (names) =>
    request('/api/import/resolve', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),
};
