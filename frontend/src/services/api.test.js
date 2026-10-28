import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from './api.js';

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

describe('api service', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('health returns backend status', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      jsonResponse({ status: 'ok', qloo_configured: false }),
    );
    const body = await api.health();
    expect(body.qloo_configured).toBe(false);
    expect(fetch).toHaveBeenCalledWith('/health', expect.any(Object));
  });

  it('searchArtists POSTs the query', async () => {
    const mock = vi.fn().mockResolvedValue(
      jsonResponse({ query: 'Radiohead', candidates: [], best_match: null, ambiguous: false }),
    );
    globalThis.fetch = mock;
    await api.searchArtists('Radiohead');
    const [url, options] = mock.mock.calls[0];
    expect(url).toBe('/api/artists/search');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ query: 'Radiohead' });
  });

  it('surfaces backend error codes', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      jsonResponse({ detail: { code: 'QLOO_NOT_CONFIGURED', message: 'no key' } }, 503),
    );
    const err = await api.searchArtists('x').catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.code).toBe('QLOO_NOT_CONFIGURED');
    expect(err.message).toBe('no key');
  });

  it('assignSchedule POSTs stages, slots and acts', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ acts: [], note: '' }));
    globalThis.fetch = mock;
    await api.assignSchedule([{ id: 's1', name: 'Main' }], [{ id: 't1', start: '17:00', end: '18:00', label: '17:00' }], []);
    const [, options] = mock.mock.calls[0];
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body);
    expect(body.stages[0].id).toBe('s1');
    expect(body.slots[0].id).toBe('t1');
    expect(body.acts).toEqual([]);
  });

  it('interpretPlan POSTs the current schedule with the instruction', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ summary: '', preferences: {}, evidence: [] }));
    globalThis.fetch = mock;
    await api.interpretPlan(
      [{ id: 's1', name: 'Main' }],
      [{ id: 't1', start: '17:00', end: '18:00', label: '17:00' }],
      [{ id: 'a1', name: 'Alpha Waves', entity_id: 'unmatched:a1' }],
      'Keep Alpha Waves fixed and reduce high-affinity clashes.',
    );
    const [url, options] = mock.mock.calls[0];
    expect(url).toBe('/api/plan/interpret');
    expect(options.method).toBe('POST');
    const body = JSON.parse(options.body);
    expect(body.stages[0].id).toBe('s1');
    expect(body.slots[0].id).toBe('t1');
    expect(body.acts[0].id).toBe('a1');
    expect(body.instruction).toBe('Keep Alpha Waves fixed and reduce high-affinity clashes.');
  });

  it('templateFestival fetches the empty template', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse({ mode: 'live', acts: [] }));
    globalThis.fetch = mock;
    const body = await api.templateFestival();
    expect(body.mode).toBe('live');
    expect(mock.mock.calls[0][0]).toBe('/api/festival/template');
  });
});
