import { describe, it, expect, beforeEach } from 'vitest';
import {
  SESSION_KEY,
  SESSION_VERSION,
  clearSession,
  loadSession,
  saveSession,
} from './session.js';

const festival = {
  name: 'Saved Fest',
  mode: 'demo',
  stages: [{ id: 'main', name: 'Main' }],
  slots: [{ id: 't1', label: '17:00', start: '17:00', end: '18:00' }],
  acts: [
    {
      id: 'a1',
      name: 'Alpha',
      entity_id: 'e1',
      stage_id: 'main',
      slot_id: 't1',
      duration_min: 60,
      fixed: true,
    },
  ],
};

const preferences = {
  high_affinity_threshold: 0.5,
  high_affinity_weight: 3,
  move_penalty: 0.1,
  max_moves: 5,
};

const state = {
  festival,
  preferences,
  lockSources: { a1: 'planner' },
  applied: true,
  analysis: { initial_clashes: [] },
  similarity: { mode: 'demo', pairs: [] },
};

describe('session storage', () => {
  beforeEach(() => window.localStorage.clear());

  it('round-trips the lineup, assignment, priorities, locks and applied plan', () => {
    saveSession(state);
    const saved = loadSession();
    expect(saved.festival).toEqual(festival);
    expect(saved.preferences).toEqual(preferences);
    expect(saved.lockSources).toEqual({ a1: 'planner' });
    expect(saved.applied).toBe(true);
    expect(saved.analysis).toEqual(state.analysis);
    expect(saved.similarity).toEqual(state.similarity);
  });

  it('records the schema version it wrote', () => {
    saveSession(state);
    const raw = JSON.parse(window.localStorage.getItem(SESSION_KEY));
    expect(raw.version).toBe(SESSION_VERSION);
  });

  it('ignores a payload from another schema version', () => {
    window.localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ version: SESSION_VERSION + 1, festival }),
    );
    expect(loadSession()).toBeNull();
  });

  it('ignores corrupt JSON and incomplete festivals', () => {
    window.localStorage.setItem(SESSION_KEY, '{not json');
    expect(loadSession()).toBeNull();

    window.localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ version: SESSION_VERSION, festival: { acts: [] } }),
    );
    expect(loadSession()).toBeNull();
  });

  it('clears the saved session', () => {
    saveSession(state);
    clearSession();
    expect(window.localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(loadSession()).toBeNull();
  });

  it('does not throw when storage refuses to write', () => {
    const broken = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota');
      },
      removeItem: () => {
        throw new Error('nope');
      },
    };
    expect(() => saveSession(state, broken)).not.toThrow();
    expect(() => clearSession(broken)).not.toThrow();
    expect(loadSession(broken)).toBeNull();
  });
});
