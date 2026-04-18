import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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
import ImportPage from './pages/import/ImportPage';
import AdminLayout from './pages/admin/AdminLayout';
import EntityConfig from './pages/admin/EntityConfig';
import ImpersonationBanner from './components/ImpersonationBanner';
import AppLayout from './components/AppLayout';
import NotFound from './components/NotFound';

function PrivateRoute({
  children,
  requireMasterAdmin = false,
  requiredRole,
}: {
  children: React.ReactNode;
  requireMasterAdmin?: boolean;
  requiredRole?: string;
}) {
  const { user, isAuthenticated } = useSelector((state: RootState) => state.auth);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (requireMasterAdmin && !user?.is_master_admin) return <Navigate to="/dashboard" replace />;
  if (requiredRole && user?.role !== requiredRole && !user?.is_master_admin)
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
        </Route>
        <Route path="/" element={<Navigate to={isAuthenticated ? '/dashboard' : '/login'} />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
