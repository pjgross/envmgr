# EnvManager — Architecture Reference

> Referenced from [CLAUDE.md](../CLAUDE.md) | Roadmap: [plan.md](plan.md)
> macmini infra: [architecture copy.md](architecture%20copy.md)

---

## 1. Multi-Tier Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React)                  │
│  - Pages, Components, Redux Store, API Services     │
└─────────────────────┬───────────────────────────────┘
                      │ HTTP/REST
┌─────────────────────▼───────────────────────────────┐
│              API Layer (FastAPI)                     │
│  - Endpoints, Request/Response validation (Pydantic)│
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│            Service Layer (Business Logic)            │
│  - Domain logic, orchestration, validation          │
└─────────────┬───────────────────┬───────────────────┘
              │                   │
┌─────────────▼─────────┐  ┌─────▼──────────────────┐
│  Database Layer       │  │  External Services     │
│  - Models (SQLAlchemy)│  │  - GitHub, Jira, CI/CD │
│  - Repositories       │  │  - Redis, NATS         │
└───────────────────────┘  └────────────────────────┘
```

---

## 2. Backend Layer Responsibilities

### API Layer (`backend/app/api/v1/`)

**Purpose**: HTTP endpoint definitions, request/response handling.

- Use Pydantic models for request/response validation
- Keep endpoints thin — delegate to service layer
- Handle HTTP-specific concerns (status codes, headers)
- Apply authentication/authorization decorators
- Take `page: Page = Depends(pagination())` on list endpoints and set `X-Total-Count` (§8)
- **Commit before raising** when a write has to survive the error being returned —
  `get_db()` rolls back on exception, so a rate-limit record or a token revocation
  written on the way to a 4xx is otherwise discarded. Services signal this by raising
  a distinct exception type; see `auth.py`

Examples: `environments.py`, `bookings.py`, `auth.py`

### Service Layer (`backend/app/services/`)

**Purpose**: Business logic, orchestration, domain rules.

- No HTTP-specific code (no Request/Response objects)
- Coordinate between multiple repositories/models
- Implement business validation rules
- Publish domain events
- Handle transactions
- Reusable across different API endpoints

Examples: `booking_service.py`, `environment_service.py`

### Database Layer (`backend/app/db/models/`)

**Purpose**: Data persistence, ORM models.

- SQLAlchemy models with type hints (`Mapped[]`)
- Relationships defined with `relationship()`
- No business logic in models (only data structure)
- Use Base class for common fields (`id`, `created_at`, `updated_at`)
- Migrations managed by Alembic

Examples: `user.py`, `environment.py`, `booking.py`

---

## 3. Multi-Tenancy Pattern

**Every tenant-scoped table MUST**:
- Include `tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)`
- Filter by `tenant_id` in all queries
- Include tenant context in JWT tokens
- Enforce row-level security (PostgreSQL RLS policies — deferred; app-level `tenant_id` filtering used throughout)

**Tenant Context Flow**:
1. User authenticates → JWT token includes `tenant_id`
2. API endpoint extracts `tenant_id` from token
3. Service layer filters all queries by `tenant_id`
4. Database enforces RLS policies as additional safeguard

---

## 4. Event-Driven Architecture

**Outbox Pattern** — events written atomically with business operations:

```python
# In service layer, within transaction:
async with db.begin():
    # 1. Perform business operation
    booking = await create_booking(...)

    # 2. Write event to event_log table (same transaction)
    event = Event(
        event_type="BookingCreated",
        aggregate_id=booking.id,
        payload={...}
    )
    db.add(event)

# 3. Background worker reads event_log and publishes to NATS (JetStream subject)
# 4. NATS consumers send notifications, update reporting tables, etc.
```

**Message broker: NATS with JetStream**
- Dev: local NATS container in docker-compose (`nats://localhost:4222`)
- Prod: shared macmini NATS instance (`nats://macmini:4222`)
- JetStream provides persistent, at-least-once delivery (replaces RabbitMQ durable queues)
- Subjects follow pattern: `envmgr.events.<AggregateType>.<EventType>` (e.g., `envmgr.events.Booking.BookingCreated`); stream name: `ENVMGR_EVENTS`

