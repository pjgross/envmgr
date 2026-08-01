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
  '../pages/infrastructure/InfrastructureComponentList.tsx',
  '../store/infrastructureComponentSlice.ts',
  '../hooks/useAllHosts.ts',
]);

// Reads the array of every infrastructure component ("host") — the picker
// case this task exists to fix — either as a direct chained property access
// (`s.infrastructureComponent.components`) or destructured out of the whole
// slice object (`const { components } = useSelector(... => state
// .infrastructureComponent)`), mirroring environmentSliceConsumers.test.ts's
// two shapes.
// No selector-parameter prefix on the first pattern. Requiring the param to
// be named `s` or `state` would let `(ic: RootState) =>
// ic.infrastructureComponent.components` through, and costs nothing to drop:
// `.infrastructureComponent.components` is specific enough on its own.
const READS_COMPONENTS_LIST = [
  /\.infrastructureComponent\.components\b/,
  /\{[^}]*\bcomponents\b[^}]*\}\s*=\s*useSelector\(\s*\([^)]*\)\s*=>\s*[A-Za-z_$][\w$]*\.infrastructureComponent\s*\)/,
];

describe('infrastructure component slice consumers', () => {
  it('no component outside InfrastructureComponentList reads or dispatches the component list', () => {
    // This is the precondition for converting InfrastructureComponentList (a
    // later task). A single straggler reintroduces the whole class of bug
    // this programme exists to remove: a picker limited to the grid's
    // current page, or a bare dispatch clobbering it back to page 1.
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(files)) {
      // Test files (this one included) live under __tests__ directories
      // only — there is no *.test.ts(x) outside one anywhere in src/.
      if (path.includes('/__tests__/')) continue;
      if (EXCLUDED_PATHS.has(path)) continue;

      const rel = path.replace(/^\.\.\//, '');
      if (/\bfetchInfrastructureComponents\s*\(/.test(src)) {
        offenders.push(`${rel}: dispatches fetchInfrastructureComponents`);
      }
      if (READS_COMPONENTS_LIST.some((re) => re.test(src))) {
        offenders.push(`${rel}: reads the component list`);
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
