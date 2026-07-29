import { defineConfig, configDefaults } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
    // e2e/ holds Playwright specs. Vitest's default include matches *.spec.ts,
    // so without this it tries to collect them and fails — Playwright's
    // fixtures-based `test(...)` is not a vitest API. Run them with
    // `npm run test:e2e`.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
});
