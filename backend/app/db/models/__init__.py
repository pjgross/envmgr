# Import all models here for Alembic to detect them
from app.db.base import Base
from app.db.models.user import Tenant, User, CustomFieldDefinition
from app.db.models.system import System, SubSystem
from app.db.models.environment import Environment, EnvironmentSystem

# This will be expanded as we add more models
__all__ = [
    "Base",
    "Tenant",
    "User",
    "CustomFieldDefinition",
    "System",
    "SubSystem",
    "Environment",
    "EnvironmentSystem",
]
