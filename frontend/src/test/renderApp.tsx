import { render } from '@testing-library/react';
import { Provider } from 'react-redux';
import { vi } from 'vitest';
import App from '../App';
import { store } from '../store';
import { setCredentials } from '../store/authSlice';

export interface HarnessUser {
  role: string;
  is_master_admin?: boolean;
}

// jsdom implements no matchMedia at all. Without a stub, AppLayout's
// useMediaQuery(up('md')) silently reports `false`, so every render goes
// through the mobile `variant="temporary"` MUI Drawer — which, because
// AppLayout sets `ModalProps={{ keepMounted: true }}`, always mounts a
// Portal + FocusTrap + Slide transition into document.body even while
// closed. Those schedule their own timers, and this harness's callers
// clear the DOM by hand between tests (`document.body.replaceChildren()`,
// not RTL's tracked `cleanup()`) — so a transition timer firing after that
// tries to remove a node that is no longer there, throwing a `NotFoundError`
// that has nothing to do with the page under test. Stubbing `matchMedia` to
// report a desktop viewport renders the permanent drawer instead, which
// uses no Modal/Portal machinery at all.
window.matchMedia =
  window.matchMedia ??
  (vi.fn().mockImplementation((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia);

/**
 * Render the real App (BrowserRouter and all) at `path` as `user`. The
 * singleton store is used deliberately: App's auth bootstrap reads it.
 *
 * Callers must `vi.mock('../services/api')` (and `authService`) so lazy
 * pages that fetch on mount get an empty answer instead of a network call.
 */
export function renderAppAt(path: string, user: HarnessUser) {
  window.history.pushState({}, '', path);
  store.dispatch(
    setCredentials({
      user: {
        id: 1,
        username: 'tester',
        email: 'tester@example.com',
        role: user.role,
        tenant_id: 1,
        is_master_admin: user.is_master_admin ?? false,
      },
      token: 'test-token',
    })
  );
  return render(
    <Provider store={store}>
      <App />
    </Provider>
  );
}
