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
  // `import.meta.glob('../**/*.{ts,tsx}', ...)` keys files relative to THIS
  // file's own directory (src/__tests__/). A co-located test next to the
  // component it covers (e.g. `src/pages/foo/__tests__/foo.test.tsx`) keys
  // as `../pages/foo/__tests__/foo.test.tsx` — it DOES carry a `__tests__`
  // segment. But a SIBLING of this file, in the same `src/__tests__/`
  // directory, keys with NO directory segment at all: `./storageKeys.test.ts`
  // (verified directly against the glob's own output), not
  // `../__tests__/storageKeys.test.ts` as the relative-path intuition
  // suggests. Neither the `__tests__` nor the `/test/` substring check can
  // ever match that key, so every file in this directory is swept as
  // production code today — latent only because none renders a `<Table>`.
  // The explicit `.test.ts(x)` suffix check covers it directly, independent
  // of which directory the file happens to sit in.
  const isProductionFile = (path: string) =>
    !path.includes('__tests__') && !path.includes('/test/') && !/\.test\.tsx?$/.test(path);

  // Tokenise `<Table` / `<TableContainer` OPEN tags AND `</TableContainer>`
  // CLOSE tags, in the order they appear in the source, and never any prop
  // text in between. A naive `<TableContainer[^>]*>\s*<Table` regex gives a
  // false positive on `ImportPage.tsx`, whose props contain a bare `>`
  // inside a JSX expression (`sx={{ mb: x.length > 0 ? 2 : 0 }}`) — the
  // `[^>]*` stops at that `>` and never reaches the real `<Table` that
  // follows. Tokenising tag names and checking ADJACENCY IN THE TOKEN
  // SEQUENCE sidesteps this entirely: it never looks at prop text, so it
  // cannot be fooled by a `>` living inside one.
  //
  // The CLOSE tag must be tracked, not discarded: a `<Table>` counts as
  // covered only when the immediately preceding token is a TableContainer
  // OPEN — never a TableContainer CLOSE. Without tracking closes,
  // `<TableContainer><div /></TableContainer>` followed by a sibling, bare
  // `<Table>` tokenises as `[open, Table]` and reads as "adjacent" even
  // though the container already closed before the table appeared — exactly
  // the counting defect this test replaces, wearing a new disguise. Tracking
  // the close makes that sequence `[open, close, Table]`, whose token
  // immediately before `Table` is `close`, not `open` — correctly rejected.
  //
  // `<Table[\s>]` cannot match `<TableContainer`, `<TableHead`, `<TableRow`
  // or `<TableCell` — the character after "Table" must be whitespace or `>`.
  const TOKEN = /<(TableContainer|Table)[\s>]|<\/(TableContainer)>/g;

  type Token = 'containerOpen' | 'containerClose' | 'table';

  const tokenSequence = (source: string): Token[] =>
    [...source.matchAll(TOKEN)].map((m) =>
      m[2] === 'TableContainer' ? 'containerClose' : m[1] === 'TableContainer' ? 'containerOpen' : 'table',
    );

  it('every <Table> open tag is immediately preceded by a <TableContainer> open tag', () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      if (!isProductionFile(path)) continue;
      const sequence = tokenSequence(source);
      sequence.forEach((tok, i) => {
        if (tok === 'table' && sequence[i - 1] !== 'containerOpen') {
          offenders.push(path);
        }
      });
    }
    expect(offenders, `a <Table> not immediately preceded by <TableContainer>: ${offenders.join(', ')}`).toEqual([]);
  });

  // Every table this PR wrapped already sits on a surface (a `Paper`, a
  // dialog, a panel `Box`) — see the plan's "Already inside" column. A
  // `TableContainer` also rendering `component={Paper}` would be a SECOND
  // surface stacked on the first: a visible doubled border/background,
  // worst in dark mode. The plan's Global Constraints, CLAUDE.md and
  // docs/ui-audit.md all state the prohibition; none of them tested it.
  //
  // Scoped to the 16 files this PR wrapped (not every `TableContainer` in
  // the app — `SystemDetail.tsx`, `CustomFieldDefinitionManager.tsx` and
  // `TenantScopeChangeRules.tsx` use `component={Paper}` deliberately,
  // predate this PR, and are not this sweep's business).
  const PR5_WRAPPED_FILES = [
    '../components/admin/LifecycleTemplatesPanel.tsx',
    '../components/bookings/EnvironmentsPanel.tsx',
    '../components/bookings/GroupTransitionPanel.tsx',
    '../components/environments/ComparisonTable.tsx',
    '../components/environments/EnvironmentProjectsPanel.tsx',
    '../components/releases/ReleaseEnvironmentCoverage.tsx',
    '../components/releases/ReleaseSystemsTab.tsx',
    '../components/releases/RollbackPanel.tsx',
    '../components/releases/ScopeImportDialog.tsx',
    '../components/releases/pir/PirActionsTable.tsx',
    '../components/systems/RehearsalsPanel.tsx',
    '../pages/admin/TenantDetail.tsx',
    '../pages/admin/UserGroupDetail.tsx',
    '../pages/admin/UserManagement.tsx',
    '../pages/environment-groups/EnvironmentGroupDetail.tsx',
    '../pages/projects/ProjectDetail.tsx',
  ];

  // Extracts each `<TableContainer ...>` OPENING TAG in full, tracking
  // brace depth and string-quote state so a `>` inside a prop expression
  // (the same `ImportPage.tsx` shape above) never mistaken for the tag's
  // own closing bracket.
  const extractOpeningTags = (source: string, tagName: string): string[] => {
    const tags: string[] = [];
    const start = new RegExp(`<${tagName}(?=[\\s>])`, 'g');
    let match: RegExpExecArray | null;
    while ((match = start.exec(source))) {
      let i = match.index;
      let depth = 0;
      let quote: string | null = null;
      for (; i < source.length; i++) {
        const ch = source[i];
        if (quote) {
          if (ch === quote && source[i - 1] !== '\\') quote = null;
        } else if (ch === '"' || ch === "'" || ch === '`') {
          quote = ch;
        } else if (ch === '{') {
          depth++;
        } else if (ch === '}') {
          depth--;
        } else if (ch === '>' && depth === 0) {
          break;
        }
      }
      tags.push(source.slice(match.index, i + 1));
    }
    return tags;
  };

  const COMPONENT_PAPER = /component=\{\s*Paper\s*\}/;

  it('no TableContainer this PR wrapped renders a second Paper surface', () => {
    const offenders: string[] = [];
    for (const path of PR5_WRAPPED_FILES) {
      const source = files[path];
      if (source === undefined) {
        offenders.push(`${path} (not found by import.meta.glob — path drifted?)`);
        continue;
      }
      for (const tag of extractOpeningTags(source, 'TableContainer')) {
        if (COMPONENT_PAPER.test(tag)) offenders.push(`${path}: ${tag}`);
      }
    }
    expect(offenders, `a TableContainer with component={Paper}: ${offenders.join(', ')}`).toEqual([]);
  });
});
