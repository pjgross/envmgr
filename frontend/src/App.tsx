import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { RootState } from './store';
import { authService } from './services/authService';
import { setCredentials, logout } from './store/authSlice';
import Login from './pages/Login';

import ImpersonationBanner from './components/ImpersonationBanner';
import AppLayout from './components/AppLayout';
import NotFound from './components/NotFound';

// Route components are code-split: the app shipped as a single 3.4 MB chunk,
// so every visitor downloaded every page — including the ELK layout engine and
// FullCalendar — before the login form could render.
const AdminLayout = lazy(() => import('./pages/admin/AdminLayout'));
const ApiKeyManagement = lazy(() => import('./pages/admin/ApiKeyManagement'));
const BookingCalendar = lazy(() => import('./pages/bookings/BookingCalendar'));
const BookingDetail = lazy(() => import('./pages/bookings/BookingDetail'));
const BookingList = lazy(() => import('./pages/bookings/BookingList'));
const BuildDetail = lazy(() => import('./pages/builds/BuildDetail'));
const BuildList = lazy(() => import('./pages/builds/BuildList'));
const ChangeRequestDetail = lazy(() => import('./pages/change-requests/ChangeRequestDetail'));
const ChangeRequestList = lazy(() => import('./pages/change-requests/ChangeRequestList'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const DeploymentDetail = lazy(() => import('./pages/deployments/DeploymentDetail'));
const DeploymentList = lazy(() => import('./pages/deployments/DeploymentList'));
const DoraDashboard = lazy(() => import('./pages/insights/DoraDashboard'));
const EntityConfig = lazy(() => import('./pages/admin/EntityConfig'));
const EnvironmentCompare = lazy(() => import('./pages/environments/EnvironmentCompare'));
const EnvironmentDetail = lazy(() => import('./pages/environments/EnvironmentDetail'));
const EnvironmentList = lazy(() => import('./pages/environments/EnvironmentList'));
const EnvironmentRequestDetail = lazy(() => import('./pages/environments/EnvironmentRequestDetail'));
const EnvironmentRequestForm = lazy(() => import('./pages/environments/EnvironmentRequestForm'));
const EnvironmentRequestList = lazy(() => import('./pages/environments/EnvironmentRequestList'));
const GitHubIntegration = lazy(() => import('./pages/admin/GitHubIntegration'));
const HealthDashboard = lazy(() => import('./pages/insights/HealthDashboard'));
const ImportPage = lazy(() => import('./pages/import/ImportPage'));
const IncidentDetail = lazy(() => import('./pages/incidents/IncidentDetail'));
const IncidentForm = lazy(() => import('./pages/incidents/IncidentForm'));
const IncidentList = lazy(() => import('./pages/incidents/IncidentList'));
const InfrastructureComponentList = lazy(() => import('./pages/infrastructure/InfrastructureComponentList'));
const ProjectDetail = lazy(() => import('./pages/admin/ProjectDetail'));
const Projects = lazy(() => import('./pages/admin/Projects'));
const RaidSettings = lazy(() => import('./pages/admin/RaidSettings'));
const ReleaseAnalytics = lazy(() => import('./pages/releases/ReleaseAnalytics'));
const ReleaseCalendar = lazy(() => import('./pages/releases/ReleaseCalendar'));
const ReleaseDetail = lazy(() => import('./pages/releases/ReleaseDetail'));
const ReleaseList = lazy(() => import('./pages/releases/ReleaseList'));
const ReleaseTemplateForm = lazy(() => import('./pages/admin/release-templates/ReleaseTemplateForm'));
const ReleaseTemplateLibrary = lazy(() => import('./pages/admin/release-templates/ReleaseTemplateLibrary'));
const ReleaseTimeline = lazy(() => import('./pages/releases/ReleaseTimeline'));
const ScopeWindows = lazy(() => import('./pages/releases/ScopeWindows'));
const SystemCatalog = lazy(() => import('./pages/systems/SystemCatalog'));
const SystemDetail = lazy(() => import('./pages/systems/SystemDetail'));
const TenantDetail = lazy(() => import('./pages/admin/TenantDetail'));
const TenantList = lazy(() => import('./pages/admin/TenantList'));
const TenantScopeChangeRules = lazy(() => import('./pages/admin/TenantScopeChangeRules'));
const TenantSettings = lazy(() => import('./pages/tenant/TenantSettings'));
const UserGroupDetail = lazy(() => import('./pages/admin/UserGroupDetail'));
const UserGroups = lazy(() => import('./pages/admin/UserGroups'));
const UserManagement = lazy(() => import('./pages/tenant/UserManagement'));

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
      {/* One boundary around all routes: each lazy page resolves on first
          navigation to it, showing the same spinner the app already uses for
          auth bootstrap rather than a blank screen. */}
      <Suspense fallback={<FullPageSpinner />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={isAuthenticated ? <AppLayout /> : <Navigate to="/login" />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/insights/dora" element={<DoraDashboard />} />
            <Route path="/insights/health" element={<HealthDashboard />} />
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
            <Route
              path="/tenant/groups"
              element={
                <PrivateRoute>
                  <UserGroups />
                </PrivateRoute>
              }
            />
            <Route
              path="/tenant/groups/:id"
              element={
                <PrivateRoute>
                  <UserGroupDetail />
                </PrivateRoute>
              }
            />
            <Route
              path="/tenant/projects"
              element={
                <PrivateRoute>
                  <Projects />
                </PrivateRoute>
              }
            />
            <Route
              path="/tenant/projects/:id"
              element={
                <PrivateRoute>
                  <ProjectDetail />
                </PrivateRoute>
              }
            />
            <Route path="/systems" element={<SystemCatalog />} />
            <Route path="/systems/:id" element={<SystemDetail />} />
            <Route path="/environments" element={<EnvironmentList />} />
            <Route path="/environments/compare" element={<EnvironmentCompare />} />
            <Route path="/environments/:id" element={<EnvironmentDetail />} />
            <Route path="/environment-requests" element={<EnvironmentRequestList />} />
            <Route path="/environment-requests/new" element={<EnvironmentRequestForm />} />
            <Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
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
            <Route
              path="/admin/github"
              element={
                <PrivateRoute requiredRole="Admin">
                  <AdminLayout />
                </PrivateRoute>
              }
            >
              <Route index element={<GitHubIntegration />} />
            </Route>
          </Route>
          <Route path="/" element={<Navigate to={isAuthenticated ? '/dashboard' : '/login'} />} />
            <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
