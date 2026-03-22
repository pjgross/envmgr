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
│  - Repositories       │  │  - Neo4j, Redis, NATS  │
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
- Return consistent response formats

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
- Enforce row-level security (PostgreSQL RLS policies — Phase 1)

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
# 4. NATS consumers update Neo4j, send notifications, etc.
```

**Message broker: NATS with JetStream**
- Dev: local NATS container in docker-compose (`nats://localhost:4222`)
- Prod: shared macmini NATS instance (`nats://macmini:4222`)
- JetStream provides persistent, at-least-once delivery (replaces RabbitMQ durable queues)
- Subjects follow pattern: `envmgr.<event_type>` (e.g., `envmgr.BookingCreated`)

**Event Consumers** (`backend/app/workers/`):
- **Neo4j sync consumer** — update topology graph (subscribes to entity change events)
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
5. Topology projected to Neo4j for graph queries
6. Drift detection compares `.tf` vs `.tfstate`

**Fallback**: Manual file upload for systems without GitHub integration.

---

## 8. API Design Standards

### RESTful Conventions

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/environments` | List (with pagination, filtering) |
| GET | `/api/v1/environments/{id}` | Get single |
| POST | `/api/v1/environments` | Create |
| PUT | `/api/v1/environments/{id}` | Update (full) |
| PATCH | `/api/v1/environments/{id}` | Partial update |
| DELETE | `/api/v1/environments/{id}` | Soft delete |

### Response Format

```json
{
  "data": { },
  "items": [ ],
  "total": 100,
  "page": 1,
  "page_size": 50
}
```

### Error Format

```json
{
  "detail": "Error message",
  "error_code": "BOOKING_CONFLICT",
  "context": { }
}
```

---

## 9. Testing Strategy

### Unit Tests
- Service layer business logic (80%+ coverage target)
- Pure functions and utilities
- Run: `pytest backend/tests/unit/`

### Integration Tests
- API endpoints with test database
- Database operations
- Run: `pytest backend/tests/integration/`

### E2E Tests
- Critical user flows with Playwright
- Example: Create environment → Create booking → Approve booking
- Run: `npm run test:e2e` (frontend)

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

| Container | Image | Dev port | Purpose |
|-----------|-------|----------|---------|
| `db` | `postgres:16` | 5432 | Application database |
| `neo4j` | `neo4j:5-community` | 7474 / 7687 | Graph store (topology) |
| `redis` | `redis:7-alpine` | 6379 | Cache + metrics queue |
| `nats` | `nats:latest` | 4222 / 8222 | Event bus (JetStream enabled) |
| `backend` | (built locally) | 8000 | FastAPI application |
| `frontend` | (built locally) | 5173 | React dev server |

Start: `docker-compose up -d`

Inter-container connection strings use Docker service names: `postgresql://db:5432/envmgr`, `bolt://neo4j:7687`, `nats://nats:4222`, `redis://redis:6379`.

---

### Production (macmini — Tailscale)

Some infrastructure is **shared** from macmini's existing service stack; EnvManager runs only its application-specific containers.

**Shared macmini services (no containers added by EnvManager)**:

| Service | Connection | Notes |
|---------|-----------|-------|
| Neo4j | `bolt://macmini:7687` | Community Edition — see Neo4j note below |
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
- Removes `neo4j` and `nats` containers
- Sets env vars pointing to macmini shared services
- Remaps `backend` port to 8100
- Remaps `db` port to 5435

**Environment variable differences (dev vs prod)**:

| Variable | Dev | Prod |
|----------|-----|------|
| `DATABASE_URL` | `postgresql://db:5432/envmgr` | `postgresql://localhost:5435/envmgr` |
| `NEO4J_URI` | `bolt://neo4j:7687` | `bolt://macmini:7687` |
| `NATS_URL` | `nats://nats:4222` | `nats://macmini:4222` |
| `REDIS_URL` | `redis://redis:6379` | `redis://localhost:6379` |

---

### Neo4j Community Edition — Namespacing

macmini runs Neo4j **Community Edition**, which supports only a single database (`neo4j`). EnvManager namespaces its data using a dedicated label prefix to avoid collisions with other users of the instance:

- All EnvManager nodes carry the label `EnvMgr` in addition to their entity label: e.g., `:EnvMgr:System`, `:EnvMgr:Environment`
- All EnvManager relationships use the type prefix convention: `ENVMGR_DEPENDS_ON`, `ENVMGR_DEPLOYED_IN`
- Queries always include the `EnvMgr` label to scope to EnvManager data only

If the macmini Neo4j instance is upgraded to **Enterprise Edition**, EnvManager can use a dedicated named database (`envmgr`) and drop the label prefixes.

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
| 7474 | Neo4j Browser | macmini (shared) |
| 7687 | Neo4j Bolt | macmini (shared) |
| 8000 | Supabase Kong | macmini |
| 8080 | SearXNG | macmini |
| **8100** | **EnvManager Backend API** | **EnvManager** |
| 8222 | NATS Monitor | macmini |
| 9093 | Prometheus | macmini |
| 11434 | Ollama | macmini |
