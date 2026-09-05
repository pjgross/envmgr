import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { RootState } from './store';
import { authService } from './services/authService';
import { setCredentials, logout } from './store/authSlice';
import Login from './pages/Login';

import ImpersonationBanner from './components/ImpersonationBanner';
import AppLayout from './components/AppLayout';
import NotFound from './components/NotFound';
import { LEGACY_REDIRECTS, LegacyRedirectRoute } from './components/legacyRedirects';

// Route components are code-split: the app shipped as a single 3.4 MB chunk,
// so every visitor downloaded every page — including the ELK layout engine and
// FullCalendar — before the login form could render.
const AdminHome = lazy(() => import('./pages/admin/AdminHome'));
const ApiKeyManagement = lazy(() => import('./pages/admin/ApiKeyManagement'));
const BookingCalendar = lazy(() => import('./pages/bookings/BookingCalendar'));
const BookingDetail = lazy(() => import('./pages/bookings/BookingDetail'));
const BookingList = lazy(() => import('./pages/bookings/BookingList'));
const BuildDetail = lazy(() => import('./pages/builds/BuildDetail'));
const BuildList = lazy(() => import('./pages/builds/BuildList'));
const ChangeRequestDetail = lazy(() => import('./pages/change-requests/ChangeRequestDetail'));
const ChangeRequestList = lazy(() => import('./pages/change-requests/ChangeRequestList'));
const ComponentTypesPage = lazy(() => import('./pages/admin/ComponentTypesPage'));
const ContentionEscalations = lazy(
  () => import('./pages/contentions/EscalationWorklist')
);
const Dashboard = lazy(() => import('./pages/Dashboard'));
const MyWork = lazy(() => import('./pages/MyWork'));
const PirActionList = lazy(() => import('./pages/pir/PirActionList'));
const DecommissionWorklist = lazy(() => import('./pages/decommissions/DecommissionWorklist'));
const DeploymentDetail = lazy(() => import('./pages/deployments/DeploymentDetail'));
const DeploymentList = lazy(() => import('./pages/deployments/DeploymentList'));
const DoraDashboard = lazy(() => import('./pages/insights/DoraDashboard'));
const EntityConfig = lazy(() => import('./pages/admin/EntityConfig'));
const EnvironmentCompare = lazy(() => import('./pages/environments/EnvironmentCompare'));
const EnvironmentGroupDetail = lazy(() => import('./pages/environment-groups/EnvironmentGroupDetail'));
const EnvironmentGroups = lazy(() => import('./pages/environment-groups/EnvironmentGroups'));
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
const ProjectDetail = lazy(() => import('./pages/projects/ProjectDetail'));
const Projects = lazy(() => import('./pages/projects/Projects'));
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
const TenantSettings = lazy(() => import('./pages/admin/TenantSettings'));
const UserGroupDetail = lazy(() => import('./pages/admin/UserGroupDetail'));
const UserGroups = lazy(() => import('./pages/admin/UserGroups'));
const UserManagement = lazy(() => import('./pages/admin/UserManagement'));

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

/**
 * `/admin/:entity/:tab` was PR 1's form. The tab is a query param now (§6), so
 * this is a redirect and NOT a LEGACY_REDIRECTS entry: that table answers
 * "this page moved" and is scheduled for deletion one release after PR 1;
 * this answers "a tab is addressed differently". Folding them together would
 * leave the next reader unable to delete either safely.
 */
