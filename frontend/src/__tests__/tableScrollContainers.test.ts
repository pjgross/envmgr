import { describe, expect, it } from 'vitest';

// `import.meta.glob` enumerates AND reads every source file, with no Node
// builtins — this package has no `@types/node`, so `fs`/`path` would fail
// `tsc --noEmit`. Same technique as storageKeys.test.ts.
const files = import.meta.glob<string>('../**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
});

/**
 * PR 5's remaining debt, emptied task by task. Every entry is a file whose
 * `<Table>` has no `<TableContainer>` yet. Delete an entry in the same commit
 * that wraps its table — the second test below fails if you forget, and fails
 * again if you delete an entry without doing the work.
 */
const UNWRAPPED = new Set<string>([
  '../components/admin/LifecycleTemplatesPanel.tsx',
  '../components/systems/RehearsalsPanel.tsx',
  '../pages/environment-groups/EnvironmentGroupDetail.tsx',
  '../pages/projects/ProjectDetail.tsx',
  '../pages/admin/UserGroupDetail.tsx',
  '../pages/admin/TenantDetail.tsx',
]);

/**
 * A bare MUI `<Table>` has no scroll container. It renders
 * `<table style="width: 100%">`, which still grows past its parent when the
 * content's *minimum* width does — a column per environment, or a single
 * unbreakable token like an email address. Nothing scrolls it, so the
 * DOCUMENT scrolls; and because the drawer and app bar are `position: fixed`,
 * the content slides underneath them and the leftmost column — the row's
 * identity — is hidden behind the 240px drawer. `<TableContainer>` is
 * `width: 100%; overflow-x: auto` (TableContainer.js:29), which confines the
 * scroll to the table.
 *
 * jsdom performs no layout, so no rendered test can measure this. It is
 * asserted on the source, the same call storageKeys.test.ts makes.
 */
describe('every raw <Table> has a scroll container', () => {
  const isProductionFile = (path: string) =>
    !path.includes('__tests__') && !path.includes('/test/');

  // `<Table[\s>]` cannot match `<TableContainer`, `<TableHead`, `<TableRow`
  // or `<TableCell` — the character after "Table" must be whitespace or `>`.
  const TABLE = /<Table[\s>]/g;
  const CONTAINER = /<TableContainer[\s>]/g;

  const count = (source: string, re: RegExp) => [...source.matchAll(re)].length;

  it('no production file renders more <Table> elements than <TableContainer>', () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      if (!isProductionFile(path)) continue;
      if (UNWRAPPED.has(path)) continue;
      const tables = count(source, TABLE);
      if (tables === 0) continue;
      const containers = count(source, CONTAINER);
      if (containers < tables) offenders.push(`${path} (${tables} tables, ${containers} containers)`);
    }
    expect(offenders, `a <Table> with no <TableContainer>: ${offenders.join(', ')}`).toEqual([]);
  });

  it('every allowlisted file still exists and still needs wrapping', () => {
    // A stale allowlist entry is worse than none: it silently exempts a file
    // that was fixed, or names one that no longer exists, and the guard reads
    // as passing either way.
    const stale: string[] = [];
    for (const path of UNWRAPPED) {
      const source = files[path];
      if (source === undefined) {
        stale.push(`${path} (no such file)`);
        continue;
      }
      if (count(source, CONTAINER) >= count(source, TABLE)) {
        stale.push(`${path} (already wrapped — delete this entry)`);
      }
    }
    expect(stale, `stale allowlist entries: ${stale.join(', ')}`).toEqual([]);
  });
});
