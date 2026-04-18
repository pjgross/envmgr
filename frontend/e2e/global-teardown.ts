import { unlinkSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default async function globalTeardown() {
  const dbPath = path.resolve(__dirname, '../../backend/e2e_test.db');
  if (existsSync(dbPath)) {
    unlinkSync(dbPath);
    console.log('\nE2E test database removed.');
  }
}
