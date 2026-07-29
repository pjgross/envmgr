from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import Optional


# The key shipped in this repo. It is a sentinel, not a secret: a deployment
# running with it outside DEBUG is rejected at startup rather than signing
# tokens anyone with the source can forge.
INSECURE_DEV_SECRET_KEY = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "EnvManager"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr"
    
    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "envmgr_dev_password"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # NATS
    NATS_URL: str = "nats://localhost:4222"
    
    # Security
    SECRET_KEY: str = INSECURE_DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 100
    
    # File Upload
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    @model_validator(mode="after")
    def _reject_insecure_secret_key(self) -> "Settings":
        if not self.DEBUG and self.SECRET_KEY == INSECURE_DEV_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the value shipped in the repository. Set a "
                "real SECRET_KEY (e.g. `openssl rand -hex 32`) for any non-DEBUG "
                "deployment — JWTs signed with the shipped key are forgeable by "
                "anyone with the source. Set DEBUG=true for local development."
            )
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
