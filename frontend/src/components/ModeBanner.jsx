export default function ModeBanner({ health, analysisMode }) {
  if (!health) return null;
  const live = health.qloo_configured;
  const modeLabel = {
    demo: 'analysis: demo data',
    live: 'analysis: live Qloo data',
    mixed: 'analysis: mixed demo + live',
    unmatched: 'analysis: no Qloo profiles',
  }[analysisMode] ?? null;
  const modeStamp = {
    demo: 'stamp-demo',
    live: 'stamp-live',
    unmatched: 'stamp-missing',
  }[analysisMode] ?? '';
  return (
    <div className="mode-stamp">
      <span className={`stamp ${live ? 'stamp-live' : 'stamp-demo'}`}>
        {live ? 'Live Qloo data' : 'Demo mode — no API key'}
      </span>
      {modeLabel && (
        <span className={`stamp ${modeStamp}`} title="Data source used for the current similarity analysis">
          {modeLabel}
        </span>
      )}
      <span className="stamp">v{health.version}</span>
    </div>
  );
}
