# Import all models here for Alembic to detect them
from app.db.base import Base
from app.db.models.user import Tenant, User
from app.db.models.custom_field import CustomFieldDefinition
from app.db.models.component_type import ComponentTypeDefinition
from app.db.models.system import System, SubSystem
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.dependency import SystemDependency, ComponentDependency
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_lifecycle import (
    BookingType,
    BookingStatusHistory,
)
from app.db.models.version import EnvironmentSubSystemVersion
from app.db.models.event_log import EventLog

# This will be expanded as we add more models
__all__ = [
    "Base",
    "Tenant",
    "User",
    "CustomFieldDefinition",
    "ComponentTypeDefinition",
    "System",
    "SubSystem",
    "Environment",
    "EnvironmentSystem",
    "SystemDependency",
    "ComponentDependency",
    "Booking",
    "ContextTag",
    "BookingRequest",
    "BookingConflictAck",
    "LifecycleTemplate",
    "BookingType",
    "BookingStatusHistory",
    "EnvironmentSubSystemVersion",
    "EventLog",
]
