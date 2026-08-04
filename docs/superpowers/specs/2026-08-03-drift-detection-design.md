# Drift detection — design

> Status: design agreed 2026-08-03. Phase 6 sub-project 2, the last one outstanding.
> Prior art: [GitHub repository scanning](2026-08-03-github-repository-scanning-design.md),
> [environment comparison](2026-08-03-environment-comparison-design.md).

## What this is

A read-only report answering one question about a single System: **does EnvManager's
subsystem catalogue still match what the system's repository declares?**

It compares repository IaC against the subsystem catalogue. It never writes. Reconciling
is done by pressing the existing Scan button, or by hand.

## Why the phase doc's framing had to change

`docs/phases/phase-6.md` describes this sub-project as comparing "IaC-declared against
recorded state", and notes it was blocked on where `.tfstate` comes from. Reading the
shipped code moves the problem:

1. **The IaC parsers write `SubSystem` rows, not `InfrastructureComponent` rows.**
   `terraform_hcl_import_service` and `docker_compose_import_service` both upsert into the
   system catalogue. Nothing anywhere sets `InfrastructureComponentSource.TERRAFORM` — that
   enum value is unused. The natural comparison is therefore IaC against the *subsystem
   catalogue*, which needs no `.tfstate` and no new data source.

2. **`SubSystem` has no provenance.** A scan-created subsystem is indistinguishable from a
   hand-created one, so "in EnvManager but not in the code" cannot currently be told apart
   from "deliberately added by hand". This design adds that provenance.

3. **A scan already destroys the evidence as it finds it.** The importers upsert by name:
   they silently overwrite `component_type` and `technology`, and never touch resources that
   have vanished from the code. Drift exists in the data today and is simply never reported.

`.tf`-versus-`.tfstate` drift — the classic framing — stays out of scope. Its two blockers
are unchanged: `.tfstate` is not normally in the repository, and `.tf` declares resources
without computed values or resource ids, so the two formats do not produce comparable rows.

## Decisions

| Decision | Choice |
|---|---|
| What is compared | Repository IaC ↔ subsystem catalogue |
| Relationship to scan | Separate read-only report. Scan is unchanged and remains the apply path |
| Provenance | New `source` + `source_path` columns on `SubSystem` |
| Coverage | Subsystems **and** compose dependency edges |
| Placement | System detail page, computed on demand, never stored |
| Architecture | Split parse from persist; `apply()` and `diff()` consume one declared value |

Scan keeps writing immediately and drift never writes. The two together still give
preview-then-apply loosely, without a behaviour change to a shipped feature. Note the
scanner **never deletes**, so `missing_in_code` is a category no scan can resolve — the
drift report is the only place it is ever visible.

## Architecture

### Parse/apply/diff split

Detectors currently *are* the writers: `import_terraform_hcl` parses and persists in one
pass, so there is no point at which "what the code declares" exists as a value that could be
compared. The refactor introduces one.

```
backend/app/services/scanning/
  declared.py      NEW  value objects below
  reconcile.py     NEW  apply() and diff()
  registry.py           Detector.parse now returns DeclaredState
  scanner.py            walks the repo, collects DeclaredState per detector
  detectors/
    compose.py
    terraform_hcl.py
```

```python
@dataclass(frozen=True)
class DeclaredSubsystem:
    name: str
    component_type: str
    technology: str | None
    source_path: str

@dataclass(frozen=True)
class DeclaredEdge:
    from_name: str
    to_name: str
    port: int | None
    source_path: str

@dataclass
class DeclaredState:
    subsystems: list[DeclaredSubsystem] = field(default_factory=list)
    edges: list[DeclaredEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```

`ParseContext` sheds `db`, `system_id` and `tenant_id` — parsing needs only `content`, `path`
and `fetch`. That is what makes the parsers testable without a database.

Two consumers read the same `DeclaredState`:

