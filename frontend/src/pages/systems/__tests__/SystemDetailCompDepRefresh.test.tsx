import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import SystemDetail from '../SystemDetail';

// Real wiring test for the bug: "adding a component dependency successfully
// adds the entry but does not refresh the page, so you have to switch tabs
// and then back to see the new entry." The Component Dependencies tab holds
// its list in local state (`allCompDeps`), populated by an effect keyed on
// `[tab, subsystems]`. The create handler used to call `setTab(3)` to force
// a "refresh" — a no-op, since the Add button lives on tab 3 and the value
// doesn't change, so React bails out and the effect never reruns.

// vi.mock factories below are hoisted above normal top-level const
// declarations, so the fixtures they reference must go through vi.hoisted.
const { SYSTEM, SUBSYSTEMS, NEW_COMPONENT_DEPENDENCY } = vi.hoisted(() => ({
  SYSTEM: {
    id: 1,
    tenant_id: 1,
    name: 'System A',
    description: null,
    github_repository_url: null,
    custom_fields: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  SUBSYSTEMS: [
    {
      id: 10,
      name: 'Auth',
      description: null,
      system_id: 1,
      tenant_id: 1,
      component_type: 'other',
      technology: null,
      custom_fields: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 11,
      name: 'API',
      description: null,
      system_id: 1,
      tenant_id: 1,
      component_type: 'other',
      technology: null,
      custom_fields: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  ],
  NEW_COMPONENT_DEPENDENCY: {
    id: 100,
    from_subsystem_id: 10,
    to_subsystem_id: 11,
    dependency_type: 'api_call' as const,
    direction: 'one_way' as const,
    label: null,
    protocol: null,
    port: null,
    source: 'manual' as const,
    tenant_id: 1,
    to_subsystem: { id: 11, name: 'API', description: null, system_id: 1 },
    from_subsystem: { id: 10, name: 'Auth', description: null, system_id: 1 },
    is_incoming: false,
    endpoints: [],
  },
}));

// No HTTP — this test is about the wiring between the create action and the
// component-dependency reload, not about what the server returns.
vi.mock('../../../services/systemService', () => ({
  systemService: {
    getSystem: vi.fn().mockResolvedValue(SYSTEM),
    listSubSystems: vi.fn().mockResolvedValue(SUBSYSTEMS),
    listSystems: vi.fn().mockResolvedValue({ rows: [SYSTEM], total: 1 }),
  },
}));

vi.mock('../../../services/dependencyService', () => ({
  dependencyService: {
    listSystemDependencies: vi.fn().mockResolvedValue([]),
    listComponentDependencies: vi.fn().mockResolvedValue([]),
    createComponentDependency: vi.fn().mockResolvedValue(NEW_COMPONENT_DEPENDENCY),
  },
}));

vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

import { dependencyService } from '../../../services/dependencyService';

// The Add Component Dependency dialog's <Select> elements don't set
// `labelId`, so their accessible name (via aria-labelledby) is empty even
// though an <InputLabel> sits right next to them in the same <FormControl> —
// a pre-existing a11y gap in SystemDetail.tsx, out of scope for this fix.
// Locate the combobox the same way a sighted user would: by the label text
// inside its FormControl.
function comboboxByLabel(container: HTMLElement, labelText: string) {
  const label = within(container).getByText(labelText);
  const formControl = label.closest('.MuiFormControl-root');
  if (!formControl) throw new Error(`No FormControl ancestor found for label "${labelText}"`);
  return within(formControl as HTMLElement).getByRole('combobox');
}

function renderDetail() {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/systems/1']}>
        <Routes>
          <Route path="/systems/:id" element={<SystemDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>
  );
}

describe('SystemDetail component dependency create refresh', () => {
  beforeEach(() => {
    // openCompDepCreate hits the API directly with `fetch` (not through a
    // service module) to build the cross-system "To SubSystem" picker.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () =>
          SUBSYSTEMS.map((s) => ({ id: s.id, name: s.name, system_id: s.system_id })),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reloads the component dependency list after a successful create, without a tab change', async () => {
    renderDetail();

    // Let the initial page load settle.
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'System A' })).toBeInTheDocument()
    );

    // Switch to the Component Dependencies tab — this is the only tab change
    // in the whole test, establishing the baseline load.
    await userEvent.click(screen.getByRole('tab', { name: 'Component Deps' }));

    await waitFor(() =>
      expect(dependencyService.listComponentDependencies).toHaveBeenCalled()
    );

    vi.mocked(dependencyService.listComponentDependencies).mockClear();

    // Open the Add dialog and complete the form.
    await userEvent.click(screen.getByRole('button', { name: 'Add Component Dependency' }));

    const dialog = await screen.findByRole('dialog');

    await userEvent.click(comboboxByLabel(dialog, 'From SubSystem'));
    await userEvent.click(await screen.findByRole('option', { name: 'Auth' }));

    await userEvent.click(comboboxByLabel(dialog, 'To SubSystem'));
    await userEvent.click(await screen.findByRole('option', { name: 'System A / API' }));

    await userEvent.click(within(dialog).getByRole('button', { name: 'Add' }));

    await waitFor(() =>
      expect(dependencyService.createComponentDependency).toHaveBeenCalled()
    );

    // The bug: after a successful create, the list must be reloaded — with
    // no tab click in between (the Add button lives on tab 3 already).
    await waitFor(() =>
      expect(dependencyService.listComponentDependencies).toHaveBeenCalled()
    );
  });
});
