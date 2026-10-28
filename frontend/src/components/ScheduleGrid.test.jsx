import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import ScheduleGrid from './ScheduleGrid.jsx';

const STAGES = [
  { id: 'main', name: 'Main Stage' },
  { id: 'pulse', name: 'Pulse Tent' },
];
const SLOTS = [
  { id: 't1', label: '17:00', end: '18:00' },
  { id: 't2', label: '18:00', end: '19:00' },
];

const act = (id, name, stage, slot) => ({
  id,
  name,
  entity_id: `e-${id}`,
  stage_id: stage,
  slot_id: slot,
  duration_min: 60,
  fixed: false,
});

describe('ScheduleGrid', () => {
  it('shows every act when two share a cell instead of hiding one', () => {
    const { container } = render(
      <ScheduleGrid
        stages={STAGES}
        slots={SLOTS}
        acts={[act('a1', 'Alpha', 'main', 't1'), act('a2', 'Beta', 'main', 't1')]}
        clashes={[]}
        profiles={{}}
        applied={false}
        moveCount={0}
      />,
    );

    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    const cell = container.querySelector('.cell.collision');
    expect(cell).not.toBeNull();
    expect(cell.querySelectorAll('.act-chip')).toHaveLength(2);
    expect(within(cell).getByText('double-booked')).toHaveClass('stamp-clash');
  });

  it('renders one chip for a single booking without a collision mark', () => {
    const { container } = render(
      <ScheduleGrid
        stages={STAGES}
        slots={SLOTS}
        acts={[act('a1', 'Alpha', 'main', 't1')]}
        clashes={[]}
        profiles={{}}
        applied={false}
        moveCount={0}
      />,
    );
    expect(container.querySelectorAll('.act-chip')).toHaveLength(1);
    expect(container.querySelector('.cell.collision')).toBeNull();
    expect(screen.queryByText('double-booked')).not.toBeInTheDocument();
  });
});