**Event Consumers** (`backend/app/workers/`):
- **Notification consumer** — email and webhooks
- **Metrics consumer** — update reporting tables / DORA calculations

---

## 5. Database Design Patterns

### JSONB for Flexibility

Use JSONB columns for:
- Custom fields (user-defined metadata)
- Configuration data (varies by component type)
- Notification preferences
- Settings and options

Index JSONB columns with GIN indexes for query performance.

### Soft Deletes

All entities use `deleted_at: Mapped[Optional[datetime]]`. Never hard delete records (audit trail requirement). Always filter `deleted_at IS NULL` in queries.

### Audit Trail

- Base model includes `created_at` and `updated_at`
- Change history tables track field-level changes
- Event log provides complete audit trail

---

## 6. Frontend Architecture

### State Management (Redux Toolkit)

```
frontend/src/store/
├── index.ts              # Store configuration
├── authSlice.ts          # Authentication state
├── environmentSlice.ts   # Environment state
├── bookingSlice.ts       # Booking state
└── ...
```

- Use Redux Toolkit's `createSlice` and `createAsyncThunk`
- API calls in async thunks, not in components
- Normalize state shape (avoid nested data)
- Use selectors for derived state

### Component Structure

```
frontend/src/
├── components/           # Reusable components
│   ├── BookingCalendar.tsx
│   ├── ComponentConfigEditor.tsx
│   └── ...
├── pages/               # Page-level components
│   ├── Dashboard.tsx
│   ├── EnvironmentList.tsx
│   └── ...
├── services/            # API client services
│   ├── api.ts           # Axios instance
│   ├── authService.ts
│   └── environmentService.ts
└── types/               # TypeScript type definitions
```

- Pages compose components
- Components are presentational (receive props)
- API calls in service layer, not components
- Use TypeScript interfaces for all props

---

## 7. GitHub-First Infrastructure Discovery

**Workflow**:
1. System entity links to GitHub repository (`github_repository_url`)
2. Background worker scans repository for:
   - Terraform files: `*.tf`, `*.tfstate`
   - Docker Compose files: `docker-compose.yml`, `docker-compose.*.yml`
3. Parsers extract infrastructure components:
   - Terraform → AWS/Azure/GCP resources
   - Docker Compose → containerized services
4. Components stored in PostgreSQL with source traceability
5. Topology served from PostgreSQL (`topology_service`); no graph store — see `decisions/2026-07-30-drop-neo4j.md`
6. Drift detection compares `.tf` vs `.tfstate`

**Fallback**: Manual file upload for systems without GitHub integration.

---

## 8. API Design Standards

