# Archive

Documents kept for the record, not for reference. Nothing here describes how EnvManager
works today — some of it actively contradicts the current system. Read
[`../prod architecture.md`](../prod%20architecture.md), [`../requirements.md`](../requirements.md)
and [`../../CLAUDE.md`](../../CLAUDE.md) for current state.

They are kept rather than deleted because they record *why* things are the way they are,
which git history alone conveys poorly.

| Document | What it was | Superseded by |
|---|---|---|
| [`GEMINI.md`](GEMINI.md) | The original Gemini-era agent guide — conventions, architecture notes and workflow for the first phases | [`../../CLAUDE.md`](../../CLAUDE.md) |
| [`EnvManager_Development_Prompt.md`](EnvManager_Development_Prompt.md) | The original system specification the project was built from | [`../requirements.md`](../requirements.md), [`../prod architecture.md`](../prod%20architecture.md) |
| [`EnvManager_Requirements_Summary.md`](EnvManager_Requirements_Summary.md) | The first requirements summary | [`../requirements.md`](../requirements.md) |
| [`phase-3-sub1-smoke-checklist.md`](phase-3-sub1-smoke-checklist.md) | Manual QA walkthrough before merging `feature/phase-3-core-releases` (April 2026) | The automated suite — `backend/tests/integration/test_release_happy_path.py` and the rest |
| [`phase-3-sub2-smoke-checklist.md`](phase-3-sub2-smoke-checklist.md) | Manual QA walkthrough before merging Enterprise Releases (April 2026) | As above |
| [`pagination-merge-runbook.md`](pagination-merge-runbook.md) | Merge order for the three stacked pagination PRs (#36–#38), executed 2026-07-31 | Nothing — the merge is done. Kept because its central claim (that GitHub auto-retargets a stacked PR's base) is **false**, and the annotated copy records the recovery |

## Known contradictions

The two original specification documents describe **Neo4j as the graph store for
infrastructure topology**. It was provisioned but never used, and was removed on
2026-07-30 — topology is PostgreSQL-backed. See
[`../decisions/2026-07-30-drop-neo4j.md`](../decisions/2026-07-30-drop-neo4j.md).

They also predate: the removal of self-service registration, refresh-token sessions,
GitHub Actions CI, the Dockerfiles, and the dual-engine test suite.

## Not archived

Kept in `docs/` because they are still live:

- **`docs/phases/phase-*.md`** — per-phase summaries, linked from each row of the roadmap.
- **`docs/superpowers/`** — per-feature plans and design specs. Already segregated and
  dated; they are the design record for individual features.
- **`docs/frontend-modernisation-plan.md`** — Tier 1 landed, tiers 2–4 are still open work.
- **The three `.docx` files** — source material cited by [`../gap-analysis.md`](../gap-analysis.md)
  and [`../requirements.md`](../requirements.md).
