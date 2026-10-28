import { WarningCircle } from '@phosphor-icons/react';

export default function SimilarityError({ error, onRetry, retrying = false }) {
  const artists = error?.artists ?? [];
  return (
    <div className="error-banner compact similarity-error" role="alert">
      <strong>
        <WarningCircle size={15} aria-hidden="true" /> Similarity data could not be loaded.
      </strong>
      <p>
        Failed for {artists.length} artist{artists.length === 1 ? '' : 's'}
        {artists.length ? `: ${artists.join(', ')}` : '.'}
      </p>
      {error?.message && <p>{error.message}</p>}
      <button className="btn btn-small" type="button" onClick={onRetry} disabled={retrying}>
        {retrying ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  );
}