### RESTful Conventions

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/environments/` | List (filtering, bounded — see below) |
| GET | `/api/v1/environments/{id}` | Get single |
| POST | `/api/v1/environments/` | Create |
| PUT | `/api/v1/environments/{id}` | Update (full) |
| PATCH | `/api/v1/environments/{id}` | Partial update |
| DELETE | `/api/v1/environments/{id}` | Soft delete |

### Response Format

List endpoints return a **bare JSON array**, not an envelope:

```json
[ { "id": 1, "name": "SIT-1" }, { "id": 2, "name": "UAT-1" } ]
```

The unwindowed total goes in an **`X-Total-Count`** response header, so a client can
tell the page is partial and walk it with `?offset=`. `limit` defaults to 500 and is
capped at 1000; exceeding the cap is a `422` rather than a silent clamp. Not every
list endpoint is bounded yet — [`pagination.md`](pagination.md) has the inventory and
the one endpoint that is blocked on a refactor.

> An earlier version of this document described an `{ data, items, total, page,
> page_size }` envelope and an error format with `error_code` and `context`. Neither
> was ever implemented. The formats below are what the API actually returns.

### Error Format

FastAPI's default shape:

```json
{ "detail": "Booking overlaps an existing exclusive booking" }
```

Validation errors carry FastAPI's structured `detail` array. Unhandled exceptions
return a correlatable 500 rather than a traceback:

```json
{ "detail": "Internal server error", "request_id": "9f2c…" }
```

### Status Code Conventions

| Code | Used for |
|------|----------|
| `401` | Not authenticated — absent, malformed or expired credentials |
| `403` | Authenticated but not permitted (wrong role, wrong tenant) |
| `404` | Absent, or present but invisible to this tenant |
| `422` | Request body or query parameter validation |
| `429` | Rate limited (sign-in attempts) — carries `Retry-After` |

`401` vs `403` matters to the frontend: `services/api.ts` treats `401` as "refresh
the session and retry", and only `401`.

---

## 9. Testing Strategy

919 backend tests, 120 frontend unit tests, Playwright E2E. CI
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs the backend suite
against **both** engines as a matrix, plus lint, build, image builds and dependency
audits.

### Layout

| Suite | Location | Run |
|---|---|---|
| Unit | `backend/tests/unit/` | `uv run pytest tests/unit/` |
| Service | `backend/tests/services/` | `uv run pytest tests/services/` |
| Integration | `backend/tests/integration/` | `uv run pytest tests/integration/` |
| Frontend unit | `frontend/src/**/__tests__/` | `npm run test -- --run` |
| E2E | `frontend/e2e/` | `npm run test:e2e` |

### Two engines, not one

The suite defaults to in-memory SQLite. Point it at PostgreSQL with
`TEST_DATABASE_URL` — CI does both:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest -q
```

This is not redundancy. Several migrations gate their DDL on
`if dialect.name != "postgresql": return`, so the partial unique indexes enforcing
tenant-scoped name uniqueness and membership state are **inert under SQLite** and a
SQLite-only run cannot exercise them.

On PostgreSQL the schema is built once per session and each test starts from
`TRUNCATE … RESTART IDENTITY CASCADE`. Schema setup and cleanup go through a *sync*
psycopg2 engine, because an asyncpg connection is bound to the event loop that opened
it and pytest-asyncio gives each test its own.

### Foreign keys are enforced on both

SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON` is set per connection.
It wasn't, so 41 tests were inserting rows pointing at ids that did not exist and
passing. The pragma is on now. **Never point a test row at a fabricated id** — use
the idempotent per-tenant helpers in `backend/tests/factories.py`.

### The migration drift guard

`backend/tests/test_migration_schema_drift.py` builds a throwaway database with
`alembic upgrade head` and diffs it against `Base.metadata`. Without it, a migration
that forgets a column passes every test while producing a broken database on a clean
deploy — which is exactly how six tables once shipped without their `created_at` /
`updated_at`. It **skips** when no PostgreSQL is reachable, so the CI job asserts it
did not skip.

### Transaction boundaries need `realistic_client`

The shared `client` fixture overrides `get_db` with a bare `yield`: it never commits
and never rolls back. Anything that depends on `get_db`'s real behaviour therefore
looks correct when it isn't — two security features were silently broken this way,
each writing a row and then raising the exception that rolled it back. Use the
`realistic_client` fixture in `tests/integration/test_auth.py`, whose override
mirrors production commit/rollback.

---

## 10. Lifecycle Configurability

Both **Bookings** and **Change Requests** support configurable state machines rather than hardcoded status enums.

**Design rules**:
- States and allowed transitions are stored in configuration (database table or config file), not in application code
- The service layer reads the lifecycle definition at runtime to validate transitions
- At minimum, one built-in lifecycle for each entity must include an approval step

**Minimum built-in lifecycles**:

| Entity | Default Lifecycle States |
|--------|--------------------------|
| Booking | `draft → submitted → approved \| rejected → cancelled` |
| Change Request | `draft → submitted → approved \| rejected → in_progress → completed \| cancelled` |

**Implementation pattern**:
```python
# LifecycleDefinition table stores allowed transitions per entity type
# Service validates before state change:
async def transition(entity, new_status, lifecycle_config):
    allowed = lifecycle_config.allowed_transitions(entity.status)
    if new_status not in allowed:
        raise InvalidTransitionError(entity.status, new_status)
    entity.status = new_status
