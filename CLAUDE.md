# EnvManager - Claude Code Guide

> **Repo / remote (2026-07-22)**: Canonical remote is now **GitHub `github.com/pjgross/envmgr`** (private, default `main`) via git remote `github`. The old local GitLab (`origin`, `localhost:8929`) is **legacy/dev-only** and its `main` is stale — push and open PRs against **GitHub** (`gh` CLI, account `pjgross`). Main tip `22b6a9b` (2026-07-31).
> **Hardening programme (2026-07-30) — ✅ COMPLETE**, 11 PRs (#23–#33) merged to `main`, CI green on both engines; docs then realigned (#34) and superseded docs archived (#35) — tip `dbfa73a`. In order: migration-built databases were broken (6 tables missing `Base` timestamps) + a drift guard; unauthenticated `/auth/register` could mint an Admin in any tenant; **GitHub Actions CI** (there was none); **Dockerfiles + wired compose** (there was no deployable artifact); all dependency advisories cleared + audit gates; Neo4j and pika removed (never used); **dual-engine test suite + foreign key enforcement** (SQLite was ignoring FKs, 41 tests were inserting broken rows); structured logging, request ids, `/metrics`, supervised outbox publisher; frontend code splitting (3,445 kB → 180 kB entry); refresh-token sessions with revocation + login rate limiting; bounded list results.
>
> **Pagination programme (2026-07-30/31) — ✅ A/B/C1 MERGED to `main`**, tip `22b6a9b`, CI green on both engines. The three formerly-stacked PRs landed in order on 2026-07-31 and their branches are deleted: **#36** `feature/pagination-sweep` (sub-project A: bounded 22 list endpoints, merge `305c222`); **#37** `feature/pagination-sweep-b` (B: restructured 5 queries that filtered after execution, then bounded them, merge `cbd2974`); **#38** `feature/pagination-sweep-c1` (C1: whitelist-based `sorting()` + the filter params the grids lacked, merge `22b6a9b`). **Sub-project C3 — the frontend half — is NOT started**, and it is the one that fixes the live bug: every list page fetches a capped page then filters it *in the browser*, so `ReleaseList` sends no filters, gets the newest 50 releases, and filters those 50 in JavaScript. Read the **"What sub-project C3 must honour"** section of [docs/pagination.md](docs/pagination.md) before starting C3 — it is the durable contract (sort whitelists, the 12 never-sortable computed columns, the endpoint-wide `default_dir` hazard). Suite at C1's tip: 1056 passed/10 skipped SQLite, 1065/1 PostgreSQL.
> **Next**: Phase 6 (Infrastructure Topology) — plans against PostgreSQL, no graph store. Known open items: of **51** `GET .../response_model=list[...]` endpoints (reproducible count in [docs/pagination.md](docs/pagination.md)), **27** are bounded and **24** are not, after a follow-on pass restructured four of the six that used to be blocked on Python-side filtering/merging (`GET /{release_id}/raid` — `rag`/`overdue` into SQL; `GET /systems/{id}/dependencies` and `GET /subsystems/{id}/dependencies` — two concatenated queries into one `OR` query; `GET /environments/{id}/versions` — `current_only` dedup into a `ROW_NUMBER()` window; `GET /releases/{id}/dependency-alerts` — its N+1 became a join with `IS DISTINCT FROM`, but it stays **unbounded**: a second filter, `diff_days == 0`, drops rows after the query and has no portable SQL form, so a page would window the pre-filter set) plus `GET /releases/{id}/membership` (not in the 51 — it returns a dict; its `history` list is now bounded, `X-Total-Count` describes `history` only, not `current`+`history` combined). **"Blocked on a query restructure" now holds one endpoint** — `dependency-alerts`, for the reason above; the five cleared cases stay on record in docs/pagination.md rather than being deleted. Sub-project **C1** then added a whitelist-based `sorting()` primitive (sibling to `pagination()`, same 422-not-silent-fallback contract) to nine of the bounded endpoints, plus the filter parameters their grids needed (`search` on environments/systems, widened `search` on infrastructure-components, `environment_search`/`release_search` on deployments, `subsystem_search` on builds) — and bounded `GET /builds` itself in the process, its one deliberate behaviour change (a new `id` tiebreaker on an endpoint that had none). See docs/pagination.md's "What sub-project C3 must honour" for the sortable-column contract the frontend half (C3) depends on: which columns are permanently unsortable (computed post-query), the endpoint-wide `default_dir` hazard, and the enum name-vs-value storage gotcha. Of the remaining 24: **2** (`rollup/systems`, `rollup/members`, alongside 3 non-list aggregation endpoints) are permanently unbounded by design; **17** are bounded in practice by tenant configuration or by a single entity's own structure/history — neither needs action; **1** (`GET /environments/{id}/health/history`) already has its own hand-rolled limit and just needs wiring to the shared primitive for `X-Total-Count`; **3** (plus 2 more outside the 51-count because they don't declare `response_model=list[...]`) are genuinely growth-bearing and simply not done yet — `GET /releases/{id}/bookings`, `GET /releases/{id}/change-requests`, `GET /environments/{id}/deployments` (inconsistent with its bounded sibling `GET /deployments`), `GET /tenant/users/lite`, and `GET /bookings/{id}/received-feedback`. Still open: `GET /releases/calendar` and `/releases/timeline` call `list_releases` with a hardcoded `limit=500` and discard the total, silently truncating past 500 releases; and in the membership view, an accepted membership appears in both `current` and `history` (pre-existing, deliberately untouched — a semantic change, not a pagination one). env-topology SP4 (group-by-system/host toggle); `docs/architecture copy.md` could use a real filename (content is current — it is the macmini host map).
>
> **First prod deploy after this**: signs everyone out once (old 24h tokens have no refresh token), requires `SECRET_KEY` + `POSTGRES_PASSWORD`, runs migrations `basetimestamps` + `authsessions` from the entrypoint, and the SP1/SP2 tenant backfill scripts remain a standing step. See [docs/dependency-audit.md](docs/dependency-audit.md), [docs/pagination.md](docs/pagination.md), [docs/decisions/](docs/decisions/) and §8/§9/§12/§13/§14 of the architecture reference.
> **Current Phase (2026-07-29)**: Everything merged + pushed to GitHub `main`. Phase 1 ✅ | Phase 2 ✅ | Phase 2.5 ✅ | Phase 3 Sub-1/Sub-2 ✅ (Sub-3 Jira deferred) | Phase 4 ✅ (incl. user/admin manual, `build_number` required, `GET /api/v1/webhooks/can-deploy` preflight, GitLab-CI dogfooding pipeline). **Phase 5 ✅ COMPLETE + in-app verified** — 5 sub-projects: SP1 Incident Tracking, SP2 DORA Metrics, SP3 Environment Health, SP4 PIR, SP5b Release/Booking-conflict metrics, SP5a Environment Operating Hours + Utilization (DST-correct, `zoneinfo`); latest migration `environment_operating_hours` (`7441806378e5`). Health-alert closed-booking bug fixed. **Release RAID log fully shipped + UI-verified** (backend + frontend + docs + enterprise rollup; migration `raidlogtables`). **UI audit done** — P1 fixes landed, P2/P3 backlog. Phase 5 follow-on: SP1/SP2 tenant backfill scripts are a standing **prod**-deploy step (dev confirmed clean). Next: per [docs/plan.md](docs/plan.md) / [docs/gap-analysis.md](docs/gap-analysis.md) (Phases 6–13).
> **Requirements**: [docs/requirements.md](docs/requirements.md)
> **App Architecture**: [docs/prod architecture.md](docs/prod%20architecture.md)
> **Infra (macmini)**: [docs/architecture copy.md](docs/architecture%20copy.md)
> **Roadmap**: [docs/plan.md](docs/plan.md) | **Phase 1 summary**: [docs/phases/phase-1.md](docs/phases/phase-1.md) | **Phase 2 summary**: [docs/phases/phase-2.md](docs/phases/phase-2.md) | **Phase 3 summary**: [docs/phases/phase-3.md](docs/phases/phase-3.md)
> **Gap analysis (2026-07-16)**: [docs/gap-analysis.md](docs/gap-analysis.md) — capability coverage vs the Release/Environment Management intro docs; added Phases 9–13 (Release Governance, Test Data Management, Cost/FinOps, Compliance/Audit, ITSM) + expanded Phases 6 & 7.
> **Admin Guide**: [docs/admin-guide.md](docs/admin-guide.md)
> **User Guide**: [docs/user-guide.md](docs/user-guide.md)
> **CI**: [.github/workflows/ci.yml](.github/workflows/ci.yml) — pytest on SQLite **and** PostgreSQL, lint, build, image builds, dependency audits. The GitLab pipeline ([docs/gitlab-ci-setup.md](docs/gitlab-ci-setup.md)) is deployment-tracking dogfooding, not the gate on `main`.
> **Dependency policy**: [docs/dependency-audit.md](docs/dependency-audit.md) | **Pagination**: [docs/pagination.md](docs/pagination.md) | **Decisions**: [docs/decisions/](docs/decisions/)
> **UI Audit (2026-07-22)**: [docs/ui-audit.md](docs/ui-audit.md) — ranked usability/consistency/a11y findings; P1 fixed, P2/P3 remain as backlog.

EnvManager is a multi-tenant test environment management platform: inventory, booking, change management, CI/CD tracking, DORA metrics, and infrastructure topology visualization.

Stack: FastAPI + PostgreSQL + Redis + **NATS** (backend) / React 18 + TypeScript + MUI + Redux Toolkit (frontend).

---

## Dev Environment

Runs fully containerised on **OrbStack** (macOS). `docker-compose up -d` starts all services locally; OrbStack provides DNS at `<service>.orb.local` for inter-container access.

```bash
# 1. Start infrastructure (PostgreSQL, Redis, NATS)
docker-compose up -d

# 2. Backend env (once) — DEBUG=true is what permits the repo's placeholder
#    SECRET_KEY; with DEBUG=false the app refuses to start without a real one
cd backend && cp .env.example .env

# 3. Run migrations
cd backend && alembic upgrade head

# 4. Backend (separate terminal)
cd backend && uvicorn app.main:app --reload

# 5. Frontend (separate terminal)
cd frontend && npm run dev
```

| Service | Dev URL | Notes |
|---------|---------|-------|
| Frontend | http://localhost:5173 | Vite dev server |
| Backend API | http://localhost:8000 | FastAPI |
| API Docs | http://localhost:8000/docs | Swagger UI |
| NATS Monitor | http://localhost:8222 | Local NATS container |
| Metrics | http://localhost:8000/metrics | Prometheus exposition |
| PostgreSQL | localhost:5432 | Local Postgres container |
| Redis | localhost:6379 | Local Redis container |
| Jira | http://localhost:8090 | Dev/testing only — not in prod |
| GitLab | http://localhost:8929 | Dev/testing only — not in prod |
| GitLab SSH | localhost:2224 | Dev/testing only — not in prod |

Demo login: `admin` / `admin123` (tenant: `demo`)

Master admin login: `masteradmin` / `masteradmin123` (tenant: `system`)
Run once to seed: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_master_admin.py`

---

## Production Deployment

Production runs on **macmini** (Tailscale network). EnvManager's containers are deployed via docker-compose. Several infrastructure services are shared from the macmini host rather than duplicated.

```bash
SECRET_KEY=$(openssl rand -hex 32) POSTGRES_PASSWORD=... \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    --profile app up -d --build
```

- `backend` and `frontend` live under the compose **`app` profile** so the dev flow above (`docker-compose up -d` for infra, uvicorn + vite on the host) doesn't fight them for ports 8000/5173.
- `SECRET_KEY` and `POSTGRES_PASSWORD` are **required** — compose fails fast without them, and the backend refuses to start with `DEBUG=false` and the repo's placeholder key.
- The backend image's entrypoint runs `alembic upgrade head` **before** uvicorn. That order matters: `init_db()` calls `create_all`, so if the app started first it would build the schema itself and leave `alembic_version` empty, after which migrations fail on "relation already exists". Set `RUN_MIGRATIONS=0` to skip.
- The frontend image is nginx serving the built bundle and proxying `/api` to `BACKEND_ORIGIN` (`src/services/api.ts` uses a relative `/api/v1` baseURL, so whatever serves the bundle must also proxy the API).
- Port lists in `docker-compose.prod.yml` use `!override`; without it compose **appends** to the base list and republishes the base port too.

| Service | Source | Prod connection |
|---------|--------|-----------------|
| PostgreSQL | EnvManager docker-compose | `localhost:5435` (own container) |
| Redis | EnvManager docker-compose | `localhost:6379` (own container) |
| NATS | **Shared — macmini** | `nats://macmini:4222` |
| Grafana | **Shared — macmini** | `http://macmini:3003` |
| Prometheus | **Shared — macmini** | `http://macmini:9093` |
| Backend API | EnvManager docker-compose | `http://macmini:8100` |
| Frontend | EnvManager docker-compose | `http://macmini:5173` (or via Caddy) |

**No graph database**: Neo4j was provisioned early but never used — topology is PostgreSQL-backed. Removed 2026-07-30, see [docs/decisions/2026-07-30-drop-neo4j.md](docs/decisions/2026-07-30-drop-neo4j.md). The macmini Neo4j instance is a shared host service for other projects and still runs; EnvManager just doesn't connect to it.

Prod architecture reference: [`docs/architecture copy.md`](docs/architecture%20copy.md)

---

## Code Conventions

**Python**: PEP 8, type hints, async/await throughout. `snake_case` functions/vars, `PascalCase` classes.

**TypeScript**: Strict mode, explicit types, functional components. `camelCase` functions/vars, `PascalCase` components/types.

**Git**: Branch names like `feature/phase1-environment-crud`. Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.

---

## Adding a New Feature (checklist)

1. `backend/app/db/models/<entity>.py` — SQLAlchemy model with `tenant_id`; all enum columns use `native_enum=False` (stores as VARCHAR — keeps SQLite test compat)
2. `alembic revision -m "..."` then write DDL **manually** — do NOT use `--autogenerate` (init_db uses create_all so autogenerate sees nothing to do for new tables); use `op.create_table()` for new tables, `op.add_column()` for new columns
3. `alembic upgrade head`
4. `backend/app/services/<entity>_service.py` — business logic, no HTTP code; use `db.flush()` not `db.commit()` when you need the DB to assign an ID mid-transaction
5. `backend/app/api/v1/<entities>.py` — thin endpoints, delegate to service
6. `frontend/src/services/<entity>Service.ts` — API client
7. `frontend/src/store/<entity>Slice.ts` — Redux slice with async thunks
8. `frontend/src/pages/<EntityList>.tsx` — page component using Redux

---

## Common Pitfalls

- **Business logic in API endpoints** — keep endpoints thin, put logic in services
- **Missing tenant_id filter** — every query on tenant-scoped tables must filter by `tenant_id`; use `current_user.active_tenant_id` (not `.tenant_id`) to handle impersonation correctly
- **API calls in React components** — use Redux async thunks + service layer instead
- **Synchronous DB operations** — always use `async/await` with `AsyncSession`
- **Hard deleting records** — use soft deletes (`deleted_at = datetime.now(timezone.utc)`); only dependency/junction records use hard delete
- **Skipping migrations** — always create an Alembic migration for schema changes; write manual DDL (see checklist above)
- **`db.commit()` in services** — `get_db()` auto-commits on success; calling `db.commit()` inside a service will break the outbox pattern (event rows must commit atomically with the business write). Use `db.flush()` if you need the DB to assign an ID mid-transaction
- **Native enums** — always set `native_enum=False` on enum columns; PostgreSQL native ENUMs break SQLite-based tests and are hard to alter later
- **`--autogenerate` migrations** — `init_db()` calls `create_all`, so Alembic autogenerate sees tables as already existing and generates empty migrations. Always use `alembic revision -m "..."` and write the DDL manually
- **Fabricating foreign keys in tests** — never point a test row at an id you haven't created (`subsystem_id=1`, `raised_by=1`). SQLite silently ignored FKs until `PRAGMA foreign_keys=ON` was added, so ~40 tests were inserting broken rows and passing. Use the helpers in `backend/tests/factories.py`
- **Testing only on SQLite** — the suite defaults to in-memory SQLite, but partial unique indexes and other dialect-gated DDL are inert there. Run it against PostgreSQL too before trusting a schema or query change: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` (CI runs both legs)
- **Secrets in code** — use environment variables and `.env` files. `SECRET_KEY` must be set for any `DEBUG=false` deployment; the app refuses to start with the repo's placeholder
- **Self-service user creation** — there is no `/auth/register`; create users via `POST /api/v1/tenant/users`, which is admin-gated and forces the caller's tenant
- **Unbounded list endpoints** — new list endpoints take `page: Page = Depends(pagination())` (it's a factory — call it) and their service returns `(rows, total)` via `fetch_page` for a single-entity select or `fetch_page_rows` for a multi-column one; see [docs/pagination.md](docs/pagination.md). Order by a **unique** key — append the primary key as a tiebreaker, or `LIMIT`/`OFFSET` will duplicate and drop rows across pages once ties exist. Never add `limit` to an endpoint whose service filters in Python after the query, or merges two executed queries — the page would be windowed before the filter and the results quietly wrong. If the endpoint also needs a `sort_by`/`sort_dir`, use `sorting()` (same file) the same way: it's a **whitelist** mapping client field names to ORM columns — `sort_by` is never used to address a column directly (no `getattr`, no interpolation) — and an unknown `sort_by` is a **422**, not a silent fallback. Chain `apply_sort` **before** the tiebreaker, never instead of it (`apply_sort(query, sort).order_by(Model.id)`), and never whitelist a column a service computes in Python after the query — it isn't backed by a single column to sort by
- **Minting tokens by hand** — `create_access_token` alone produces an unrevocable session. Use `auth_session_service.issue_session`; anything that invalidates a password must call `revoke_all_for_user`

---

## Quick Reference

```python
# Sessions: 15-minute access token + 14-day rotating refresh token. Never mint a
# token with create_access_token directly — go through auth_session_service so the
# session gets a revocable database row.
from app.services import auth_session_service
session = await auth_session_service.issue_session(db, user)

# Logging — the root logger is configured at import; just take a module logger.
# Lines are stamped with the current request id automatically.
import logging
logger = logging.getLogger(__name__)

# Database session
from app.db.base import get_db
async def my_endpoint(db: AsyncSession = Depends(get_db)): ...

# Auth + tenant context (use active_tenant_id — handles impersonation)
from app.core.security import get_current_user
async def my_endpoint(current_user: User = Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id  # NOT .tenant_id

# Require master admin
from app.core.security import require_master_admin
async def my_endpoint(current_user=Depends(require_master_admin())): ...

# Require tenant admin (role="Admin")
from app.core.security import require_tenant_admin
async def my_endpoint(current_user=Depends(require_tenant_admin())): ...

# Require any specific role
from app.core.security import require_role, Role
async def my_endpoint(current_user=Depends(require_role(Role.RELEASE_MANAGER))): ...

# Publish event (outbox pattern)
from app.core.events import publish_event
await publish_event(event_type="BookingCreated", aggregate_id=booking.id, payload={...})
```

```typescript
// Frontend: dispatch async thunk
const dispatch = useDispatch();
useEffect(() => { dispatch(fetchEnvironments()); }, []);
```

---

## Architecture Reference

See [docs/prod architecture.md](docs/prod%20architecture.md) for:
- Multi-tier architecture diagram
- Layer responsibilities (API / Service / DB)
- Multi-tenancy pattern
- Event-driven architecture & outbox pattern (NATS/JetStream)
- Database design patterns
- Frontend state management
- GitHub-first infrastructure discovery
- API design standards & response formats
- Testing strategy
- Deployment architecture (dev OrbStack + prod macmini)

See [docs/architecture copy.md](docs/architecture%20copy.md) for the macmini host service map (all running Docker services, ports, and endpoints).

---

> **Note**: `CLAUDE.md` (this file) is the authoritative guide for Claude Code sessions. The original Gemini-era guide is kept at [docs/archive/GEMINI.md](docs/archive/GEMINI.md) — see [docs/archive/](docs/archive/) for what else is there and why.
