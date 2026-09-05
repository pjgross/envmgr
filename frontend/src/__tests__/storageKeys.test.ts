import { describe, expect, it } from 'vitest';

// `import.meta.glob` enumerates AND reads every source file, with no Node
// builtins — this package has no `@types/node`, so `fs`/`path` would fail
// `tsc --noEmit`. Same technique as systemSliceConsumers.test.ts.
const files = import.meta.glob<string>('../**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
});

/**
 * A DataTable's `storageKey` names one localStorage entry. Two grids sharing
 * one share their column-visibility model, so hiding a column on one silently
 * hides whatever column happens to sit at that index on the other. No rendered
 * test can see this — it needs two pages mounted at once — so it is asserted
 * on the source.
 */
describe('every storageKey is unique', () => {
  // Test files legitimately reuse throwaway keys against a cleared
  // localStorage, and the wrapper's own default lives in DataTable.tsx.
  const isProductionFile = (path: string) =>
    !path.includes('__tests__') && !path.includes('/test/') && !path.endsWith('DataTable.tsx');

  it('no two production grids declare the same storageKey literal', () => {
    const seen = new Map<string, string[]>();
    for (const [path, source] of Object.entries(files)) {
      if (!isProductionFile(path)) continue;
      for (const match of source.matchAll(/storageKey="([^"]+)"/g)) {
        const key = match[1];
        seen.set(key, [...(seen.get(key) ?? []), path]);
      }
    }
    const duplicates = [...seen.entries()].filter(([, paths]) => paths.length > 1);
    expect(duplicates, `storageKey reused: ${JSON.stringify(duplicates)}`).toEqual([]);
  });

  it('every computed storageKey is allowlisted', () => {
    // A template-literal key can't be compared for uniqueness by reading the
    // source, so each one is named here deliberately. RaidTab's key is
    // `release-raid-${typeTab}`, one entry per RAID type tab, which is the
    // point — the tabs are different grids.
    const ALLOWED_COMPUTED = new Set(['../components/releases/raid/RaidTab.tsx']);
    const computed: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      if (!isProductionFile(path)) continue;
      if (/storageKey=\{/.test(source) && !ALLOWED_COMPUTED.has(path)) computed.push(path);
    }
    expect(computed, 'a computed storageKey escapes the uniqueness check').toEqual([]);
  });
});

/**
 * These three `storageKey` literals are not merely unique (the describe
 * block above already guards that) — they are FROZEN. Before Task 7,
 * BookingList/EnvironmentList/SystemCatalog each kept their own
 * loadColumnModel/saveColumnModel pair writing directly to
 * `<name>-columns-${userId ?? 'guest'}`. DataTable composes its own key as
 * `${storageKey}-${userId}`, so each page now passes the historical name as
 * `storageKey` and `user?.id ?? 'guest'` as `userId` specifically so the
 * composed key lands on the exact entry a real user's column layout is
 * already stored under. Renaming any literal below, or dropping its
 * `userId={user?.id ?? 'guest'}` companion, changes nothing anyone would see
 * on screen — it just silently starts every user back at the default column
 * set, with their old preference still sitting under a key nothing reads any
 * more. This is the source-level half of that guard: it cannot see how
 * DataTable itself turns the two props into a key (a rendered test for that,
 * against a real DataGrid, lives in
 * `src/components/__tests__/dataTableServerMode.test.tsx`).
 */
describe('the three migrated hand-rolled-persistence pages keep their historical key', () => {
  const HISTORICAL_KEYS: Record<string, string> = {
    '../pages/bookings/BookingList.tsx': 'bookings-list-columns',
    '../pages/environments/EnvironmentList.tsx': 'environments-list-columns',
    '../pages/systems/SystemCatalog.tsx': 'systems-list-columns',
  };

  it.each(Object.entries(HISTORICAL_KEYS))(
    '%s declares its historical storageKey and the guest-fallback userId',
    (path, key) => {
      const source = files[path];
      expect(source, `expected to find ${path} in the glob`).toBeDefined();
      expect(source).toContain(`storageKey="${key}"`);
      expect(source).toContain("userId={user?.id ?? 'guest'}");
    }
  );
});
