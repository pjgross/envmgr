# EnvManager

A comprehensive test environment management platform for booking, tracking, and visualizing test environments with DORA metrics and infrastructure topology.

## Features

- **Environment Inventory**: Catalog test environments with metadata and ownership
- **Shared Booking System**: Coordinate environment usage across projects
- **Multi-Project Coordination**: Define usage agreements between teams
- **Change Management**: Track planned changes with approval workflows
- **Release Management**: Link bookings to releases with test phases
- **Deployment Tracking**: Monitor CI/CD deployments
- **DORA Metrics**: Calculate and report DevOps performance indicators
- **Infrastructure Topology**: Visualize cloud architecture with interactive diagrams
- **Multi-Tenant**: Support multiple organizations with data isolation

## Technology Stack

- **Backend**: FastAPI (Python 3.11+), PostgreSQL 15+, Neo4j 5+, Redis, RabbitMQ
- **Frontend**: React 18+ with TypeScript, Material-UI, React Flow
- **Development**: Docker Compose

## Quick Start

### Prerequisites

- Docker Desktop (for Mac)
- Python 3.11+
- Node.js 18+

### Development Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd envmgr
```

2. Start the development environment:
```bash
docker-compose up -d
```

3. Initialize the database:
```bash
cd backend
python -m alembic upgrade head
```

4. Start the backend:
```bash
cd backend
uvicorn app.main:app --reload
```

5. Start the frontend:
```bash
cd frontend
npm install
npm run dev
```

6. Access the application:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

## Project Structure

```
envmgr/
├── backend/          # FastAPI backend
│   ├── app/
│   │   ├── api/      # API endpoints
│   │   ├── core/     # Config, security, events
│   │   ├── db/       # Database models & migrations
│   │   ├── services/ # Business logic
│   │   └── workers/  # Event consumers
│   └── tests/
├── frontend/         # React frontend
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── services/
│       └── store/
├── docs/             # Documentation
├── templates/        # Excel import templates
└── docker-compose.yml
```

## Documentation

- [Implementation Plan](docs/implementation_plan.md)
- [Excel Import Templates](docs/excel_templates_spec.md)
- [API Documentation](http://localhost:8000/docs) (when running)

## License

Proprietary - All rights reserved
