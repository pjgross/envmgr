# EnvManager

A comprehensive test environment management platform for booking, tracking, and visualizing test environments with DORA metrics and infrastructure topology.

## Features

- **Environment Inventory**: Catalog test environments with metadata and ownership
- **Shared Booking System**: Coordinate environment usage across projects
- **Multi-Project Coordination**: Define usage agreements between teams
- **Change Management**: Track planned changes with approval workflows
- **Release Management**: Link bookings to releases with test phases
- **Deployment Tracking**: Monitor CI/CD deployments via GitHub Actions
- **DORA Metrics**: Calculate and report DevOps performance indicators
- **Infrastructure Topology**: Visualize system dependencies with interactive diagrams
- **Multi-Tenant**: Support multiple organizations with data isolation

## Technology Stack

- **Backend**: FastAPI (Python 3.11+), PostgreSQL 15+, Neo4j 5+, Redis, NATS (JetStream)
- **Frontend**: React 18+ with TypeScript, Material-UI, React Flow
- **Development**: Docker Compose on OrbStack (macOS)

## Quick Start

### Prerequisites

- [OrbStack](https://orbstack.dev) (preferred on macOS) or Docker Desktop
- Python 3.11+
- Node.js 18+

### Automated Setup

The quickest way to get started:

```bash
./setup.sh
```

This starts all Docker services, initializes the database, installs dependencies, and seeds demo data.

### Manual Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd envmgr
```

2. Start the infrastructure (PostgreSQL, Neo4j, Redis, NATS):
```bash
docker-compose up -d
```

3. Initialize the database:
```bash
cd backend
uv sync
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed_master_admin.py
```

4. Start the backend:
```bash
uv run uvicorn app.main:app --reload
```

5. Start the frontend (new terminal):
```bash
cd frontend
npm install
npm run dev
```

### Dev Services

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:5173 | Vite dev server |
| Backend API | http://localhost:8000 | FastAPI |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Neo4j Browser | http://localhost:7474 | Graph DB UI |
| NATS Monitor | http://localhost:8222 | Message broker |
| PostgreSQL | localhost:5432 | Direct DB access |
| Redis | localhost:6379 | Cache |
| Jira | http://localhost:8090 | Dev/testing only |
| GitLab | http://localhost:8929 | Dev/testing only |

Demo login: `admin` / `admin123` (tenant: `demo`)

Master admin login: `masteradmin` / `masteradmin123` (tenant: `system`)
Seed on first run: `cd backend && PYTHONPATH=. uv run python scripts/seed_master_admin.py`

## Admin Management

EnvManager has two admin tiers:

| Role | Tenant | Capabilities |
|---|---|---|
| **Master Admin** | `system` | Create/disable tenants, manage users in any tenant, sign in as any tenant |
| **Tenant Admin** | own tenant | Manage tenant settings and users within their own tenant |

Master admins can use **Sign In As** from the Platform Admin page to get an impersonation token scoped to any tenant — useful for support and testing.

## Production Deployment

Production runs on **macmini** (Tailscale network) using a compose override that disables locally-managed services (Neo4j, NATS) in favour of shared macmini host services and remaps ports to avoid conflicts with other services on the host.

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

| Service | Dev port | Prod port | Notes |
|---------|----------|-----------|-------|
| Backend API | 8000 | 8100 | Avoids Supabase Kong (8000) |
| PostgreSQL | 5432 | 5435 | Avoids Supabase (5432), Langfuse (5433) |
| Neo4j | local container | `bolt://macmini:7687` | Shared from macmini |
| NATS | local container | `nats://macmini:4222` | Shared from macmini |

See [`docker-compose.prod.yml`](docker-compose.prod.yml) for the full override and [`docs/prod architecture.md`](docs/prod%20architecture.md) for the complete deployment reference.

## Project Structure

```
envmgr/
├── backend/          # FastAPI backend
│   ├── app/
│   │   ├── api/      # API endpoints
│   │   ├── core/     # Config, security, events
│   │   ├── db/       # Database models & migrations
│   │   ├── services/ # Business logic
│   │   └── workers/  # Event consumers (NATS)
│   └── tests/
├── frontend/         # React frontend
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── services/
│       └── store/
├── docs/             # Documentation
├── templates/        # Excel import templates
├── docker-compose.yml
└── docker-compose.prod.yml
```

## Documentation

- [Project Roadmap](docs/plan.md)
- [Requirements](docs/requirements.md)
- [Current Phase Tasks](docs/phases/phase-1.md)
- [Architecture Reference](docs/prod%20architecture.md)
- [API Documentation](http://localhost:8000/docs) (when running)

## License

Proprietary - All rights reserved
