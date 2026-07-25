import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReactFlowProvider } from 'reactflow';
import SubsystemNode from '../SubsystemNode';
import type { RenderSubsystem } from '../topologyElkGraph';

function renderNode(sub: RenderSubsystem) {
  return render(
    <ReactFlowProvider>
      <SubsystemNode data={{ label: sub, color: '#388e3c' }} />
    </ReactFlowProvider>,
  );
}

const base: RenderSubsystem = {
  id: 1, name: 'billing-api', system_id: 2, component_type: 'web_service', technology: null,
};

describe('SubsystemNode mocked styling', () => {
  it('shows a "mocked" caption when the subsystem is mocked', () => {
    renderNode({ ...base, is_mocked: true });
    expect(screen.getByText('mocked')).toBeInTheDocument();
  });

  it('omits the "mocked" caption for a normal subsystem', () => {
    renderNode({ ...base, is_mocked: false });
    expect(screen.queryByText('mocked')).not.toBeInTheDocument();
  });

  it('omits the "mocked" caption when is_mocked is absent (systems path)', () => {
    renderNode(base);
    expect(screen.queryByText('mocked')).not.toBeInTheDocument();
  });
});
