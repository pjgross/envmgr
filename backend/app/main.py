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

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(admin_router.router, prefix="/api/v1/admin", tags=["Master Admin"])
app.include_router(tenant_admin_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
app.include_router(tenant_admin_fields_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
app.include_router(systems_router.router, prefix="/api/v1/systems", tags=["Systems"])
app.include_router(environments_router.router, prefix="/api/v1/environments", tags=["Environments"])
app.include_router(dependencies_router.router, prefix="/api/v1", tags=["Dependencies"])
app.include_router(bookings_router.router, prefix="/api/v1/bookings", tags=["Bookings"])
app.include_router(import_router.router, prefix="/api/v1/import", tags=["Import"])
app.include_router(topology_router.router, prefix="/api/v1", tags=["Topology"])
app.include_router(booking_lifecycle_router.router, prefix="/api/v1/tenant", tags=["Booking Lifecycle"])
