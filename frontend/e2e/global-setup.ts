import { execFileSync } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '../..');
const BACKEND_DIR = path.join(PROJECT_ROOT, 'backend');
const SITE_PACKAGES = path.join(PROJECT_ROOT, '.venv/lib/python3.12/site-packages');
const PYTHON =
  process.env.PYTHON_BIN ||
  path.join(
    process.env.HOME!,
    '.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12'
  );

export default async function globalSetup() {
  console.log('\nSeeding E2E test database...');
  execFileSync(PYTHON, ['scripts/seed_e2e.py'], {
    cwd: BACKEND_DIR,
    env: {
      ...process.env,
      PYTHONPATH: `${SITE_PACKAGES}:.`,
      DATABASE_URL: 'sqlite+aiosqlite:///./e2e_test.db',
    },
    stdio: 'inherit',
  });
}
