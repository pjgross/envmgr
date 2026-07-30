import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../store';
import App from '../App';
// ?raw is a Vite import; typed via vite/client, so this needs no @types/node.
import appSource from '../App.tsx?raw';

// No HTTP from the auth bootstrap effect.
vi.mock('../services/authService', () => ({
  authService: {
    getCurrentUser: vi.fn().mockRejectedValue(new Error('unauthenticated')),
    login: vi.fn(),
  },
}));

describe('App with code-split routes', () => {
  it('renders the shell without waiting on a lazy chunk', async () => {
    // Login stays eagerly imported precisely so the first paint needs no chunk
    // fetch. If it were lazified, this would show the Suspense fallback instead
    // and the login form would never appear synchronously.
    render(
      <Provider store={store}>
        <App />
      </Provider>
    );

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
  });

  it('every lazily-imported route module resolves and has a default export', async () => {
    // lazy() requires a default export and a valid path, but a mistake in either
    // only surfaces when someone navigates to that route. Read the lazy() calls
    // out of App.tsx and load exactly those — not everything under pages/, which
    // also holds named-export sub-components that legitimately have no default.
    const source = appSource;
    const lazyPaths = [...source.matchAll(/lazy\(\(\) => import\('(\.\/pages\/[^']+)'\)\)/g)].map(
      (m) => m[1]
    );

    const modules = import.meta.glob('../pages/**/*.tsx');
    const resolve = (routePath: string) => modules[routePath.replace('./pages/', '../pages/') + '.tsx'];

    expect(lazyPaths.length).toBeGreaterThan(30);
    const problems: string[] = [];
    for (const routePath of lazyPaths) {
      const load = resolve(routePath);
      if (!load) {
        problems.push(`${routePath}: no module at that path`);
        continue;
      }
      const mod = (await load()) as { default?: unknown };
      if (mod.default === undefined) problems.push(`${routePath}: no default export`);
    }
    expect(problems).toEqual([]);
  });
});