export function EntityTabRedirect() {
  const { entity, tab } = useParams<{ entity: string; tab: string }>();
  return <Navigate replace to={`/admin/${entity}?tab=${tab}`} />;
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
            <Route path="/my-work" element={<MyWork />} />
            <Route path="/insights/dora" element={<DoraDashboard />} />
            <Route path="/insights/health" element={<HealthDashboard />} />

            {/* Catalogue */}
            <Route path="/systems" element={<SystemCatalog />} />
            <Route path="/systems/:id" element={<SystemDetail />} />
            <Route path="/environments" element={<EnvironmentList />} />
            <Route path="/environments/compare" element={<EnvironmentCompare />} />
            <Route path="/environments/:id" element={<EnvironmentDetail />} />
            <Route path="/infrastructure/hosts" element={<InfrastructureComponentList />} />
            <Route path="/import" element={<ImportPage />} />

            {/* Bookings */}
            <Route path="/bookings" element={<Navigate replace to="/bookings/calendar" />} />
            <Route path="/bookings/calendar" element={<BookingCalendar />} />
            <Route path="/bookings/list" element={<BookingList />} />
            <Route path="/bookings/:id" element={<BookingDetail />} />
            <Route path="/environment-requests" element={<EnvironmentRequestList />} />
            <Route path="/environment-requests/new" element={<EnvironmentRequestForm />} />
            <Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
            <Route path="/change-requests" element={<ChangeRequestList />} />
            <Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
            {/* Readable by any tenant member; writes are gated on the page.
                PrivateRoute (no requiredRole) is still needed here, not just
                the role gate below: it also waits on authInitialized/user
                before rendering, so a hard reload (isAuthenticated true from
                localStorage, user still null) can't compute a page's write
                permissions against a null user. */}
            <Route path="/projects" element={<PrivateRoute><Projects /></PrivateRoute>} />
            <Route path="/projects/:id" element={<PrivateRoute><ProjectDetail /></PrivateRoute>} />
            <Route path="/environment-groups" element={<PrivateRoute><EnvironmentGroups /></PrivateRoute>} />
            <Route path="/environment-groups/:id" element={<PrivateRoute><EnvironmentGroupDetail /></PrivateRoute>} />
            <Route path="/contentions" element={<ContentionEscalations />} />
            <Route path="/decommissions" element={<DecommissionWorklist />} />

            {/* Releases */}
            <Route path="/releases" element={<ReleaseList />} />
            <Route path="/releases/new" element={<ReleaseList />} />
            <Route path="/releases/calendar" element={<ReleaseCalendar />} />
            <Route path="/releases/timeline" element={<ReleaseTimeline />} />
            <Route path="/releases/scope-windows" element={<ScopeWindows />} />
            <Route path="/releases/analytics" element={<ReleaseAnalytics />} />
            <Route path="/releases/:id" element={<ReleaseDetail />} />
            <Route path="/builds" element={<BuildList />} />
            <Route path="/builds/:id" element={<BuildDetail />} />
            <Route path="/deployments" element={<DeploymentList />} />
            <Route path="/deployments/:id" element={<DeploymentDetail />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/new" element={<IncidentForm />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/incidents/:id/edit" element={<IncidentForm />} />
            <Route path="/pir-actions" element={<PirActionList />} />

            {/* Admin mode: every route under /admin renders inside the admin drawer.
                The gate is per route, not on the layout, because User groups is
                readable by any tenant member (B3a) while everything else is Admin. */}
            <Route path="/admin" element={<Outlet />}>
              <Route index element={<PrivateRoute requiredRole="Admin"><AdminHome /></PrivateRoute>} />
              <Route path="users" element={<PrivateRoute requiredRole="Admin"><UserManagement /></PrivateRoute>} />
              <Route path="user-groups" element={<PrivateRoute><UserGroups /></PrivateRoute>} />
              <Route path="user-groups/:id" element={<PrivateRoute><UserGroupDetail /></PrivateRoute>} />
              <Route path="settings" element={<PrivateRoute requiredRole="Admin"><TenantSettings /></PrivateRoute>} />
              <Route path="api-keys" element={<PrivateRoute requiredRole="Admin"><ApiKeyManagement /></PrivateRoute>} />
              <Route path="github" element={<PrivateRoute requiredRole="Admin"><GitHubIntegration /></PrivateRoute>} />
              <Route path="component-types" element={<PrivateRoute requiredRole="Admin"><ComponentTypesPage /></PrivateRoute>} />
              <Route path="releases/templates" element={<PrivateRoute requiredRole="Admin"><ReleaseTemplateLibrary /></PrivateRoute>} />
              <Route path="releases/templates/:id" element={<PrivateRoute requiredRole="Admin"><ReleaseTemplateForm /></PrivateRoute>} />
              <Route path="releases/scope-change-rules" element={<PrivateRoute requiredRole="Admin"><TenantScopeChangeRules /></PrivateRoute>} />
              <Route path="releases/raid" element={<PrivateRoute requiredRole="Admin"><RaidSettings /></PrivateRoute>} />
              <Route path="tenants" element={<PrivateRoute requireMasterAdmin><TenantList /></PrivateRoute>} />
              <Route path="tenants/:tenantId" element={<PrivateRoute requireMasterAdmin><TenantDetail /></PrivateRoute>} />
              {/* react-router v7 ranks routes by segment specificity, not
                  declaration order, so a static segment (e.g. "tenants")
                  always outranks a dynamic ":entity" at the same position
                  regardless of where either is listed — these two catch-alls
                  are simply the only routes that CAN match here. */}
              <Route path=":entity/:tab" element={<PrivateRoute requiredRole="Admin"><EntityTabRedirect /></PrivateRoute>} />
              <Route path=":entity" element={<PrivateRoute requiredRole="Admin"><EntityConfig /></PrivateRoute>} />
            </Route>

            {/* One release of bookmark compatibility. */}
            {LEGACY_REDIRECTS.map((r) => (
              <Route key={r.from} path={r.from} element={<LegacyRedirectRoute to={r.to} />} />
            ))}
          </Route>
          <Route path="/" element={<Navigate to={isAuthenticated ? '/dashboard' : '/login'} />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
