import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import TopologyToolbar from '../TopologyToolbar';
import type { SearchableComponent } from '../topologyFocus';

const comps: SearchableComponent[] = [
  { id: 5, name: 'Customer API Server', systemName: 'Customer' },
  { id: 1, name: 'Mortage Server', systemName: 'Mortgage' },
];

describe('TopologyToolbar', () => {
  it('shows matching components as the user types and calls onSelect on click', async () => {
    const onSelect = vi.fn();
    render(<TopologyToolbar components={comps} onSelect={onSelect} availableTypes={[]} hiddenTypes={new Set()} onToggleType={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/search component/i), 'mort');
    const option = await screen.findByText('Mortage Server');
    expect(screen.queryByText('Customer API Server')).not.toBeInTheDocument();
    await userEvent.click(option);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('shows no result list for an empty query', () => {
    render(<TopologyToolbar components={comps} onSelect={vi.fn()} availableTypes={[]} hiddenTypes={new Set()} onToggleType={() => {}} />);
    expect(screen.queryByText('Mortage Server')).not.toBeInTheDocument();
  });

  it('selects the highlighted result via ArrowDown + Enter', async () => {
    const onSelect = vi.fn();
    render(<TopologyToolbar components={comps} onSelect={onSelect} availableTypes={[]} hiddenTypes={new Set()} onToggleType={() => {}} />);
    const input = screen.getByPlaceholderText(/search component/i);
    await userEvent.type(input, 'server'); // matches both (Customer API Server, Mortage Server)
    await userEvent.keyboard('{ArrowDown}{Enter}'); // highlight starts at 0, ArrowDown -> index 1
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it('opens the Types menu and toggles a type', async () => {
    const onToggleType = vi.fn();
    render(
      <TopologyToolbar
        components={comps}
        onSelect={vi.fn()}
        availableTypes={['api_gateway', 'database']}
        hiddenTypes={new Set()}
        onToggleType={onToggleType}
      />
    );
    await userEvent.click(screen.getByRole('button', { name: /types/i }));
    const dbRow = await screen.findByText('database');
    await userEvent.click(dbRow);
    expect(onToggleType).toHaveBeenCalledWith('database');
    expect(screen.getByRole('menu')).toBeInTheDocument(); // multi-select: menu stays open after toggle
  });
});