- `reconcile.apply(db, system_id, tenant_id, source, declared) -> DetectorResult` — the
  existing scan behaviour, moved out of the import services.
- `reconcile.diff(db, system_id, tenant_id, source, declared) -> DriftReport` — new.

Because both read one declared value, the report cannot describe something a scan would not
do.

**The per-detector `begin_nested()` savepoint moves from parse to `apply`.** It must survive
the refactor: its purpose is that one detector's failed write cannot mark the session for
rollback and erase every other detector's results at commit time.

### Schema change

`SubSystem` gains:

- `source` — enum `manual` / `terraform` / `terraform_hcl` / `docker_compose`, `native_enum=False`,
  `nullable=False`, `server_default='manual'`.
- `source_path` — `String(500)`, nullable.

There are exactly four `SubSystem` creation sites and each stamps its own value:
`system_service` (manual), `terraform_import_service` (`.tfstate` upload → `terraform`),
`terraform_hcl_import_service` (`terraform_hcl`), `docker_compose_import_service`
(`docker_compose`). `excel_import_service` does not create subsystems.

Migration is hand-written `op.add_column` DDL — the repo's `init_db()` calls `create_all`, so
`--autogenerate` produces empty migrations.

Existing rows backfill to `manual`, including ones a past scan created. This deliberately
errs quiet rather than noisy: those rows will not appear as drift until re-scanned. It
self-heals because `apply()` stamps `source` and `source_path` on rows it **updates**, not
only on rows it creates.

### The soundness rule

GitHub truncates the tree of a large repository and the scan caps files fetched. If any file
a detector claimed went unread, then "in the catalogue but not in the code" is **unsound**:
unread files are indistinguishable from deletions.

So, per detector, when any of `truncated`, `stopped_early`, `paths_unread > 0`, or a fetch
error applies, the absence category is **not computed at all** and the response carries the
reason.

> **Positive findings survive a partial read; absence findings do not.**

Presence and type-change come from files actually read. Absence is only provable from a
complete one.

## What counts as drift

**Matching key** is `subsystem.name` within `(tenant_id, system_id, deleted_at IS NULL)` —
the same key the importers upsert on, so the differ and the writer cannot disagree about
identity.

**Comparison is scoped per source.** For each IaC source, catalogue rows carrying that
`source` are compared only against the declared set from the detector that owns it. Without
this, running only the compose detector would report every `terraform_hcl` row as deleted.

A consequence worth stating: **`terraform`-sourced rows are never reported absent.** They
come from a `.tfstate` upload, nothing in a repository scan looks for them, and so there is
no complete read to prove absence from. That falls out of the soundness rule rather than
being a special case.

A second consequence looks alarming but is correct: if a repository no longer contains **any**
file a detector claims — every `.tf` deleted, say — that detector reads zero paths with no
truncation and no errors, absence *is* computed, and every row carrying its source reports as
`missing_in_code`. That is a complete read of an empty declared set, and those rows genuinely
are drift. The UI must not special-case it into silence; a system whose Terraform was deleted
wholesale is exactly the case this report exists to surface.

### Subsystem categories

| Category | Meaning | Does a scan resolve it? |
|---|---|---|
| `missing_in_catalogue` | Declared in code, no catalogue row | Yes — creates it |
| `missing_in_code` | IaC-sourced row, no longer declared | **No** — the scanner never deletes |
| `changed` | Name matches, `component_type` or `technology` differs | Yes — overwrites |

A changed `source_path` is **not** drift. A resource moving between files is a refactor, and
reporting it would bury the real findings. The current path is shown as context, never as a
difference.

### Edge categories

The same three categories over `ComponentDependency` rows with `source=docker_compose` whose
endpoints are both subsystems of this system, with `port` as the only comparable attribute.
Dependency edges already carry provenance via `DependencySource`, so they need no migration.

An edge whose endpoint subsystem is itself missing from the catalogue is reported as
`missing_in_catalogue` — its creation is implied by the subsystem's.

