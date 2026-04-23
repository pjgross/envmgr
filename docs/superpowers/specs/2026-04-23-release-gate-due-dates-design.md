# Release Gates: self-contained due dates + timeline diamonds

**Status:** Draft — awaiting user review
**Date:** 2026-04-23
**Phase:** Phase 3 follow-up (post Sub-1/Sub-2 merge)

## Summary

Release gates currently carry an optional `test_phase_id` link and have no
date of their own. Gate criteria each carry their own nullable `due_date`.
This design drops the phase link entirely, gives each gate a required
`due_date`, and makes criteria inherit that date (the per-criterion column
goes away). Gates then render as status-coloured diamonds on the per-release
Gantt timeline alongside the existing orange `target_date` diamond.

## Goals

1. Gates are self-contained milestones on a release, independent of test
   phases.
2. A single `due_date` per gate is the source of truth for when the gate —
   and all its criteria — must be met.
3. Gates appear visually on the release Gantt so stakeholders can see
   milestones at a glance, colour-coded by decision status.

## Non-goals

- Redesigning phases or the Plan tab's PhasesTable/PhaseGanttEditor.
- Rendering gates on the enterprise combined timeline (`TimelineTab.tsx`) —
  that tab is text-based today; diamonds are out of scope.
- Per-criterion overrides of the gate due date (intentionally removed).
- Jira integration (deferred — Phase 3 Sub-3).

## Data-model changes

### `release_gate`

- **Add** `due_date` (`DateTime(timezone=True)`, `NOT NULL`).
- **Drop** `test_phase_id` (column + index + FK).

Backfill order for existing rows (migration time, per-row):

1. Linked phase's `end_date`, if `test_phase_id` is set and the phase has one.
2. `MAX(gate_criterion.due_date)` across the gate's non-deleted criteria, if
   any are present.
3. The release's `target_date`, if set.
4. The release's `created_at::date`, as a final guaranteed-non-null fallback.

This priority preserves the intent of whoever set the phase link originally,
then falls back to signals already present on the gate's children, and only
invents a date from `created_at` when nothing else is available. Admins can
edit afterwards from the gate UI.

### `gate_criterion`

- **Drop** `due_date` column.
- Overdue logic moves to "gate is past its due_date and criterion.status is
  open" — evaluated at read time against the gate's date.

Before dropping, the migration copies `MAX(criterion.due_date)` into the
parent gate's `due_date` as part of the backfill chain above, so no date
signal is lost.

### Outbox events

- `ReleaseGateCreated` / `ReleaseGateUpdated` payloads gain `due_date`.
- No new event types. No migration of historical event rows.

## API changes

### `POST /api/v1/releases/{id}/gates`

Request body:

```json
{ "name": "UAT Sign-off", "due_date": "2026-05-01T00:00:00Z" }
```

- `due_date` becomes **required**.
- `test_phase_id` is removed from the schema.

### `PATCH /api/v1/release-gates/{gate_id}`

Adds `due_date` as an optional field in the partial-update body.
Removes `test_phase_id`.

### `GET /api/v1/releases/{id}/gates`

Response shape changes:

- Gate read adds `due_date` (required, ISO timestamp).
- Gate read removes `test_phase_id`.
- Each embedded `GateCriterionRead` removes its own `due_date`.
- `overdue_criterion_count` semantics change: when `gate.due_date < now` it
  equals the number of `status = "open"` criteria on that gate; when the
  gate's date is in the future it is `0`. Same name, simpler computation.

### `GET /api/v1/releases/timeline`

Each timeline entry gains a `gates` array:

```json
"gates": [
  { "id": 12, "name": "UAT Sign-off", "due_date": "2026-05-01T00:00:00Z", "status": "pending" }
]
```

Only non-deleted gates are returned. Status values: `pending | passed |
failed | overridden` — same set already used by `ReleaseGate.status`.

## Timeline rendering

`frontend/src/pages/releases/ReleaseTimeline.tsx` gets a new diamond draw
per gate, using the same polygon primitive as the existing `target_date`
diamond. Placement: centred on the row, at the x-coordinate matching
`gate.due_date`.

