import { configureStore } from '@reduxjs/toolkit'
import authReducer from './authSlice'
import adminReducer from './adminSlice'
import tenantAdminReducer from './tenantAdminSlice'
import systemReducer from './systemSlice'

export const store = configureStore({
    reducer: {
        auth: authReducer,
        admin: adminReducer,
        tenantAdmin: tenantAdminReducer,
        system: systemReducer,
    },
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
