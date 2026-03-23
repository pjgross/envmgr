# Import all models here for Alembic to detect them
from app.db.base import Base
from app.db.models.user import Tenant, User, CustomFieldDefinition
from app.db.models.system import System, SubSystem
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.dependency import SystemDependency, ComponentDependency
from app.db.models.booking import Booking, BookingType, BookingStatus, ContextTag
from app.db.models.version import EnvironmentSubSystemVersion
from app.db.models.event_log import EventLog

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
    "SystemDependency",
    "ComponentDependency",
    "Booking",
    "BookingType",
    "BookingStatus",
    "ContextTag",
    "EnvironmentSubSystemVersion",
    "EventLog",
]
