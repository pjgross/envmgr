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
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # NATS
    NATS_URL: str = "nats://localhost:4222"
    
    # Security
    SECRET_KEY: str = INSECURE_DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    # Access tokens are short-lived now that refresh tokens exist; callers that
    # need a different life pass expires_delta explicitly. See
    # app/services/auth_session_service.py.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

    # Encrypts third-party credentials at rest. Separate from SECRET_KEY on
    # purpose. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SECRETS_ENCRYPTION_KEY: str = ""

    # OAuth App client id for the GitHub device flow. Device flow needs no
    # client secret, which is a large part of why it was chosen.
    GITHUB_OAUTH_CLIENT_ID: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 100
    
    # File Upload
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB

    # A repository with hundreds of .tf files would otherwise mean hundreds of
    # sequential API calls against a rate limit. Hitting this cap is reported,
    # never silent.
    MAX_SCAN_FILES: int = 200

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
