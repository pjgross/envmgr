# Import all models here for Alembic to detect them
from app.db.base import Base
from app.db.models.user import Tenant, User
from app.db.models.custom_field import CustomFieldDefinition
from app.db.models.component_type import ComponentTypeDefinition
from app.db.models.system import System, SubSystem
from app.db.models.environment import (
    Environment,
    EnvironmentSystem,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
)
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentSource,
    InfrastructureComponentType,
)
from app.db.models.dependency import SystemDependency, ComponentDependency
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_lifecycle import (
    BookingType,
    BookingStatusHistory,
)
from app.db.models.environment_tier import EnvironmentTier  # noqa: F401
from app.db.models.change_request import (
    ChangeRequest,
    ChangeRequestEnvironment,
    ChangeRequestHost,
    ChangeHistory,
    ChangeType,
)
from app.db.models.version import EnvironmentSubSystemVersion
from app.db.models.event_log import EventLog
from app.db.models.release_template import ReleaseTemplate
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.test_phase import TestPhase
from app.db.models.release_gate import ReleaseGate
from app.db.models.gate_criterion import GateCriterion
from app.db.models.release_system import ReleaseSystem
from app.db.models.release_dependency import ReleaseDependency
from app.db.models.release_event import ReleaseEventType, ReleaseEvent
from app.db.models.release_change import ReleaseChange
from app.db.models.release_change_history import (
    ReleaseChangeReleaseHistory,
    ReleaseChangeStatusHistory,
)
from app.db.models.scope_change_kind_rule import ScopeChangeKindRule
from app.db.models.api_key import ApiKey
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.raid import (
    RaidItem,
    RaidConfig,
    RaidItemScopeLink,
    RaidItemRelation,
    RaidItemHistory,
)
from app.db.models.incident import Incident, IncidentStatusHistory  # noqa: F401
from app.db.models.environment_health import EnvironmentHealthStatus  # noqa: F401
from app.db.models.environment_operating_hours import EnvironmentOperatingHours  # noqa: F401
from app.db.models.pir import PIR  # noqa: F401
from app.db.models.release_membership import ReleaseMembership  # noqa: F401
from app.db.models.refresh_token import LoginAttempt, RefreshToken  # noqa: F401
from app.db.models.tenant_secret import TenantSecret  # noqa: F401
from app.db.models.user_group import UserGroup, UserGroupMember  # noqa: F401
from app.db.models.environment_request import EnvironmentRequest  # noqa: F401
from app.db.models.project import Project, UsageAgreement  # noqa: F401
from app.db.models.usage_agreement_ack import UsageAgreementAck  # noqa: F401
from app.db.models.environment_group import (  # noqa: F401
    EnvironmentGroup,
    EnvironmentGroupMember,
)
from app.db.models.contention_escalation import ContentionEscalation  # noqa: F401
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy  # noqa: F401
from app.db.models.environment_decommission import (  # noqa: F401
    EnvironmentDecommission,
    EnvironmentDecommissionAttestation,
    EnvironmentDecommissionStep,
)
from app.db.models.environment_lifecycle_policy import EnvironmentLifecyclePolicy  # noqa: F401
from app.db.models.gate_type import GateType  # noqa: F401
from app.db.models.gate_evidence import GateEvidence  # noqa: F401
from app.db.models.gate_waiver import GateWaiver  # noqa: F401
from app.db.models.rollback import (  # noqa: F401
    ReleaseRollbackPlan,
    ReleaseRollbackAuthorisation,
    RollbackRehearsal,
    RollbackPolicy,
)

# This will be expanded as we add more models
__all__ = [
    "Base",
    "ApiKey",
    "Build",
    "Deployment",
    "Tenant",
    "User",
    "CustomFieldDefinition",
    "ComponentTypeDefinition",
    "System",
    "SubSystem",
    "Environment",
    "EnvironmentSystem",
    "EnvironmentSubSystem",
    "EnvironmentSubSystemHost",
    "InfrastructureComponent",
    "InfrastructureComponentSource",
    "InfrastructureComponentType",
    "SystemDependency",
    "ComponentDependency",
    "Booking",
    "ContextTag",
    "BookingRequest",
    "BookingConflictAck",
    "LifecycleTemplate",
    "BookingType",
    "BookingStatusHistory",
    "ChangeRequest",
    "ChangeRequestEnvironment",
    "ChangeRequestHost",
    "ChangeHistory",
    "ChangeType",
    "EnvironmentSubSystemVersion",
    "EventLog",
    "ReleaseTemplate",
    "Release",
    "ReleaseStatusHistory",
    "TestPhase",
    "ReleaseGate",
    "GateCriterion",
    "ReleaseSystem",
    "ReleaseDependency",
    "ReleaseEventType",
    "ReleaseEvent",
    "ReleaseChange",
    "ReleaseChangeReleaseHistory",
    "ReleaseChangeStatusHistory",
    "ScopeChangeKindRule",
    "RaidItem",
    "RaidConfig",
    "RaidItemScopeLink",
    "RaidItemRelation",
    "RaidItemHistory",
    "Incident",
    "IncidentStatusHistory",
    "EnvironmentHealthStatus",
    "EnvironmentOperatingHours",
    "PIR",
]
