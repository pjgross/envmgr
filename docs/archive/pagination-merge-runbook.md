# Pagination programme — merge runbook (executed 2026-07-31)

**Done.** All three PRs are merged to `main` and their branches are deleted. Kept for one
reason: the procedure below was wrong about how GitHub handles stacked PRs, and it cost a
recovery step. If you ever stack PRs in this repo again, read "The trap" first.

| PR | Head | Merge commit |
|---|---|---|
| #36 | `feature/pagination-sweep` | `305c222` |
| #37 | `feature/pagination-sweep-b` | `cbd2974` |
| #38 | `feature/pagination-sweep-c1` | `22b6a9b` |

Final `main` tip `22b6a9b`, CI green on all four jobs (SQLite, PostgreSQL, frontend, images).
`main`'s tree was verified byte-identical to `feature/pagination-sweep-c1` after the last merge
(`git diff github/main feature/pagination-sweep-c1` — empty).

## The trap

The original runbook asserted that "GitHub retargets #37's base to `main` automatically" after
#36 merges. **It does not — not when you merge with `--delete-branch`.** Deleting the base
branch of an open PR *closes* that PR:

```
gh pr merge 36 --merge --delete-branch    # ← this closed #37
```

Recovery is awkward, because the two obvious repairs each block the other:

- `gh pr edit 37 --base main` → `Cannot change the base branch of a closed pull request`
- `gh pr reopen 37` → `Could not open the pull request` (its base branch no longer exists)

The way out is to **push the deleted branch back**, which makes the PR reopenable:

```bash
git push github refs/heads/feature/pagination-sweep:refs/heads/feature/pagination-sweep
gh pr reopen 37
gh pr edit 37 --base main
```

Note the order — reopen first, *then* retarget.

## What to do instead

Merge without `--delete-branch`, retarget the next PR by hand, and delete every branch at the
end once nothing is stacked on it:

```bash
gh pr merge 36 --merge            # no --delete-branch
gh pr edit 37 --base main         # explicit, not hoped-for
gh pr merge 37 --merge
gh pr edit 38 --base main
gh pr merge 38 --merge
git push github --delete feature/pagination-sweep feature/pagination-sweep-b feature/pagination-sweep-c1
```

Retargeting a PR triggers a fresh CI run. That re-run is redundant when the head SHA hasn't
moved and the new base's tree already equals the old base's tree — which is exactly the case in
a linear stack merged in order. #37 was merged on the strength of its original green run against
the same SHA rather than waiting ~25 minutes for an identical answer.

The original advice to use `--merge` over `--squash` **was** correct and still stands: squashing
a base branch rewrites the commits the next PR is stacked on.

## Still outstanding (unchanged by the merge)

**Sub-project C3 — the frontend half — is not written**, and it is the one that fixes the
user-visible bug: every list page still fetches a capped page and filters it *in the browser*.
Read the "What sub-project C3 must honour" section of [`../pagination.md`](../pagination.md)
first. The smaller deferred items (`/releases/calendar` and `/releases/timeline`'s hardcoded
`limit=500`, `dependency-alerts` staying unbounded, the membership `current`/`history`
duplication, and joined-name sorting) are recorded there and in the CLAUDE.md banner.
