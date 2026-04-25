import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ApiKeyCreatedDialog from '../ApiKeyCreatedDialog';

describe('ApiKeyCreatedDialog', () => {
  it('renders the raw key', () => {
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={() => {}} />,
    );
    expect(screen.getByDisplayValue('em_abc123')).toBeInTheDocument();
  });

  it('calls navigator.clipboard.writeText on copy click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={() => {}} />,
    );
    fireEvent.click(screen.getByLabelText('copy'));
    expect(writeText).toHaveBeenCalledWith('em_abc123');
  });

  it('calls onDismiss when the button is clicked', () => {
    const onDismiss = vi.fn();
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={onDismiss} />,
    );
    fireEvent.click(screen.getByText("I've copied it"));
    expect(onDismiss).toHaveBeenCalled();
  });
});
