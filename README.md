# EnvManager

A test environment management platform for booking, tracking and visualising test environments, with release governance, DORA metrics and infrastructure topology.

## Features

- **Environment Inventory**: Catalog test environments with metadata, ownership and operating hours
- **Shared Booking System**: Coordinate environment usage across projects, with conflict detection
- **Release Management**: Releases with test phases, gates, scope tracking and a RAID log
- **Change Management**: Track planned changes with approval workflows and outage windows
- **Deployment Tracking**: Record builds and deployments from any CI via webhook, with a pre-deploy preflight check
- **DORA Metrics**: Deployment frequency, lead time, change failure rate and MTTR
- **Incidents & PIR**: Incident tracking with post-incident reviews
- **Environment Health & Utilisation**: Status history and DST-correct utilisation against operating hours
- **Infrastructure Topology**: Interactive dependency diagrams (React Flow + ELK)
- **Multi-Tenant**: Multiple organisations with enforced data isolation

## Technology Stack

- **Backend**: FastAPI, Python 3.12+, PostgreSQL 15+, Redis, NATS (JetStream)
- **Frontend**: React 18, TypeScript, Material-UI, Redux Toolkit, React Flow
- **Tooling**: `uv` (Python), Node 24 / npm 11, Docker Compose on OrbStack (macOS)
- **CI**: GitHub Actions — [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

There is no graph database. Neo4j was in the original design as the topology store and was provisioned, but never used; topology is PostgreSQL-backed. See [`docs/decisions/2026-07-30-drop-neo4j.md`](docs/decisions/2026-07-30-drop-neo4j.md).

## Quick Start

### Prerequisites

- [OrbStack](https://orbstack.dev) (preferred on macOS) or Docker Desktop
- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- Node 24+ (npm 11 — `package-lock.json` is not readable by npm 10)

### Setup

```bash
./setup.sh
```

Starts the infrastructure containers, creates `backend/.env`, installs dependencies, migrates the database and seeds a demo tenant.

<details>
<summary>Manual equivalent</summary>

```bash
# 1. Infrastructure (PostgreSQL, Redis, NATS)
docker-compose up -d

# 2. Backend env — DEBUG=true is what permits the repo's placeholder SECRET_KEY.
#    Without a .env the backend refuses to start.
cd backend && cp .env.example .env

# 3. Dependencies and schema
uv sync
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed_master_admin.py

# 4. Backend
uv run uvicorn app.main:app --reload

# 5. Frontend (new terminal)
cd frontend && npm ci && npm run dev
```

</details>

### Dev Services

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:5173 | Vite dev server |
| Backend API | http://localhost:8000 | FastAPI |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Metrics | http://localhost:8000/metrics | Prometheus exposition |
| NATS Monitor | http://localhost:8222 | Message broker |
| PostgreSQL | localhost:5432 | Direct DB access |
| Redis | localhost:6379 | Cache |
| Jira | http://localhost:8090 | Dev/testing only |
| GitLab | http://localhost:8929 | Dev/testing only — legacy, CI is GitHub Actions |

Demo login: `admin` / `admin123` (tenant: `demo`)

Master admin login: `masteradmin` / `masteradmin123` (tenant: `system`)
Seed on first run: `cd backend && PYTHONPATH=. uv run python scripts/seed_master_admin.py`

## Tests

```bash
cd backend  && SECRET_KEY=dev uv run pytest -q            # 919 tests, in-memory SQLite
cd frontend && npm run lint && npm run test -- --run      # 120 tests
cd frontend && npm run test:e2e                           # Playwright
```

The backend suite also runs against PostgreSQL, and **CI runs both engines**. Several migrations gate their DDL on the dialect, so a SQLite-only run cannot exercise them:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest -q
```

Dependency advisories are gated too — see [`docs/dependency-audit.md`](docs/dependency-audit.md):

```bash
cd backend  && uv run python scripts/audit_dependencies.py
cd frontend && npm run audit
```

## Admin Management

| Role | Tenant | Capabilities |
|---|---|---|
| **Master Admin** | `system` | Create/disable tenants, manage users in any tenant, sign in as any tenant |
| **Tenant Admin** | own tenant | Manage tenant settings and users within their own tenant |

Master admins can use **Sign In As** from the Platform Admin page for an impersonation token scoped to any tenant. Those tokens last 60 minutes and cannot be refreshed.

There is no self-service registration. Users are created through `POST /api/v1/tenant/users`, which requires a tenant admin and forces the caller's own tenant.

### Sessions

A 15-minute access token plus a 14-day refresh token that rotates on every use. Signing out revokes the session server-side, and a password reset revokes every session for that user. Five failed sign-ins for a username within 15 minutes returns `429` until the window passes.

## Production Deployment

Production runs on **macmini** (Tailscale network) with a compose override that disables dev-only services, points NATS at the shared host instance, and remaps ports to avoid conflicts.

```bash
SECRET_KEY=$(openssl rand -hex 32) POSTGRES_PASSWORD=... \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    --profile app up -d --build
```

- `backend` and `frontend` live under the compose **`app` profile**, so `docker-compose up -d` for dev infrastructure doesn't claim ports 8000/5173 from host-run uvicorn and vite.
- `SECRET_KEY` and `POSTGRES_PASSWORD` are **required** — compose fails fast without them, and the backend refuses to start with `DEBUG=false` and the repo's placeholder key.
- The backend image's entrypoint runs `alembic upgrade head` **before** uvicorn. That order matters: `init_db()` calls `create_all`, so an app-first boot on an empty database would build the schema itself and leave `alembic_version` empty, after which every migration fails. `RUN_MIGRATIONS=0` opts out.
- The frontend image is nginx serving the built bundle and proxying `/api` to `BACKEND_ORIGIN`.

| Service | Dev port | Prod port | Notes |
|---------|----------|-----------|-------|
| Backend API | 8000 | 8100 | Avoids Supabase Kong (8000) |
| Frontend | 5173 | 5173 → 8080 | nginx in the container |
| PostgreSQL | 5432 | 5435 | Avoids Supabase (5432), Langfuse (5433) |
| NATS | local container | `nats://macmini:4222` | Shared from macmini |

See [`docker-compose.prod.yml`](docker-compose.prod.yml) and [`docs/prod architecture.md`](docs/prod%20architecture.md).

## Project Structure

```
envmgr/
├── .github/workflows/    # CI (pytest on both engines, lint, build, images)
├── backend/
│   ├── app/
│   │   ├── api/v1/       # Endpoints (thin — delegate to services)
│   │   ├── core/         # Config, security, pagination, observability, events
│   │   ├── db/           # Models & Alembic migrations
│   │   ├── services/     # Business logic
│   │   └── workers/      # Outbox publisher (NATS)
│   ├── scripts/          # Seeds, dependency audit
│   ├── tests/            # unit / services / integration + factories
│   ├── Dockerfile
│   └── docker-entrypoint.sh
├── frontend/
│   ├── src/              # components, pages, services, store
│   ├── e2e/              # Playwright
│   ├── Dockerfile
│   └── nginx.conf
├── docs/
├── templates/            # Excel import templates
├── docker-compose.yml
└── docker-compose.prod.yml
```

## Documentation

**Start here**
- [Architecture Reference](docs/prod%20architecture.md) — layers, multi-tenancy, events, deployment
- [Project Roadmap](docs/plan.md) — phase status
- [CLAUDE.md](CLAUDE.md) — conventions, pitfalls, quick reference

**Guides**
- [Admin Guide](docs/admin-guide.md) · [User Guide](docs/user-guide.md)
- [CI/CD deployment tracking setup](docs/gitlab-ci-setup.md)

**Reference**
- [Requirements](docs/requirements.md) · [Gap Analysis](docs/gap-analysis.md)
- [Dependency Audit](docs/dependency-audit.md) · [Pagination](docs/pagination.md) · [UI Audit](docs/ui-audit.md)
- [Decisions](docs/decisions/) · [Phase summaries](docs/phases/)
- [API docs](http://localhost:8000/docs) (when running)

## License

Proprietary — All rights reserved
