"""build and deployment must be accepted entity_type values."""
import pytest
from pydantic import ValidationError

from app.api.v1.schemas.custom_field import CustomFieldDefinitionCreate


def test_build_entity_type_accepted():
    c = CustomFieldDefinitionCreate(
        entity_type="build", label="Scan ID", field_type="text",
    )
    assert c.entity_type == "build"


def test_deployment_entity_type_accepted():
    c = CustomFieldDefinitionCreate(
        entity_type="deployment", label="Blast Radius", field_type="text",
    )
    assert c.entity_type == "deployment"


def test_unknown_entity_type_rejected():
    with pytest.raises(ValidationError):
        CustomFieldDefinitionCreate(
            entity_type="not_a_thing", label="x", field_type="text",
        )
