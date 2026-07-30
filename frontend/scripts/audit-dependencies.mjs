#!/usr/bin/env node
// Fail if `npm audit` reports an advisory we have not explicitly accepted.
//
//   node scripts/audit-dependencies.mjs
//
// `npm audit` has no per-advisory ignore, and --audit-level is too blunt: it
// would hide unrelated highs alongside the one we've reasoned about. Accepted
// advisories are listed below with a reachability argument. "No clean version
// exists" is not on its own a reason — it needs to be unreachable in this app.

import { execFileSync } from 'node:child_process';

/** advisory URL fragment (GHSA id) -> why we ship with it */
const ACCEPTED = {
  'GHSA-qwww-vcr4-c8h2':
    'react-router RSC-mode CSRF bypass. Affects 7.12.0-8.2.0, and every version at ' +
    'or below 7.17.0 carries the reachable open-redirect (GHSA-wrjc-x8rr-h8h6), so ' +
    'there is no clean release: downgrading to npm audit\'s suggested 7.11.0 would ' +
    'trade an unreachable issue for a reachable one. Unreachable here — this is a ' +
    'client-only SPA (BrowserRouter, no React Server Components, no SSR). Revisit ' +
    'when a version above 8.2.0 ships.',
};

const raw = (() => {
  try {
    return execFileSync('npm', ['audit', '--json', '--omit=dev'], { encoding: 'utf8' });
  } catch (err) {
    // npm exits non-zero when it finds anything; the report is still on stdout.
    if (err.stdout) return err.stdout;
    throw err;
  }
})();

const report = JSON.parse(raw);
const unaccepted = [];
const acceptedSeen = new Set();

for (const [name, vuln] of Object.entries(report.vulnerabilities ?? {})) {
  for (const via of vuln.via ?? []) {
    if (typeof via !== 'object' || !via.url) continue; // string entries are indirections
    const ghsa = via.url.split('/').pop();
    if (ghsa in ACCEPTED) acceptedSeen.add(ghsa);
    else unaccepted.push(`${name} (${vuln.severity}): ${via.title} — ${via.url}`);
  }
}

for (const ghsa of [...acceptedSeen].sort()) {
  console.log(`accepted: ${ghsa} — ${ACCEPTED[ghsa].split('.')[0]}.`);
}

if (unaccepted.length > 0) {
  console.error(`\n${unaccepted.length} unaccepted advisories:`);
  for (const line of [...new Set(unaccepted)].sort()) console.error(`  ${line}`);
  console.error(
    '\nUpgrade the package, or add the advisory to ACCEPTED in this script with a ' +
      'reachability argument.'
  );
  process.exit(1);
}

const total = report.metadata?.dependencies?.total ?? '?';
console.log(`\nno unaccepted advisories across ${total} production dependencies`);
