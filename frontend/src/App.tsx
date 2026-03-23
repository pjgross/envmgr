import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { RootState } from './store'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import TenantList from './pages/admin/TenantList'
import TenantDetail from './pages/admin/TenantDetail'
import TenantSettings from './pages/tenant/TenantSettings'
import UserManagement from './pages/tenant/UserManagement'
import SystemCatalog from './pages/systems/SystemCatalog'
import SystemDetail from './pages/systems/SystemDetail'
import ImpersonationBanner from './components/ImpersonationBanner'
import AppLayout from './components/AppLayout'

function PrivateRoute({
    children,
    requireMasterAdmin = false,
    requiredRole,
}: {
    children: React.ReactNode
    requireMasterAdmin?: boolean
    requiredRole?: string
}) {
    const { user, isAuthenticated } = useSelector((state: RootState) => state.auth)
    if (!isAuthenticated) return <Navigate to="/login" replace />
    if (requireMasterAdmin && !user?.is_master_admin) return <Navigate to="/dashboard" replace />
    if (requiredRole && user?.role !== requiredRole && !user?.is_master_admin) return <Navigate to="/dashboard" replace />
    return <>{children}</>
}

function App() {
    const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated)

    return (
        <BrowserRouter>
            <ImpersonationBanner />
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={isAuthenticated ? <AppLayout /> : <Navigate to="/login" />}>
                    <Route path="/dashboard" element={<Dashboard />} />
                    <Route
                        path="/admin/tenants"
                        element={<PrivateRoute requireMasterAdmin><TenantList /></PrivateRoute>}
                    />
                    <Route
                        path="/admin/tenants/:tenantId"
                        element={<PrivateRoute requireMasterAdmin><TenantDetail /></PrivateRoute>}
                    />
                    <Route
                        path="/tenant/settings"
                        element={<PrivateRoute requiredRole="Admin"><TenantSettings /></PrivateRoute>}
                    />
                    <Route
                        path="/tenant/users"
                        element={<PrivateRoute requiredRole="Admin"><UserManagement /></PrivateRoute>}
                    />
                    <Route path="/systems" element={<SystemCatalog />} />
                    <Route path="/systems/:id" element={<SystemDetail />} />
                </Route>
                <Route path="/" element={<Navigate to={isAuthenticated ? "/dashboard" : "/login"} />} />
            </Routes>
        </BrowserRouter>
    )
}

export default App