Unlike subsystems, dependency drift *is* fully resolved by a scan: the compose importer
deletes and recreates its edges on every run.

### Limits carried, not fixed

- **Duplicate declarations.** Two compose files both declaring `redis` collapse to one
  catalogue row today, last write wins, silently. The diff emits a warning naming both paths
  rather than double-counting or silently picking one.
- **One namespace, two conventions.** Terraform names are `<type>.<name>`, compose names are
  bare service names, and both share `subsystem.name`. A compose service literally named
  `aws_db_instance.main` would collide. Pre-existing; out of scope.

## API

`GET /api/v1/systems/{system_id}/github/drift`, mirroring the scan's path and its
`require_tenant_admin()` gate — it reads repository contents through the tenant's stored
token, so it must not be looser than the scan that does the same thing.

It shares the scanner's `_in_flight` lock. A drift check reading a catalogue that a
concurrent scan is mutating would report differences that exist on neither side.

GitHub failure handling is inherited wholesale from the scan: 503 when
`GITHUB_OAUTH_CLIENT_ID` is unset, revoked-token clearing performed outside the failing
request, per-path fetch errors recorded against the claiming detectors rather than aborting
the walk, and `GitHubAuthError`/`GitHubRateLimited` still propagating.

Response shape, per detector:

```json
{
  "ref": "main",
  "files_scanned": 12,
  "truncated": false,
  "stopped_early": false,
  "detectors": [
    {
      "detector": "docker_compose",
      "paths": ["docker-compose.yml"],
      "paths_unread": 0,
      "errors": [],
      "warnings": [],
      "absence_computed": true,
      "absence_reason": null,
      "subsystems": {
        "missing_in_catalogue": [],
        "missing_in_code": [],
        "changed": []
      },
      "edges": {
        "missing_in_catalogue": [],
        "missing_in_code": [],
        "changed": []
      }
    }
  ]
}
```

When `absence_computed` is false, the `missing_in_code` keys are **null**, never `[]`. "We
checked and found nothing missing" and "we could not check" are opposite conclusions, and an
empty list renders them identical to the UI and to any test trying to tell them apart.

## UI

A "Check drift" action on the System detail page beside the existing scan panel, rendering
per-detector sections with the three groups. Entities are rendered by name throughout.

The empty state states the positive: the catalogue matches the code. When absence was not
computed, a banner explains why and the group is **not rendered at all**, rather than
rendered empty.

## Testing

The load-bearing test:

> `apply(declared)` followed by `diff(declared)` over the same `DeclaredState` must report
> **zero** drift.

This pins the two consumers together. It fails the moment the writer and the differ disagree
about identity, type inference or edge handling — which is the failure mode that would make
this feature actively misleading rather than merely incomplete. It is behavioural, not an
assertion about emitted SQL.

Also:

- Parsers are pure after the refactor, so they get database-free unit tests over fixture
  content.
- `diff()` runs against a seeded catalogue on **both engines** — SQLite and PostgreSQL.
- A truncated-tree test asserts the absence category is *not computed* and the reason is
  present, which must be distinguishable from computed-and-empty.
- The existing detector tests pinned against a real repository's file list are the refactor's
  safety net and must stay green throughout.
- Per this repo's history with tests that pass while guarding nothing, **each new test is
  mutated to confirm it fails** — the truncation test especially, since it is easy to write
  one that passes because the category is empty for the wrong reason.

## Out of scope

- `.tf` versus `.tfstate` drift (see above).
- Scheduled or webhook-driven drift checks. There is still one supervised asyncio loop and no
  task queue; a scheduler deserves its own spec.
- A tenant-wide drift dashboard. With no task queue it would mean N sequential GitHub scans
  inside one request.
- Drift over host bindings. Nothing writes `environment_subsystem_host` from IaC, so there is
  no declared side to compare against and the category would always be empty.
- Making the scan itself non-destructive, or teaching it to delete.