```

**Key constraint**: a Booking or Change Request lifecycle must always include at least one path through an `approved` state. Lifecycles without approval are permitted as an option but not as the only option.

---

## 11. Deployment Architecture

### Overview

EnvManager is deployed as Docker containers orchestrated by docker-compose. Two environments exist:

| Environment | Host | Access |
|-------------|------|--------|
| **Development** | Developer laptop (OrbStack) | localhost |
| **Production** | macmini (Tailscale network) | `macmini` hostname |

Full macmini service map: [`architecture copy.md`](architecture%20copy.md)

---

### Development (OrbStack)

All services run locally via `docker-compose up -d`. OrbStack provides Docker Desktop compatibility and DNS resolution (`<container>.orb.local`) for inter-container networking.

**`docker-compose.yml` services (dev)**:

| Container | Image | Dev port | Profile | Purpose |
|-----------|-------|----------|---------|---------|
| `postgres` | `postgres:15-alpine` | 5432 | — | Application database |
| `redis` | `redis:7-alpine` | 6379 | — | Cache |
| `nats` | `nats:latest` | 4222 / 8222 | — | Event bus (JetStream) |
| `jira`, `jira-db` | — | 8090 | — | Dev/testing only |
| `gitlab`, `gitlab-runner` | — | 8929 / 2224 | — | Dev/testing only, legacy |
| `backend` | built from `backend/Dockerfile` | 8000 | `app` | FastAPI application |
| `frontend` | built from `frontend/Dockerfile` | 5173 → 8080 | `app` | nginx serving the built bundle |

`docker-compose up -d` starts infrastructure only. `backend` and `frontend` sit behind
the **`app` profile** so they do not claim ports 8000/5173 from the host-run uvicorn
and vite of the documented dev loop; start them with `docker compose --profile app up -d`.

The backend image also needs `backend/.env` (dev) or an explicit `SECRET_KEY`: with
`DEBUG=false` and the repo's placeholder key the app refuses to start.

Inter-container connection strings use Docker service names:
`postgresql+asyncpg://envmgr:…@postgres:5432/envmgr`, `nats://nats:4222`,
`redis://redis:6379`. The `+asyncpg` driver is required — the app builds an async
engine and rejects a bare `postgresql://` URL at startup.

---

### Production (macmini — Tailscale)

Some infrastructure is **shared** from macmini's existing service stack; EnvManager runs only its application-specific containers.

**Shared macmini services (no containers added by EnvManager)**:

| Service | Connection | Notes |
|---------|-----------|-------|
| NATS | `nats://macmini:4222` | JetStream enabled; use subject prefix `envmgr.` |
| Grafana | `http://macmini:3003` | Add EnvManager dashboard to existing Grafana |
| Prometheus | `http://macmini:9093` | Add EnvManager scrape target to existing Prometheus |

**EnvManager-owned prod containers**:

| Container | Prod port | Notes |
|-----------|-----------|-------|
| `db` (Postgres) | 5435 | Avoids conflict with Supabase (5432) and Langfuse (5433) |
| `redis` | 6379 | Own isolated Redis; not shared with macmini internal services |
| `backend` | 8100 | Avoids conflict with Supabase Kong (8000) |
| `frontend` | 5173 | Vite preview / Caddy-served static build |

**Prod docker-compose** uses a separate `docker-compose.prod.yml` (or override file) that:
- Removes the `nats` container
- Sets env vars pointing to macmini shared services
- Remaps `backend` port to 8100
- Remaps `db` port to 5435

