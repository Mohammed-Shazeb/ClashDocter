export default function ModeBanner({ health, analysisMode }) {
  if (!health) return null;
  const live = health.qloo_configured;
  const modeLabel = {
    demo: 'analysis: curated demo dataset',
    live: 'analysis: live Qloo data',
    mixed: 'analysis: mixed demo + live',
    unmatched: 'analysis: no Qloo profiles',
  }[analysisMode] ?? null;
  const modeStamp = {
    demo: 'stamp-demo',
    live: 'stamp-live',
    unmatched: 'stamp-missing',
  }[analysisMode] ?? '';
  const modeTitle = {
    demo: 'Deterministic curated dataset: fictional artists with hand-authored taste profiles. Not live Qloo output.',
    live: 'Taste tags fetched from Qloo for the artists in this lineup.',
    mixed: 'Hand-authored demo profiles and live Qloo profiles are both present in this analysis.',
    unmatched: 'No artist in this lineup has a confirmed Qloo profile, so nothing is scored.',
  }[analysisMode] ?? 'Data source used for the current similarity analysis';
  return (
    <div className="mode-stamp">
      <span
        className={`stamp ${live ? 'stamp-live' : 'stamp-demo'}`}
        title={
          live
            ? 'A Qloo API key is configured, so analysis can use live tag data.'
            : 'No Qloo API key is configured, so the app runs on the curated demo dataset only.'
        }
      >
        {live ? 'Live Qloo data' : 'Demo mode — no API key'}
      </span>
      {modeLabel && (
        <span className={`stamp ${modeStamp}`} title={modeTitle}>
          {modeLabel}
        </span>
      )}
      <span className="stamp">v{health.version}</span>
    </div>
  );
}
