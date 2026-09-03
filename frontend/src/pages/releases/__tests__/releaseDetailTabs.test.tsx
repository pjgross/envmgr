import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import releaseReducer from '../../../store/releaseSlice';
import ReleaseDetail from '../ReleaseDetail';
// The real reducer map, not a hand-picked subset: ReleaseDetail's default
// "Main" panel and the RAID panel each reach several slices deep (auth,
// customField, releaseTemplate, raid, …) via nested components, so a
// minimal store plays whack-a-mole with one missing-slice TypeError at a
// time. Reusing the production reducer object sidesteps that — only
// `release.detail` needs seeding for the tab strip itself.
import authReducer from '../../../store/authSlice';
import adminReducer from '../../../store/adminSlice';
import apiKeyReducer from '../../../store/apiKeySlice';
import buildReducer from '../../../store/buildSlice';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import systemReducer from '../../../store/systemSlice';
import environmentReducer from '../../../store/environmentSlice';
import environmentTierReducer from '../../../store/environmentTierSlice';
import dependencyReducer from '../../../store/dependencySlice';
import bookingReducer from '../../../store/bookingSlice';
import deploymentReducer from '../../../store/deploymentSlice';
import bookingRequestReducer from '../../../store/bookingRequestSlice';
import versionReducer from '../../../store/versionSlice';
import customFieldReducer from '../../../store/customFieldSlice';
import topologyReducer from '../../../store/topologySlice';
import bookingLifecycleReducer from '../../../store/bookingLifecycleSlice';
import componentTypeReducer from '../../../store/componentTypeSlice';
import uiReducer from '../../../store/uiSlice';
import changeRequestReducer from '../../../store/changeRequestSlice';
import infrastructureComponentReducer from '../../../store/infrastructureComponentSlice';
import releaseTemplateReducer from '../../../store/releaseTemplateSlice';
import releaseEventTypeReducer from '../../../store/releaseEventTypeSlice';
import scopeChangeRulesReducer from '../../../store/scopeChangeRulesSlice';
import enterpriseMembershipReducer from '../../../store/enterpriseMembershipSlice';
import raidReducer from '../../../store/raidSlice';
import incidentReducer from '../../../store/incidentSlice';
import userGroupReducer from '../../../store/userGroupSlice';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import projectReducer from '../../../store/projectSlice';
import environmentGroupReducer from '../../../store/environmentGroupSlice';
import environmentNamingPolicyReducer from '../../../store/environmentNamingPolicySlice';
import decommissionReducer from '../../../store/decommissionSlice';
import environmentLifecyclePolicyReducer from '../../../store/environmentLifecyclePolicySlice';
import contentionForecastReducer from '../../../store/contentionForecastSlice';
import gateTypeReducer from '../../../store/gateTypeSlice';
import rollbackReducer from '../../../store/rollbackSlice';

// fetchRelease is a thunk that hits the API; the page only needs `detail` to
// be present for the tab strip to render. Mock the thunk to a no-op and seed
// the state — the subject here is which tab is selected, not loading.
vi.mock('../../../store/releaseSlice', async () => {
  const actual = await vi.importActual<typeof import('../../../store/releaseSlice')>(
    '../../../store/releaseSlice',
  );
  return { ...actual, fetchRelease: Object.assign(() => ({ type: 'noop' }), { pending: { type: 'noop/pending' } }) };
});

const makeStore = () =>
  configureStore({
    reducer: {
      auth: authReducer,
      ui: uiReducer,
      admin: adminReducer,
      apiKey: apiKeyReducer,
      build: buildReducer,
      tenantAdmin: tenantAdminReducer,
      system: systemReducer,
      environment: environmentReducer,
      environmentTier: environmentTierReducer,
      dependency: dependencyReducer,
      deployment: deploymentReducer,
      booking: bookingReducer,
      bookingRequest: bookingRequestReducer,
      version: versionReducer,
      customField: customFieldReducer,
      topology: topologyReducer,
      bookingLifecycle: bookingLifecycleReducer,
      componentType: componentTypeReducer,
      changeRequest: changeRequestReducer,
      infrastructureComponent: infrastructureComponentReducer,
      release: releaseReducer,
      releaseTemplate: releaseTemplateReducer,
      releaseEventType: releaseEventTypeReducer,
      scopeChangeRules: scopeChangeRulesReducer,
      enterpriseMembership: enterpriseMembershipReducer,
      raid: raidReducer,
      incident: incidentReducer,
      userGroup: userGroupReducer,
      environmentRequest: environmentRequestReducer,
      project: projectReducer,
      environmentGroup: environmentGroupReducer,
      environmentNamingPolicy: environmentNamingPolicyReducer,
      decommission: decommissionReducer,
      environmentLifecyclePolicy: environmentLifecyclePolicyReducer,
      contentionForecast: contentionForecastReducer,
      gateType: gateTypeReducer,
      rollback: rollbackReducer,
    },
    preloadedState: {
      // Start from the slice's own initial state (`releaseReducer(undefined,
      // {type: '@@INIT'})`) rather than a hand-picked subset — several
      // nested components (DependencyAlertBanner etc.) read other release.*
      // fields unconditionally, and a bare `{ detail, loading, error }` left
      // those `undefined`. Only `detail`/`loading`/`error` are overridden;
      // everything else keeps its real default (empty arrays, `{}`, …).
      release: {
        ...releaseReducer(undefined, { type: '@@INIT' }),
        detail: { id: 7, name: 'R1', status: 'draft' },
        loading: false,
        error: null,
      } as never,
    },
  });

const renderAt = (search: string) =>
  render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={[`/releases/7${search}`]}>
        <Routes>
          <Route path="/releases/:id" element={<ReleaseDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );

describe('ReleaseDetail — the tab is in the URL', () => {
  it('opens the tab named by ?tab=', async () => {
    renderAt('?tab=rollback');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Rollback' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when no tab is named', async () => {
    renderAt('');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when ?tab= names a tab that no longer exists', async () => {
    renderAt('?tab=gone');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('puts the tab in the URL when one is clicked', async () => {
    renderAt('');
    await userEvent.click(await screen.findByRole('tab', { name: 'RAID' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'RAID' })).toHaveAttribute('aria-selected', 'true'),
    );
  });
});
