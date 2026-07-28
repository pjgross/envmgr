import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import init_db
from app.workers.event_publisher import run_event_publisher


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Test Environment Management Platform",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup and launch background workers."""
    await init_db()
    asyncio.create_task(run_event_publisher())


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Import and include routers
from app.api.v1 import api_keys as api_keys_router
from app.api.v1 import auth
from app.api.v1 import admin as admin_router
from app.api.v1 import tenant_admin as tenant_admin_router
from app.api.v1 import tenant_admin_fields as tenant_admin_fields_router
from app.api.v1 import systems as systems_router
from app.api.v1 import environments as environments_router
from app.api.v1 import dependencies as dependencies_router
from app.api.v1 import bookings as bookings_router
from app.api.v1 import import_routes as import_router
from app.api.v1 import topology as topology_router
from app.api.v1 import booking_lifecycle as booking_lifecycle_router
from app.api.v1 import component_types as component_types_router
from app.api.v1 import booking_requests as booking_requests_router
from app.api.v1 import conflicts as conflicts_router
from app.api.v1 import change_requests as change_requests_router
from app.api.v1 import infrastructure_components as infrastructure_components_router
from app.api.v1 import releases as releases_router
from app.api.v1 import raid as raid_router
from app.api.v1 import release_templates as release_templates_router
from app.api.v1 import release_event_types as release_event_types_router
from app.api.v1 import gate_criteria as gate_criteria_api
from app.api.v1 import enterprise_memberships as enterprise_memberships_router
from app.api.v1 import enterprise_rollup as enterprise_rollup_router
from app.api.v1.webhooks import deployment as webhook_deployment_router
from app.api.v1.webhooks import can_deploy as webhook_can_deploy_router

app.include_router(api_keys_router.router, prefix="/api/v1/api-keys", tags=["api-keys"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(admin_router.router, prefix="/api/v1/admin", tags=["Master Admin"])
app.include_router(tenant_admin_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
app.include_router(tenant_admin_fields_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
app.include_router(systems_router.router, prefix="/api/v1/systems", tags=["Systems"])

# Health router must be mounted BEFORE environments_router to prevent
# /environments/{env_id} from shadowing /environments/health (literal vs int param).
from app.api.v1 import environment_health as environment_health_router
app.include_router(environment_health_router.router, prefix="/api/v1")

app.include_router(environments_router.router, prefix="/api/v1/environments", tags=["Environments"])
app.include_router(dependencies_router.router, prefix="/api/v1", tags=["Dependencies"])
app.include_router(bookings_router.router, prefix="/api/v1/bookings", tags=["Bookings"])
app.include_router(import_router.router, prefix="/api/v1/import", tags=["Import"])
app.include_router(topology_router.router, prefix="/api/v1", tags=["Topology"])
app.include_router(booking_lifecycle_router.router, prefix="/api/v1/tenant", tags=["Booking Lifecycle"])
app.include_router(component_types_router.router, prefix="/api/v1/component-types", tags=["Component Types"])
app.include_router(booking_requests_router.router, prefix="/api/v1")
app.include_router(conflicts_router.router, prefix="/api/v1")
app.include_router(change_requests_router.router, prefix="/api/v1")
app.include_router(
    infrastructure_components_router.router,
    prefix="/api/v1/infrastructure-components",
    tags=["Infrastructure"],
)

# Enterprise rollup + report (registered before releases wildcard routes to avoid shadowing)
app.include_router(
    enterprise_rollup_router.router, prefix="/api/v1", tags=["enterprise-rollup"]
)

# Enterprise membership (registered before releases wildcard routes to avoid shadowing)
app.include_router(
    enterprise_memberships_router.router, prefix="/api/v1", tags=["enterprise-memberships"]
)

# Releases (main router + sub-resource routers)
app.include_router(releases_router.router, prefix="/api/v1")
app.include_router(releases_router.phases_router, prefix="/api/v1")
app.include_router(releases_router.gates_router, prefix="/api/v1")
app.include_router(releases_router.release_systems_router, prefix="/api/v1")
app.include_router(releases_router.release_deps_router, prefix="/api/v1")
app.include_router(releases_router.release_changes_router, prefix="/api/v1")
app.include_router(release_templates_router.router, prefix="/api/v1")
app.include_router(release_event_types_router.router, prefix="/api/v1")
app.include_router(gate_criteria_api.release_sub_router, prefix="/api/v1")
app.include_router(gate_criteria_api.router, prefix="/api/v1")
app.include_router(raid_router.router, prefix="/api/v1")

app.include_router(
    webhook_deployment_router.router,
    prefix="/api/v1/webhooks",
    tags=["webhooks"],
)
app.include_router(
    webhook_can_deploy_router.router,
    prefix="/api/v1/webhooks",
    tags=["webhooks"],
)

from app.api.v1 import builds as builds_router

app.include_router(builds_router.router, prefix="/api/v1/builds", tags=["builds"])

from app.api.v1 import deployments as deployments_router

app.include_router(deployments_router.router, prefix="/api/v1/deployments", tags=["deployments"])
app.include_router(deployments_router.env_sub_router, prefix="/api/v1/environments", tags=["deployments"])

from app.api.v1 import incidents as incidents_router

app.include_router(incidents_router.router, prefix="/api/v1")

from app.api.v1 import metrics as metrics_router

app.include_router(metrics_router.router, prefix="/api/v1")
