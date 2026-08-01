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
  '../pages/environments/EnvironmentList.tsx',
  '../store/environmentSlice.ts',
  '../hooks/useAllEnvironments.ts',
]);

// Reads the array of every environment — the picker case this task exists to
// fix — either as a direct chained property access (`s.environment
// .environments`) or destructured out of the whole slice object (`const {
// environments } = useSelector(... => state.environment)`, Dashboard's
// shape). Deliberately narrower than "touches state.environment at all":
// EnvironmentDetail.tsx legitimately destructures other fields of the same
// slice (currentEnvironment, environmentSystemsData, envSubsystems, loading,
// error) for a single environment's detail view, and must keep doing so —
// none of those is the list a picker would silently truncate.
// No selector-parameter prefix on the first pattern. Requiring the param to be
// named `s` or `state` would let `(env: RootState) => env.environment.environments`
// through, and costs nothing to drop: `.environment.environments` still excludes
// EnvironmentDetail's bare `state.environment` destructure and ChangeRequestForm's
// `.environment.envSubsystems`, so widening it adds no false positives.
const READS_ENVIRONMENTS_LIST = [
  /\.environment\.environments\b/,
  /\{[^}]*\benvironments\b[^}]*\}\s*=\s*useSelector\(\s*\([^)]*\)\s*=>\s*[A-Za-z_$][\w$]*\.environment\s*\)/,
];

describe('environment slice consumers', () => {
  it('no component outside EnvironmentList reads or dispatches the environment list', () => {
    // This is the precondition for converting EnvironmentList (a later task).
    // A single straggler reintroduces the whole class of bug this programme
    // exists to remove: a picker limited to the grid's current page, or a
    // bare dispatch clobbering it back to page 1.
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(files)) {
      // Test files (this one included) live under __tests__ directories
      // only — there is no *.test.ts(x) outside one anywhere in src/.
      if (path.includes('/__tests__/')) continue;
      if (EXCLUDED_PATHS.has(path)) continue;

      const rel = path.replace(/^\.\.\//, '');
      if (/\bfetchEnvironments\s*\(/.test(src)) {
        offenders.push(`${rel}: dispatches fetchEnvironments`);
      }
      if (READS_ENVIRONMENTS_LIST.some((re) => re.test(src))) {
        offenders.push(`${rel}: reads the environment list`);
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
