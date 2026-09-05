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