**Environment variable differences (dev vs prod)**:

| Variable | Dev | Prod |
|----------|-----|------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:5432/envmgr` | `postgresql+asyncpg://postgres:5432/envmgr` (published on `localhost:5435`) |
| `NATS_URL` | `nats://nats:4222` | `nats://macmini:4222` |
| `REDIS_URL` | `redis://redis:6379` | `redis://localhost:6379` |

---

### No graph database

Neo4j was in the original design as the topology graph store and was provisioned in dev and
prod, but no backend module ever imported the driver. Topology shipped PostgreSQL-backed
(`topology_service`, `dependency_service`, the `system_dependency` / `component_dependency`
tables). It was removed 2026-07-30 — see
[`decisions/2026-07-30-drop-neo4j.md`](decisions/2026-07-30-drop-neo4j.md) for the reasoning,
the namespacing scheme that had been planned for the shared Community Edition instance, and how
to reinstate it if a Phase 6 traversal turns out to need one.

The Neo4j instance in the port table below is a **shared macmini host service** used by other
projects. It keeps running; EnvManager no longer connects to it.

---

### Port Reference (macmini with EnvManager deployed)

| Port | Service | Owner |
|------|---------|-------|
| 3000 | Open WebUI | macmini |
| 3001 | Flowise | macmini |
| 3002 | Langfuse | macmini |
| 3003 | Grafana | macmini |
| 4222 | NATS | macmini (shared) |
| 5173 | EnvManager Frontend | EnvManager |
| 5432 | Supabase Postgres | macmini |
| 5433 | Langfuse Postgres | macmini (localhost) |
| **5435** | **EnvManager Postgres** | **EnvManager** |
| 5678 | n8n | macmini |
| 6333 | Qdrant | macmini |
| **6379** | **EnvManager Redis** | **EnvManager** |
| 7474 | Neo4j Browser | macmini (shared — not used by EnvManager) |
| 7687 | Neo4j Bolt | macmini (shared — not used by EnvManager) |
| 8000 | Supabase Kong | macmini |
| 8080 | SearXNG | macmini |
| **8100** | **EnvManager Backend API** | **EnvManager** |
| 8222 | NATS Monitor | macmini |
| 9093 | Prometheus | macmini |
| 11434 | Ollama | macmini |

---

## 12. Authentication & Sessions

Implemented in `app/services/auth_session_service.py` and `app/core/security.py`.

```
POST /api/v1/auth/login    → { access_token, refresh_token, expires_in, user }
POST /api/v1/auth/refresh  → same shape; rotates the refresh token
POST /api/v1/auth/logout   → 204, revokes the presented refresh token
GET  /api/v1/auth/me       → current user
```

| | Lifetime | Form | Revocable |
|---|---|---|---|
| Access token | 15 min | JWT (HS256, PyJWT) | No — expires |
| Refresh token | 14 days | opaque `secrets.token_urlsafe(32)` | Yes — `refresh_token` row |
| Impersonation token | 60 min | JWT with `impersonating_tenant_id` | No — expires, no refresh |

**There is no self-service registration.** Users are created via
`POST /api/v1/tenant/users`, which requires a tenant admin and forces the caller's own
tenant. `/auth/register` existed once, unauthenticated and accepting a caller-supplied
`tenant_id` and `role`; it was removed.

### Design decisions worth knowing

- Refresh tokens are stored **only as a SHA-256**, so a database leak yields no live
  sessions. Plain SHA-256 rather than bcrypt: the token is 256 bits of `secrets`
  output, so there is no low-entropy guess to slow down.
- **Rotation on every refresh**, with replay of a spent token treated as theft — the
  whole family descended from that login is revoked, because the thief may hold a
  newer token than the one they replayed.
- Access tokens are **not** checked against a deny-list per request. That would add a
  lookup to every authenticated call to shorten a window that is already 15 minutes.
  Revocation acts on the refresh token; `revoke_all_for_user` covers the cases where
  waiting is unacceptable, and a master-admin password reset calls it.
