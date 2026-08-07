import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.observability import configure_logging, install_observability
from app.db.base import init_db
from app.workers.event_publisher import supervise_event_publisher

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown.

    Replaces the deprecated @app.on_event hooks, and — unlike the previous bare
    create_task — holds a reference to the background task and cancels it on
    shutdown so it cannot outlive the app or be garbage-collected mid-flight.
    """
    await init_db()
    publisher = asyncio.create_task(
        supervise_event_publisher(), name="event-publisher"
    )
    logger.info("%s %s started", settings.APP_NAME, settings.APP_VERSION)
    try:
        yield
    finally:
        publisher.cancel()
        try:
            await publisher
        except asyncio.CancelledError:
            pass
        logger.info("%s shut down", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Test Environment Management Platform",
    lifespan=lifespan,
)

install_observability(app)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


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
from app.api.v1 import environment_tiers as environment_tiers_router
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
from app.api.v1 import environment_operating_hours as environment_operating_hours_router
app.include_router(environment_operating_hours_router.router, prefix="/api/v1")

app.include_router(environments_router.router, prefix="/api/v1/environments", tags=["Environments"])
app.include_router(
    environment_tiers_router.router,
    prefix="/api/v1/environment-tiers",
    tags=["Environment Tiers"],
)
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

# PIR router (registered before releases wildcard routes to avoid path shadowing)
from app.api.v1 import pir as pir_router
app.include_router(pir_router.router, prefix="/api/v1")

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

from app.api.v1 import integrations_github as integrations_github_router

app.include_router(integrations_github_router.router, prefix="/api/v1")

from app.api.v1 import user_groups as user_groups_router

app.include_router(
    # Its own tag, not "Tenant Admin": three of its five endpoints are reads
    # open to any tenant member (see app/api/v1/user_groups.py), not admin-only.
    user_groups_router.router, prefix="/api/v1/tenant", tags=["User Groups"]
)

from app.api.v1 import environment_requests as environment_requests_router

app.include_router(
    environment_requests_router.router,
    prefix="/api/v1/environment-requests",
    tags=["Environment Requests"],
)

from app.api.v1 import projects as projects_router

app.include_router(projects_router.router, prefix="/api/v1/projects", tags=["Projects"])
