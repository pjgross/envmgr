import { defineConfig, devices } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Paths resolved relative to this config file (frontend/)
const PROJECT_ROOT = path.resolve(__dirname, '..')
const BACKEND_DIR = path.join(PROJECT_ROOT, 'backend')
const SITE_PACKAGES = path.join(PROJECT_ROOT, '.venv/lib/python3.12/site-packages')

// uv-managed Python — the real binary (not the XSym shim in .venv/bin)
const PYTHON =
  process.env.PYTHON_BIN ||
  path.join(
    process.env.HOME!,
    '.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12'
  )

// E2E backend runs on a dedicated port so it can coexist with the dev backend
const E2E_BACKEND_PORT = '8002'
const E2E_DATABASE_URL = 'sqlite+aiosqlite:///./e2e_test.db'

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  // Fail fast on CI; allow retries locally
  retries: process.env.CI ? 2 : 0,

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  webServer: [
    {
      // Backend with SQLite test DB on port 8002 (safe to run alongside dev backend on 8000)
      command: [
        `PYTHONPATH=${SITE_PACKAGES}:.`,
        `DATABASE_URL=${E2E_DATABASE_URL}`,
        PYTHON,
        `-m uvicorn app.main:app --port ${E2E_BACKEND_PORT} --log-level warning`,
      ].join(' '),
      cwd: BACKEND_DIR,
      url: `http://localhost:${E2E_BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      // Vite dev server — proxies /api to the E2E backend port
      command: `BACKEND_PORT=${E2E_BACKEND_PORT} npm run dev`,
      url: 'http://localhost:5173',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
