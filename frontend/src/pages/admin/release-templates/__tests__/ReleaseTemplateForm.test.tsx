/**
 * Phase 9 C2, task 12: a gate-type selector on each gate skeleton row of
 * the Release Templates admin form. Task 6c made the backend carry
 * `gate_type_id` on a template's gate skeletons; this is the UI half that
 * lets an admin actually build the SIT->UAT->PreProd->Production ladder
 * without calling the API directly.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ReleaseTemplateForm from '../ReleaseTemplateForm';
import releaseTemplateReducer from '../../../../store/releaseTemplateSlice';
import gateTypeReducer from '../../../../store/gateTypeSlice';
import { releaseTemplateService } from '../../../../services/releaseTemplateService';
import { gateTypeService } from '../../../../services/gateTypeService';
import type { ReleaseTemplateResponse, ReleaseTemplateGate } from '../../../../types/releaseTemplate';
import type { GateTypeResponse } from '../../../../types/gateType';

const snackbarSuccess = vi.fn();
const snackbarError = vi.fn();

vi.mock('../../../../hooks/useSnackbar', () => ({
  useSnackbar: () => ({
    success: snackbarSuccess,
    error: snackbarError,
    info: vi.fn(),
    warning: vi.fn(),
    show: vi.fn(),
  }),
}));

vi.mock('../../../../services/releaseTemplateService', () => ({
  releaseTemplateService: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    instantiate: vi.fn(),
  },
}));

vi.mock('../../../../services/gateTypeService', () => ({
  gateTypeService: {
    listGateTypes: vi.fn(),
    createGateType: vi.fn(),
    updateGateType: vi.fn(),
    deleteGateType: vi.fn(),
  },
}));

const SIT_SIGNOFF: GateTypeResponse = {
  id: 1,
  tenant_id: 1,
  name: 'SIT Sign-off',
  description: null,
  category: 'sit',
  failure_behaviour: 'warn',
  expected_evidence: ['test-run-summary'],
  requires_deployment_link: false,
  display_order: 10,
  is_active: true,
};

const UAT_SIGNOFF: GateTypeResponse = {
  id: 2,
  tenant_id: 1,
  name: 'UAT Sign-off',
  description: null,
  category: 'uat',
  failure_behaviour: 'block',
  expected_evidence: ['test-run-summary', 'business-sign-off'],
  requires_deployment_link: true,
  display_order: 20,
  is_active: true,
};

// Referenced by a stored template gate below but no longer active — the
// grandfathering case (Task 6c) the picker must not blank out.
const RETIRED_TYPE: GateTypeResponse = {
  id: 3,
  tenant_id: 1,
  name: 'Legacy Smoke Test',
  description: null,
  category: null,
  failure_behaviour: 'warn',
  expected_evidence: [],
  requires_deployment_link: false,
  display_order: 30,
  is_active: false,
};

function makeTemplate(gates: ReleaseTemplateGate[]): ReleaseTemplateResponse {
  return {
    id: 7,
    tenant_id: 1,
    name: 'Standard Ladder',
    description: null,
    release_type: 'project',
    default_lifecycle_template_id: null,
    phases: [{ name: 'SIT', order: 1, default_duration_days: 5, activities: [] }],
    gates,
    version: 1,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  };
}

function makeStore() {
  return configureStore({
    reducer: { releaseTemplate: releaseTemplateReducer, gateType: gateTypeReducer },
  });
}

function renderForm(initialGates: ReleaseTemplateGate[]) {
  vi.mocked(releaseTemplateService.get).mockResolvedValue(makeTemplate(initialGates));
  const store = makeStore();
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/admin/releases/templates/7']}>
        <Routes>
          <Route path="/admin/releases/templates/:id" element={<ReleaseTemplateForm />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
  return store;
}

describe('ReleaseTemplateForm — gate type selector (task 12)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(gateTypeService.listGateTypes).mockResolvedValue({
      rows: [SIT_SIGNOFF, UAT_SIGNOFF, RETIRED_TYPE],
      total: 3,
    });
  });

  it("choosing a gate type includes gate_type_id in the saved payload", async () => {
    vi.mocked(releaseTemplateService.update).mockResolvedValue(
      makeTemplate([{ name: 'Sign-off', phase_name: null, acceptance_criteria: null, gate_type_id: 2 }])
    );

    renderForm([{ name: 'Sign-off', phase_name: null, acceptance_criteria: null, gate_type_id: null }]);

    await screen.findByDisplayValue('Standard Ladder');

    const combobox = await screen.findByRole('combobox', { name: /gate type/i });
    expect(combobox).toHaveTextContent('Untyped');

    await userEvent.click(combobox);
    await userEvent.click(await screen.findByRole('option', { name: 'UAT Sign-off' }));

    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(releaseTemplateService.update).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          gates: [
            expect.objectContaining({ name: 'Sign-off', gate_type_id: 2 }),
          ],
        })
      )
    );
  });

  it('a gate skeleton left without a type still saves, with no gate_type_id key rejected by the backend', async () => {
    vi.mocked(releaseTemplateService.update).mockResolvedValue(
      makeTemplate([{ name: 'Sign-off', phase_name: null, acceptance_criteria: null, gate_type_id: null }])
    );

    renderForm([{ name: 'Sign-off', phase_name: null, acceptance_criteria: null, gate_type_id: null }]);

    await screen.findByDisplayValue('Standard Ladder');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(releaseTemplateService.update).toHaveBeenCalled());
    const [, payload] = vi.mocked(releaseTemplateService.update).mock.calls[0];
    expect(payload.gates).toHaveLength(1);
    const gate = payload.gates![0] as ReleaseTemplateGate;

    // Backend schema (ReleaseTemplateGate) only accepts name / phase_name /
    // acceptance_criteria / gate_type_id — no stray key would be a 422.
    expect(Object.keys(gate).sort()).toEqual(
      ['acceptance_criteria', 'gate_type_id', 'name', 'phase_name'].sort()
    );
    // Untyped is legitimate — null, not omitted-but-required, and never a
    // string or an invented sentinel.
    expect(gate.gate_type_id === null || gate.gate_type_id === undefined).toBe(true);
  });

  it('renders a stored gate whose type is no longer in the active list, rather than blanking it', async () => {
    renderForm([
      { name: 'Legacy Check', phase_name: null, acceptance_criteria: null, gate_type_id: 3 },
    ]);

    await screen.findByDisplayValue('Standard Ladder');

    const combobox = await screen.findByRole('combobox', { name: /gate type/i });
    await waitFor(() => expect(combobox).toHaveTextContent('Legacy Smoke Test'));
  });

  it('the retired-but-assigned type still appears as a selectable option, marked inactive', async () => {
    renderForm([
      { name: 'Legacy Check', phase_name: null, acceptance_criteria: null, gate_type_id: 3 },
    ]);

    await screen.findByDisplayValue('Standard Ladder');
    const combobox = await screen.findByRole('combobox', { name: /gate type/i });
    await userEvent.click(combobox);

    expect(await screen.findByRole('option', { name: /legacy smoke test \(inactive\)/i })).toBeInTheDocument();
  });
});
