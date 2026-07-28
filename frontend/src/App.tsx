import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { RootState } from './store';
import { authService } from './services/authService';
import { setCredentials, logout } from './store/authSlice';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import TenantList from './pages/admin/TenantList';
import TenantDetail from './pages/admin/TenantDetail';
import TenantSettings from './pages/tenant/TenantSettings';
import UserManagement from './pages/tenant/UserManagement';
import SystemCatalog from './pages/systems/SystemCatalog';
import SystemDetail from './pages/systems/SystemDetail';
import EnvironmentList from './pages/environments/EnvironmentList';
import EnvironmentDetail from './pages/environments/EnvironmentDetail';
import BookingCalendar from './pages/bookings/BookingCalendar';
import BookingList from './pages/bookings/BookingList';
import BookingDetail from './pages/bookings/BookingDetail';
import ChangeRequestList from './pages/change-requests/ChangeRequestList';
import ChangeRequestDetail from './pages/change-requests/ChangeRequestDetail';
import ReleaseList from './pages/releases/ReleaseList';
import ReleaseDetail from './pages/releases/ReleaseDetail';
import ReleaseCalendar from './pages/releases/ReleaseCalendar';
import ReleaseTimeline from './pages/releases/ReleaseTimeline';
import ScopeWindows from './pages/releases/ScopeWindows';
import ReleaseAnalytics from './pages/releases/ReleaseAnalytics';
import ReleaseTemplateLibrary from './pages/admin/release-templates/ReleaseTemplateLibrary';
import ReleaseTemplateForm from './pages/admin/release-templates/ReleaseTemplateForm';
import InfrastructureComponentList from './pages/infrastructure/InfrastructureComponentList';
import ImportPage from './pages/import/ImportPage';
import AdminLayout from './pages/admin/AdminLayout';
import EntityConfig from './pages/admin/EntityConfig';
import TenantScopeChangeRules from './pages/admin/TenantScopeChangeRules';
import ApiKeyManagement from './pages/admin/ApiKeyManagement';
import RaidSettings from './pages/admin/RaidSettings';
import BuildList from './pages/builds/BuildList';
import BuildDetail from './pages/builds/BuildDetail';
import DeploymentList from './pages/deployments/DeploymentList';
import DeploymentDetail from './pages/deployments/DeploymentDetail';
import IncidentList from './pages/incidents/IncidentList';
import IncidentForm from './pages/incidents/IncidentForm';
import IncidentDetail from './pages/incidents/IncidentDetail';
import ImpersonationBanner from './components/ImpersonationBanner';
import AppLayout from './components/AppLayout';
import NotFound from './components/NotFound';

function FullPageSpinner() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
      <CircularProgress />
    </Box>
  );
}

