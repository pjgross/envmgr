import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { useConfirm } from '../useConfirm';

function Probe({ destructive }: { destructive: boolean }) {
  const { confirm, dialog } = useConfirm();

  useEffect(() => {
    void confirm({ message: 'x', destructive });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>{dialog}</>;
}

describe('useConfirm — P2-6: destructive confirms focus Cancel', () => {
  it('focuses Cancel for a destructive confirm so a stray Enter does not delete', async () => {
    render(<Probe destructive />);
    expect(await screen.findByRole('button', { name: 'Cancel' })).toHaveFocus();
  });

  it('focuses Confirm for a non-destructive confirm', async () => {
    render(<Probe destructive={false} />);
    expect(await screen.findByRole('button', { name: 'Confirm' })).toHaveFocus();
  });
});
