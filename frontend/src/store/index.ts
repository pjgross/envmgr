import { configureStore } from '@reduxjs/toolkit';
import authReducer from './authSlice';
import adminReducer from './adminSlice';
import apiKeyReducer from './apiKeySlice';
import buildReducer from './buildSlice';
import tenantAdminReducer from './tenantAdminSlice';
import systemReducer from './systemSlice';
import environmentReducer from './environmentSlice';
import environmentTierReducer from './environmentTierSlice';
import dependencyReducer from './dependencySlice';
import bookingReducer from './bookingSlice';
import deploymentReducer from './deploymentSlice';
import bookingRequestReducer from './bookingRequestSlice';
import versionReducer from './versionSlice';
import customFieldReducer from './customFieldSlice';
import topologyReducer from './topologySlice';
import bookingLifecycleReducer from './bookingLifecycleSlice';
import componentTypeReducer from './componentTypeSlice';
import uiReducer from './uiSlice';
import changeRequestReducer from './changeRequestSlice';
import infrastructureComponentReducer from './infrastructureComponentSlice';
import releaseReducer from './releaseSlice';
import releaseTemplateReducer from './releaseTemplateSlice';
import releaseEventTypeReducer from './releaseEventTypeSlice';
import scopeChangeRulesReducer from './scopeChangeRulesSlice';
import enterpriseMembershipReducer from './enterpriseMembershipSlice';
import raidReducer from './raidSlice';
import incidentReducer from './incidentSlice';
import userGroupReducer from './userGroupSlice';
import environmentRequestReducer from './environmentRequestSlice';
import projectReducer from './projectSlice';
import environmentGroupReducer from './environmentGroupSlice';
import environmentNamingPolicyReducer from './environmentNamingPolicySlice';
import decommissionReducer from './decommissionSlice';
import environmentLifecyclePolicyReducer from './environmentLifecyclePolicySlice';
import contentionForecastReducer from './contentionForecastSlice';

export const store = configureStore({
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
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
