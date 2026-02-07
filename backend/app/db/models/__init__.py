# Import all models here for Alembic to detect them
from app.db.base import Base
from app.db.models.user import Tenant, User, CustomFieldDefinition

# This will be expanded as we add more models
__all__ = ["Base", "Tenant", "User", "CustomFieldDefinition"]
