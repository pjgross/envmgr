from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import init_db


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
    """Initialize database on startup."""
    await init_db()


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

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])

# Additional routers will be added as features are built
# from app.api.v1 import environments, bookings
# app.include_router(environments.router, prefix="/api/v1/environments", tags=["environments"])
# app.include_router(bookings.router, prefix="/api/v1/bookings", tags=["bookings"])
