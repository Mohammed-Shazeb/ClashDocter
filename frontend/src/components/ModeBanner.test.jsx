import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ModeBanner from './ModeBanner.jsx';

describe('ModeBanner', () => {
  it('shows demo mode and demo analysis when no key is configured', () => {
    render(
      <ModeBanner
        health={{ version: '0.1.0', qloo_configured: false }}
        analysisMode="demo"
      />,
    );
    expect(screen.getByText('Demo mode — no API key')).toBeInTheDocument();
    const demoStamp = screen.getByText('analysis: curated demo dataset');
    expect(demoStamp).toBeInTheDocument();
    expect(demoStamp).toHaveAttribute(
      'title',
      'Deterministic curated dataset: fictional artists with hand-authored taste profiles. Not live Qloo output.',
    );
    expect(screen.getByText('v0.1.0')).toBeInTheDocument();
  });

  it('shows live mode and live analysis when configured', () => {
    render(
      <ModeBanner
        health={{ version: '0.1.0', qloo_configured: true }}
        analysisMode="live"
      />,
    );
    expect(screen.getByText('Live Qloo data')).toBeInTheDocument();
    expect(screen.getByText('analysis: live Qloo data')).toBeInTheDocument();
  });

  it('labels mixed demo + live analysis', () => {
    render(
      <ModeBanner
        health={{ version: '0.1.0', qloo_configured: true }}
        analysisMode="mixed"
      />,
    );
    expect(screen.getByText('analysis: mixed demo + live')).toBeInTheDocument();
  });
});
