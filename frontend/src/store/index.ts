import { configureStore } from '@reduxjs/toolkit'
import authReducer from './authSlice'
import adminReducer from './adminSlice'
import tenantAdminReducer from './tenantAdminSlice'
import systemReducer from './systemSlice'
import environmentReducer from './environmentSlice'
import dependencyReducer from './dependencySlice'
import bookingReducer from './bookingSlice'
import versionReducer from './versionSlice'
import customFieldReducer from './customFieldSlice'
import topologyReducer from './topologySlice'
import bookingLifecycleReducer from './bookingLifecycleSlice'

export const store = configureStore({
    reducer: {
        auth: authReducer,
        admin: adminReducer,
        tenantAdmin: tenantAdminReducer,
        system: systemReducer,
        environment: environmentReducer,
        dependency: dependencyReducer,
        booking: bookingReducer,
        version: versionReducer,
        customField: customFieldReducer,
        topology: topologyReducer,
        bookingLifecycle: bookingLifecycleReducer,
    },
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
