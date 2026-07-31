# Pagination programme — merge runbook

Three stacked PRs, none merged as of 2026-07-31. This is the order and the traps.

| PR | Head | Base | CI |
|---|---|---|---|
| #36 | `feature/pagination-sweep` | `main` | green |
| #37 | `feature/pagination-sweep-b` | `feature/pagination-sweep` | green |
| #38 | `feature/pagination-sweep-c1` | `feature/pagination-sweep-b` | check before merging |

## Before you start

- **No migrations.** `git diff --name-only main..feature/pagination-sweep-c1 -- backend/app/db/migrations/`
  is empty across the whole stack. Nothing to run at deploy, no backfill, no downtime step.
- **No frontend change is required by any of the three.** Endpoints still return bare JSON arrays;
  totals are header-only; sorting and the new filters are optional parameters. That is deliberate —
  it is what makes the stack safe to merge ahead of the frontend work (C3).
- 71 files, ~10.2k insertions across the three.

## Merge each in order, never out of it

Each PR is based on the one before, so #37's diff only makes sense once #36 is in.

```bash
gh pr merge 36 --repo pjgross/envmgr --merge --delete-branch
```

**Use `--merge`, not `--squash`.** This repo's history uses merge commits
(`Merge feat/list-pagination: bounded list results`), and squashing a base branch rewrites the
commits the next PR is stacked on — GitHub will then show #37 as containing #36's changes again,
or refuse to merge cleanly.

After #36 merges, **GitHub retargets #37's base to `main` automatically**. Verify before merging:

```bash
gh pr view 37 --repo pjgross/envmgr --json baseRefName,mergeable,mergeStateStatus
```

Expect `baseRefName: main`, `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN`. If the state is
`BEHIND`, update the branch (`gh pr update-branch 37 --repo pjgross/envmgr`) and let CI re-run —
do not merge a stale branch, because the dual-engine suite is the only thing standing between this
work and a silent ordering regression.

Then repeat for #37, then #38.

## After all three land

```bash
git checkout main && git pull
cd backend && uv run pytest -q
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
```

Expect **1056 passed / 10 skipped** on SQLite and **1065 / 1** on PostgreSQL. The nine-test
difference is the PostgreSQL-only tie-paging walks, which skip on SQLite by design — that gap is
correct, not a failure.

## What is still outstanding after the merge

**Sub-project C3 — the frontend half — is not written**, and it is the one that fixes the
user-visible bug. Every list page still fetches a capped page and filters it *in the browser*:
`ReleaseList` sends no filters at all, receives the newest 50 releases, and filters those 50 by
status/type/kind/system in JavaScript. A tenant with more than 50 releases gets answers computed
from a truncated set, silently. Eleven other pages are the same shape.

Everything C3 needs is in place and documented. **Read the "What sub-project C3 must honour"
section of [docs/pagination.md](pagination.md) first** — sort whitelists per endpoint, the twelve
columns that can never be sorted server-side, the endpoint-wide `default_dir` hazard, and the two
enum-storage conventions.

Smaller items recorded and deliberately not done:

- `/releases/calendar` and `/releases/timeline` still filter `target_date` in Python after a
  hardcoded `limit=500`.
- `releases/{id}/dependency-alerts` stays unbounded on purpose — its `diff_days == 0` filter has no
  portable SQL form, so a page would window the pre-filter set.
- An accepted membership appears in both `current` and `history` in the membership view.
- Sorting by joined names (`environment_name`, `system_name`, …) is not supported; each needs its
  join shape checked individually.