function PrivateRoute({
  children,
  requireMasterAdmin = false,
  requiredRole,
}: {
  children: React.ReactNode;
  requireMasterAdmin?: boolean;
  requiredRole?: string;
}) {
  const { user, isAuthenticated, authInitialized } = useSelector((state: RootState) => state.auth);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  // On a hard reload the token is present but the user is still loading; wait for it
  // rather than evaluating the role check against a null user (which would bounce to /dashboard).
  if (!authInitialized || !user) return <FullPageSpinner />;
  if (requireMasterAdmin && !user.is_master_admin) return <Navigate to="/dashboard" replace />;
  if (requiredRole && user.role !== requiredRole && !user.is_master_admin)
    return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

function App() {
  const dispatch = useDispatch();
  const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated);
  const user = useSelector((state: RootState) => state.auth.user);
  const token = useSelector((state: RootState) => state.auth.token);

  useEffect(() => {
    if (!isAuthenticated || user || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await authService.getCurrentUser();
        if (!cancelled) dispatch(setCredentials({ user: me, token }));
      } catch {
        if (!cancelled) dispatch(logout());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, user, token, dispatch]);

  return (
    <BrowserRouter>
      <ImpersonationBanner />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={isAuthenticated ? <AppLayout /> : <Navigate to="/login" />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route
            path="/admin/tenants"
            element={
              <PrivateRoute requireMasterAdmin>
                <TenantList />
              </PrivateRoute>
            }
          />
          <Route
            path="/admin/tenants/:tenantId"
            element={
              <PrivateRoute requireMasterAdmin>
                <TenantDetail />
              </PrivateRoute>
            }
          />
          <Route
            path="/tenant/settings"
            element={
              <PrivateRoute requiredRole="Admin">
                <TenantSettings />
              </PrivateRoute>
            }
          />
          <Route
            path="/tenant/users"
            element={
              <PrivateRoute requiredRole="Admin">
                <UserManagement />
              </PrivateRoute>
            }
          />
          <Route path="/systems" element={<SystemCatalog />} />
          <Route path="/systems/:id" element={<SystemDetail />} />
          <Route path="/environments" element={<EnvironmentList />} />
          <Route path="/environments/:id" element={<EnvironmentDetail />} />
          <Route path="/bookings" element={<Navigate replace to="/bookings/calendar" />} />
          <Route path="/bookings/calendar" element={<BookingCalendar />} />
          <Route path="/bookings/list" element={<BookingList />} />
          <Route path="/bookings/:id" element={<BookingDetail />} />
          <Route path="/change-requests" element={<ChangeRequestList />} />
          <Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
          <Route path="/releases" element={<ReleaseList />} />
          <Route path="/releases/new" element={<ReleaseList />} />
          <Route path="/releases/calendar" element={<ReleaseCalendar />} />
          <Route path="/releases/timeline" element={<ReleaseTimeline />} />
          <Route path="/releases/scope-windows" element={<ScopeWindows />} />
          <Route path="/releases/analytics" element={<ReleaseAnalytics />} />
          <Route path="/releases/:id" element={<ReleaseDetail />} />
          <Route
            path="/admin/release-templates"
            element={
              <PrivateRoute requiredRole="Admin">
                <ReleaseTemplateLibrary />
              </PrivateRoute>
            }
          />
          <Route
            path="/admin/release-templates/:id"
            element={
              <PrivateRoute requiredRole="Admin">
                <ReleaseTemplateForm />
              </PrivateRoute>
            }
          />
          <Route path="/builds" element={<BuildList />} />
          <Route path="/builds/:id" element={<BuildDetail />} />
          <Route path="/deployments" element={<DeploymentList />} />
          <Route path="/deployments/:id" element={<DeploymentDetail />} />
          <Route path="/incidents" element={<IncidentList />} />
          <Route path="/incidents/new" element={<IncidentForm />} />
          <Route path="/incidents/:id" element={<IncidentDetail />} />
          <Route path="/incidents/:id/edit" element={<IncidentForm />} />
          <Route path="/infrastructure/hosts" element={<InfrastructureComponentList />} />
          <Route path="/import" element={<ImportPage />} />
          <Route
            path="/admin/config"
            element={
              <PrivateRoute requiredRole="Admin">
                <AdminLayout />
              </PrivateRoute>
            }
          >
            <Route path=":entityType" element={<EntityConfig />} />
          </Route>
          <Route
            path="/admin/scope-change-rules"
            element={
              <PrivateRoute requiredRole="Admin">
                <AdminLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<TenantScopeChangeRules />} />
          </Route>
          <Route
            path="/tenant/api-keys"
            element={
              <PrivateRoute requiredRole="Admin">
                <AdminLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<ApiKeyManagement />} />
          </Route>
          <Route
            path="/tenant/raid-settings"
            element={
              <PrivateRoute requiredRole="Admin">
                <AdminLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<RaidSettings />} />
          </Route>
        </Route>
        <Route path="/" element={<Navigate to={isAuthenticated ? '/dashboard' : '/login'} />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
