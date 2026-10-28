import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SimilarityError from './SimilarityError.jsx';

describe('SimilarityError', () => {
  it('names the artists and the failure instead of showing an empty grid', () => {
    render(
      <SimilarityError
        error={{ message: 'Qloo timed out', artists: ['Alpha Waves', 'Beta Choir'] }}
        onRetry={vi.fn()}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Similarity data could not be loaded');
    expect(alert).toHaveTextContent('Failed for 2 artists: Alpha Waves, Beta Choir');
    expect(alert).toHaveTextContent('Qloo timed out');
  });

  it('offers a retry and locks it while a retry is in flight', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender } = render(
      <SimilarityError error={{ message: 'HTTP 503', artists: ['Alpha'] }} onRetry={onRetry} />,
    );

    await user.click(screen.getByRole('button', { name: /^retry$/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(
      <SimilarityError error={{ message: 'HTTP 503', artists: ['Alpha'] }} onRetry={onRetry} retrying />,
    );
    const retrying = screen.getByRole('button', { name: /retrying/i });
    expect(retrying).toBeDisabled();
  });

  it('still explains itself when no artist list is available', () => {
    render(<SimilarityError error={{ message: 'Network down' }} onRetry={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Network down');
    expect(screen.getByRole('alert')).toHaveTextContent('Failed for 0 artists');
  });
});
