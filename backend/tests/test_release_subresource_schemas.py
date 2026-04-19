import pytest
from app.api.v1.schemas.release_template import ReleaseTemplateCreate, ReleaseTemplateInstantiate
from app.api.v1.schemas.test_phase import TestPhaseCreate, TestPhaseRead
from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateDecision
from app.api.v1.schemas.release_system import ReleaseSystemCreate
from app.api.v1.schemas.release_dependency import ReleaseDependencyCreate, ReleaseDependencyAlert
from app.api.v1.schemas.release_event import ReleaseEventTypeCreate, ReleaseEventCreate
from app.api.v1.schemas.release_change import ReleaseChangeCreate


def test_schemas_all_importable():
    assert ReleaseTemplateCreate(name="x", release_type="Major").release_type == "Major"
    assert TestPhaseCreate(name="SIT").name == "SIT"
    assert ReleaseGateCreate(name="g").name == "g"
    assert ReleaseSystemCreate(system_id=1, role="changing").role == "changing"
    assert ReleaseDependencyCreate(depends_on_release_id=1).kind == "deploys_after"
    assert ReleaseEventCreate(event_type_id=1, description="ok").description == "ok"
    # ReleaseChangeCreate has no source_is_default_manual helper, just verify it constructs
    rc = ReleaseChangeCreate(title="t", change_kind="story")
    assert rc.title == "t"
    assert rc.change_kind == "story"
