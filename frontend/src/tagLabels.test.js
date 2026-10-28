import { describe, it, expect } from 'vitest';
import { prettyTag } from './tagLabels.js';

describe('prettyTag', () => {
  it('strips the Qloo URN scheme and subtype prefix', () => {
    expect(prettyTag('urn:tag:genre:music:dream pop')).toBe('dream pop');
    expect(prettyTag('urn:tag:audience:qloo:festival goers')).toBe('festival goers');
    expect(prettyTag('urn:tag:style:qloo:energetic')).toBe('energetic');
    expect(prettyTag('urn:tag:music:qloo:driving')).toBe('driving');
  });

  it('keeps meaningful separators', () => {
    expect(prettyTag('urn:tag:genre:music:dance-pop')).toBe('dance-pop');
    expect(prettyTag('urn:tag:genre:music:hip_hop')).toBe('hip hop');
  });

  it('falls back to the input when there is nothing readable left', () => {
    expect(prettyTag('')).toBe('');
    expect(prettyTag('urn:tag:')).toBe('urn:tag:');
    expect(prettyTag('plain-value')).toBe('plain-value');
  });
});
