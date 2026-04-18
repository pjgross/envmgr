import { configureStore } from '@reduxjs/toolkit'
import authReducer from './authSlice'
import adminReducer from './adminSlice'
import tenantAdminReducer from './tenantAdminSlice'
import systemReducer from './systemSlice'
import environmentReducer from './environmentSlice'
import dependencyReducer from './dependencySlice'
import bookingReducer from './bookingSlice'
import bookingRequestReducer from './bookingRequestSlice'
import versionReducer from './versionSlice'
import customFieldReducer from './customFieldSlice'
import topologyReducer from './topologySlice'
import bookingLifecycleReducer from './bookingLifecycleSlice'
import componentTypeReducer from './componentTypeSlice'
import uiReducer from './uiSlice'

export const store = configureStore({
    reducer: {
        auth: authReducer,
        ui: uiReducer,
        admin: adminReducer,
        tenantAdmin: tenantAdminReducer,
        system: systemReducer,
        environment: environmentReducer,
        dependency: dependencyReducer,
        booking: bookingReducer,
        bookingRequest: bookingRequestReducer,
        version: versionReducer,
        customField: customFieldReducer,
        topology: topologyReducer,
        bookingLifecycle: bookingLifecycleReducer,
        componentType: componentTypeReducer,
    },
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