**Status colour map** (agreed in brainstorming):

| Status       | Fill      | Notes                          |
|--------------|-----------|--------------------------------|
| `pending`    | `#607d8b` | slate — neutral, not yet decided |
| `passed`     | `#43a047` | green                          |
| `failed`     | `#e53935` | red — draws the eye            |
| `overridden` | `#ffb300` | amber — distinct from target_date orange |

Tooltip on hover: `"{gate.name} — {status} — due {yyyy-mm-dd}"`.

The existing target-date diamond keeps `#ff9800` orange. Gate diamonds never
collide visually because the amber `overridden` is distinguishably lighter
and target_date has its own fixed colour.

**Date-range computation:** `computeDateRange` must also consider gate
`due_date` so gates at the edges of the schedule don't get clipped off the
right side of the chart. Pad logic (±7 days) unchanged.

**Legend:** add four small diamond swatches for `pending / passed / failed /
overridden` after the existing phase-status swatches.

## UI changes

### Gate create/edit form

- Add a `due_date` date-picker (required on create, editable on edit).
- Remove the "Test phase" selector.
- On create, default the picker to the release's `target_date` if set,
  otherwise today. Admin can change before saving.

### Gate list (`GatesTable.tsx`)

- Add a "Due" column showing `due_date` as a short date (`yyyy-mm-dd`).
- Remove any column / chip that references test phase.
- The overdue-criterion badge keeps its visual style but its meaning is now
  "open criteria past the gate's due date" — no UI copy change needed.

### Gate criterion row

- Remove the per-criterion "Due" column from `GateCriteriaTable`.
- Criterion rows show the parent gate's date if a date is displayed at all
  (it usually isn't — the parent gate row carries it).

### Release timeline legend

Extended as described in *Timeline rendering* above.

## Migration (`alembic`)

Single revision, manual DDL (no autogenerate — per project convention):

1. `ALTER TABLE release_gate ADD COLUMN due_date TIMESTAMP WITH TIME ZONE`
   (nullable during backfill).
2. `UPDATE release_gate SET due_date = <backfill chain>` using a single SQL
   CTE that joins `test_phase`, `gate_criterion`, and `release` to apply the
   priority above. Fallback to `release.created_at` guarantees non-null.
3. `ALTER TABLE release_gate ALTER COLUMN due_date SET NOT NULL`.
4. `DROP INDEX ix_release_gate_test_phase_id` (if present — the current
   migration names it via the column-index default).
5. `ALTER TABLE release_gate DROP COLUMN test_phase_id`.
6. `ALTER TABLE gate_criterion DROP COLUMN due_date`.

Downgrade adds the columns back as nullable, restores the index and FK; no
data is recoverable after downgrade, which is acceptable for a dev-phase
migration (there is no production data yet).

## Error handling

- `POST gates` without `due_date` → 422 from Pydantic (standard validation).
- `PATCH gates` with `due_date` set to past → allowed (admins may be fixing
  a missed milestone); no server-side validation.
- Deleting a gate cascades to criteria as today (no change).

## Testing strategy

Backend:

- Unit: `release_gate_service.create_gate` requires `due_date`; persists it.
- Unit: `list_gates_with_criteria` returns `due_date` on each gate and no
  longer returns `due_date` on criteria; `overdue_criterion_count` counts
  open criteria when the gate's `due_date < now`.
- Integration: `GET /releases/timeline` includes a `gates` array per entry
  with the correct fields.
- Integration: alembic upgrade on a DB with mixed-shape gate rows
  (phase-linked, criteria-dated, neither) produces the expected `due_date`
  per the priority chain.

Frontend:

- Snapshot-free visual check of `ReleaseTimeline` when a release has gates
  in each of the four statuses.
- Gate form submit blocked until `due_date` is set.

## Rollout

One-shot migration + code change, merged as a single MR into `main` via the
usual GitLab MR flow. No feature flag.

## Open decisions

None. The four brainstorming questions (A / A / A / B) are all locked.
