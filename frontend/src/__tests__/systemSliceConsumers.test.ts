import { describe, expect, it } from 'vitest';

// `glob` is only a transitive dependency here (pulled in by tooling, not
// declared directly), so this doesn't add it as a real dependency just for a
// test. `fs`/`path` would need `@types/node`, which this project also
// doesn't have — so, like appCodeSplitting.test.tsx's `?raw` import, this
// leans on Vite's own `import.meta.glob` to both enumerate and read every
// source file, no Node builtins involved.
const files = import.meta.glob<string>('../**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
});

const EXCLUDED_PATHS = new Set([
  '../pages/systems/SystemCatalog.tsx',
  '../store/systemSlice.ts',
  '../hooks/useAllSystems.ts',
]);

// Reads the array of every system — the picker case this task exists to fix
// — either as a direct chained property access (`s.system.systems`) or
// destructured out of the whole slice object (`const { systems } =
// useSelector(... => state.system)`), mirroring
// infrastructureComponentSliceConsumers.test.ts's two shapes.
// No selector-parameter prefix on the first pattern. Requiring the param to
// be named `s` or `state` would let `(sys: RootState) =>
// sys.system.systems` through, and costs nothing to drop: `.system.systems`
// is specific enough on its own.
// `\s*` between tokens crosses newlines: SystemDetail.tsx destructures this
// slice across three lines (`useSelector(\n  (state: RootState) =>
// state.system\n)`), so a pattern that only tolerated single-line spacing
// would find nothing there and this test would pass while guarding nothing.
const READS_SYSTEMS_LIST = [
  /\.system\.systems\b/,
  /\{[^}]*\bsystems\b[^}]*\}\s*=\s*useSelector\(\s*\([^)]*\)\s*=>\s*[A-Za-z_$][\w$]*\.system\s*\)/,
];

describe('system slice consumers', () => {
  it('no component outside SystemCatalog reads or dispatches the system list, or calls listSystems directly', () => {
    // This is the precondition for converting SystemCatalog (a later task).
    // A single straggler reintroduces the whole class of bug this programme
    // exists to remove: a picker limited to the grid's current page, or a
    // bare dispatch clobbering it back to page 1. Unlike the infrastructure
    // component / environment sweeps, this slice also has direct
    // `systemService.listSystems()` callers that never touch Redux at all —
    // a reader/dispatcher grep alone would find none of them.
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(files)) {
      // Test files (this one included) live under __tests__ directories
      // only — there is no *.test.ts(x) outside one anywhere in src/.
      if (path.includes('/__tests__/')) continue;
      if (EXCLUDED_PATHS.has(path)) continue;

      const rel = path.replace(/^\.\.\//, '');
      if (/\bfetchSystems\s*\(/.test(src)) {
        offenders.push(`${rel}: dispatches fetchSystems`);
      }
      if (READS_SYSTEMS_LIST.some((re) => re.test(src))) {
        offenders.push(`${rel}: reads the system list`);
      }
      if (/systemService\.listSystems\(/.test(src)) {
        offenders.push(`${rel}: calls systemService.listSystems directly`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('found source files to scan', () => {
    // A regression here (an empty glob result) would make the test above
    // pass vacuously — this pins the sweep to real coverage.
    expect(Object.keys(files).length).toBeGreaterThan(100);
  });
});
