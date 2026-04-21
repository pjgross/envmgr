# EnvManager - Claude Code Guide

> **Current Phase**: Phase 3 Sub-project 1 (Core Releases) + follow-ups (lifecycle permissions unification, gate criteria with overdue tracking, MUI confirm sweep, scope-item custom fields, scope-item lifecycle with moves/backlog/status history) merged to `main` on 2026-04-20 / 2026-04-21 via MRs !4–!12 (main tip `35e3a99`). Phase 1 ✅ | Phase 2 ✅ | Phase 2.5 ✅ | Phase 3 Sub-1 ✅ | Phase 3 Sub-2/3 (Enterprise, Jira, PIR) deferred | Phase 4 next.
> **Requirements**: [docs/requirements.md](docs/requirements.md)
> **App Architecture**: [docs/prod architecture.md](docs/prod%20architecture.md)
> **Infra (macmini)**: [docs/architecture copy.md](docs/architecture%20copy.md)
> **Roadmap**: [docs/plan.md](docs/plan.md) | **Phase 1 summary**: [docs/phases/phase-1.md](docs/phases/phase-1.md) | **Phase 2 summary**: [docs/phases/phase-2.md](docs/phases/phase-2.md) | **Phase 3 summary**: [docs/phases/phase-3.md](docs/phases/phase-3.md)

EnvManager is a multi-tenant test environment management platform: inventory, booking, change management, CI/CD tracking, DORA metrics, and infrastructure topology visualization.

Stack: FastAPI + PostgreSQL + Neo4j + Redis + **NATS** (backend) / React 18 + TypeScript + MUI + Redux Toolkit (frontend).

---

## Dev Environment

Runs fully containerised on **OrbStack** (macOS). `docker-compose up -d` starts all services locally; OrbStack provides DNS at `<service>.orb.local` for inter-container access.

```bash
# 1. Start infrastructure (PostgreSQL, Neo4j, Redis, NATS)
docker-compose up -d

# 2. Run migrations
cd backend && alembic upgrade head

# 3. Backend (separate terminal)
cd backend && uvicorn app.main:app --reload

# 4. Frontend (separate terminal)
cd frontend && npm run dev
```

| Service | Dev URL | Notes |
|---------|---------|-------|
| Frontend | http://localhost:5173 | Vite dev server |
| Backend API | http://localhost:8000 | FastAPI |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Neo4j Browser | http://localhost:7474 | Local Neo4j container |
| NATS Monitor | http://localhost:8222 | Local NATS container |
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

| Service | Source | Prod connection |
|---------|--------|-----------------|
| PostgreSQL | EnvManager docker-compose | `localhost:5435` (own container) |
| Neo4j | **Shared — macmini** | `bolt://macmini:7687` |
| Redis | EnvManager docker-compose | `localhost:6379` (own container) |
| NATS | **Shared — macmini** | `nats://macmini:4222` |
| Grafana | **Shared — macmini** | `http://macmini:3003` |
| Prometheus | **Shared — macmini** | `http://macmini:9093` |
| Backend API | EnvManager docker-compose | `http://macmini:8100` |
| Frontend | EnvManager docker-compose | `http://macmini:5173` (or via Caddy) |

**Neo4j note**: macmini runs Neo4j Community Edition (single database). EnvManager uses dedicated node labels/prefixes to namespace its data within the shared instance. See `docs/architecture.md §11` for details.

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
- **Secrets in code** — use environment variables and `.env` files

---

## Quick Reference

```python
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

> **Note**: `GEMINI.md` at the project root is the original Gemini-era guide and is kept as a historical reference. `CLAUDE.md` (this file) is the authoritative guide for Claude Code sessions.