- **`algorithms=[…]` is passed explicitly** to `jwt.decode`. Two tests pin that a
  token signed with another algorithm and a hand-crafted `alg=none` token are both
  rejected.
- Passwords are hashed with **bcrypt directly** (not passlib, unmaintained since
  2020). Input is truncated to 72 bytes, matching what passlib did silently, so
  existing long-password users can still sign in. `verify_password` returns `False`
  on a malformed stored hash rather than raising, so a corrupt row fails that login
  instead of 500-ing the endpoint.

### Rate limiting

Per-username **and** per-IP over a 15-minute window, in the `login_attempt` table.
Per-username alone would let an attacker walk a user list from one host. Checked
**before** the password is examined, so guessing correctly does not bypass the limit.
Returns `429` with `Retry-After`.

PostgreSQL rather than Redis: the limit then holds across replicas, survives a
restart, and is testable without a running Redis. Login is not a hot path.

---

## 13. Observability

Implemented in `app/core/observability.py`, installed by `install_observability(app)`.

- **Structured logging** — JSON when `DEBUG` is off, human-readable when on. Take a
  module logger (`logging.getLogger(__name__)`); the root logger is configured at
  import.
- **Request correlation** — `X-Request-ID` is accepted from the caller or generated,
  carried in a contextvar so every log line emitted during the request is stamped
  with it, and echoed on the response. Background workers log `-`.
- **Access log** with handler duration. `uvicorn.access` is quietened because it
  duplicates the line and cannot carry the request id; `/health` and `/metrics` are
  excluded, since a healthcheck every 30s per container buries everything else.
- **`GET /metrics`** — Prometheus exposition: `envmgr_http_requests_total`,
  `envmgr_http_request_duration_seconds`, `envmgr_unhandled_exceptions_total`.
  Path labels are built from the request path with parameter values substituted back
  out, *not* from `route.path` — that attribute is relative to the router prefix, so
  `/api/v1/auth/me` would be labelled `/me` and unrelated endpoints from different
  routers would collide on a bare `/{id}`.
- **Catch-all exception handler** returning `{ detail, request_id }`. The client gets
  something to quote; the traceback stays in the logs under the same id.
- **`nats-py` is silenced** — it logs a full traceback at ERROR for every reconnect
  attempt, which is a stack trace every two seconds while NATS is down. The event
  publisher reports connectivity itself, with backoff.

### Background worker supervision

The outbox publisher runs under a **lifespan** handler that holds the task reference
and cancels it on shutdown. `supervise_event_publisher` restarts it with backoff and
logs each restart at ERROR: launched bare, anything the worker did not catch killed
the task silently and the outbox stopped draining forever — invisible precisely
because the work is meant to be unseen.

Multiple replicas are safe: the publisher selects with `FOR UPDATE SKIP LOCKED`, so
each instance takes a disjoint batch.

---

## 14. Continuous Integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), on pull requests and
pushes to `main`.

| Job | What it does |
|---|---|
| `backend` (matrix: sqlite, postgres) | `uv sync --frozen`, then the suite against each engine. The postgres leg also asserts the migration drift guard **did not skip**, and runs the dependency audit |
| `frontend` | `npm ci`, lint, vitest, build — on **Node 24**, because the lockfile was generated by npm 11 and npm 10 rejects it |
| `images` | Builds both Dockerfiles with layer caching, and asserts no compose service publishes a container port twice |

That last check exists because **compose appends port lists across override files**:
without `!override`, `docker-compose.prod.yml` republished the base `5432` alongside
`5435`, recreating the exact conflict the remap exists to avoid.

The GitLab pipeline (`.gitlab-ci.yml`, [`gitlab-ci-setup.md`](gitlab-ci-setup.md)) is
**not** CI in the usual sense — it dogfoods EnvManager's own deployment-tracking
webhooks from a local runner. It is not the gate on `main`.
