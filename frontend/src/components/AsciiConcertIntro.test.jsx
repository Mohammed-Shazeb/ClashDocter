import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AsciiConcertIntro from './AsciiConcertIntro.jsx';

describe('AsciiConcertIntro', () => {
  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const openDrawer = () =>
    fireEvent.click(screen.getByRole('button', { name: /Tune Attributes/i }));

  it('renders the brand and Get Started with the tuner drawer closed by default', () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    expect(screen.getByText('CLASHDOCTOR')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
    expect(screen.getByLabelText('Studio attribute tuner')).toHaveClass('cd-hidden');
  });

  it('opens the full tuner drawer on demand', () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    openDrawer();
    expect(screen.getByLabelText('Studio attribute tuner')).not.toHaveClass('cd-hidden');
    expect(screen.getByText('Studio Attribute Tuner')).toBeInTheDocument();
    expect(screen.getAllByRole('slider')).toHaveLength(20);
    expect(screen.getByRole('checkbox', { name: /Articulated Hand Fingers/i })).toBeChecked();
    expect(screen.getByLabelText(/Character Ramp/i)).toHaveValue('portrait');
  });

  it('shows the shipped default values on load', () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    openDrawer();
    expect(screen.getByLabelText(/Animation Speed/i)).toHaveValue('2.5');
    expect(screen.getByLabelText(/Crowd Dancers Count/i)).toHaveValue('14');
    expect(screen.getByLabelText(/ASCII Line Size/i)).toHaveValue('5');
    expect(screen.getByLabelText(/Spotlight Sweep Speed/i)).toHaveValue('2.5');
  });

  it('updates a slider live and Reset restores every default', () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    openDrawer();
    const speed = screen.getByLabelText(/Animation Speed/i);
    fireEvent.change(speed, { target: { value: '1.25' } });
    expect(speed).toHaveValue('1.25');
    expect(screen.getByText('1.25x')).toBeInTheDocument();

    const fingers = screen.getByRole('checkbox', { name: /Articulated Hand Fingers/i });
    fireEvent.click(fingers);
    expect(fingers).not.toBeChecked();

    fireEvent.change(screen.getByLabelText(/Character Ramp/i), { target: { value: 'classic' } });

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.getByLabelText(/Animation Speed/i)).toHaveValue('2.5');
    expect(screen.getAllByText('2.50x')).toHaveLength(2); // speed + lightSpeed labels
    expect(screen.getByRole('checkbox', { name: /Articulated Hand Fingers/i })).toBeChecked();
    expect(screen.getByLabelText(/Character Ramp/i)).toHaveValue('portrait');
    expect(screen.getByText('Reset to defaults ✓')).toBeInTheDocument();
  });

  it('copies the current settings as JSON', async () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    openDrawer();
    fireEvent.click(screen.getByRole('button', { name: /Copy Settings/i }));
    await waitFor(() =>
      expect(screen.getByText('Settings copied to clipboard ✓')).toBeInTheDocument(),
    );
    const written = navigator.clipboard.writeText.mock.calls[0][0];
    const parsed = JSON.parse(written);
    expect(parsed.speed).toBe(2.5);
    expect(parsed.fingers).toBe(true);
    expect(parsed.rampKey).toBe('portrait');
    expect(parsed.crowdCount).toBe(14);
  });

  it('fades out and calls onGetStarted when Get Started is clicked', async () => {
    const onGetStarted = vi.fn();
    render(<AsciiConcertIntro onGetStarted={onGetStarted} />);
    const cta = screen.getByRole('button', { name: /get started/i });
    fireEvent.click(cta);
    expect(screen.getByText('CLASHDOCTOR').closest('.cd-intro')).toHaveClass('cd-leaving');
    expect(onGetStarted).not.toHaveBeenCalled();
    await waitFor(() => expect(onGetStarted).toHaveBeenCalledTimes(1), { timeout: 1500 });
  });

  it('ignores repeated Get Started clicks during the fade', async () => {
    const onGetStarted = vi.fn();
    render(<AsciiConcertIntro onGetStarted={onGetStarted} />);
    const cta = screen.getByRole('button', { name: /get started/i });
    fireEvent.click(cta);
    fireEvent.click(cta);
    fireEvent.click(cta);
    await waitFor(() => expect(onGetStarted).toHaveBeenCalledTimes(1), { timeout: 1500 });
  });

  it('starts closed and toggles open and shut', async () => {
    render(<AsciiConcertIntro onGetStarted={() => {}} />);
    const drawer = screen.getByLabelText('Studio attribute tuner');
    expect(drawer).toHaveClass('cd-hidden');
    await userEvent.click(screen.getByRole('button', { name: /Tune Attributes/i }));
    expect(drawer).not.toHaveClass('cd-hidden');
    await userEvent.click(screen.getByRole('button', { name: 'Hide' }));
    expect(drawer).toHaveClass('cd-hidden');
  });

  it('unmounts cleanly without leaving body classes behind', () => {
    const { unmount } = render(<AsciiConcertIntro onGetStarted={() => {}} />);
    unmount();
    expect(document.body.classList.contains('cd-intro-open')).toBe(false);
  });
});
