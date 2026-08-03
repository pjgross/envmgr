"""The detector registry.

Adding a technology must be a module plus a list entry, and must not be able
to disturb detectors that already work.
"""
import pytest

from app.services.scanning.registry import DetectorResult, ParseContext
from app.services.scanning.detectors import DETECTORS
from app.services.scanning.detectors.compose import DOCKER_COMPOSE


@pytest.mark.parametrize("path", [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "deploy/docker-compose.yml",
    "a/b/c/compose.yaml",
])
def test_compose_claims_compose_files_at_any_depth(path):
    assert DOCKER_COMPOSE.matches(path) is True


@pytest.mark.parametrize("path", [
    "main.tf",
    "README.md",
    "docker-compose.yml.bak",
    "not-compose.yml",
    "composer.json",
])
def test_compose_does_not_claim_unrelated_files(path):
    assert DOCKER_COMPOSE.matches(path) is False


@pytest.mark.parametrize("path", [
    "docker-compose.override.yml",
    "docker-compose.prod.yml",
    "compose.override.yaml",
])
def test_compose_does_not_claim_override_fragments(path):
    """Not an oversight: an override merges onto a base file, and parsing it
    alone would import a partial service list as the whole application."""
    assert DOCKER_COMPOSE.matches(path) is False


def test_every_registered_detector_has_a_unique_name():
    names = [d.name for d in DETECTORS]
    assert len(names) == len(set(names))


def test_detector_result_totals_are_addable():
    """The scan sums results across detectors without knowing what any did."""
    a = DetectorResult(subsystems_created=1, subsystems_updated=2, dependencies_written=3)
    b = DetectorResult(subsystems_created=10, subsystems_updated=20, dependencies_written=30)
    total = a + b
    assert (total.subsystems_created, total.subsystems_updated, total.dependencies_written) == (
        11, 22, 33
    )


def test_warnings_survive_addition():
    a = DetectorResult(warnings=["a"])
    b = DetectorResult(warnings=["b"])
    assert (a + b).warnings == ["a", "b"]


def test_terraform_claims_tf_files_only():
    from app.services.scanning.detectors.terraform_hcl import TERRAFORM_HCL

    assert TERRAFORM_HCL.matches("main.tf") is True
    assert TERRAFORM_HCL.matches("infra/modules/vpc/main.tf") is True
    assert TERRAFORM_HCL.matches("terraform.tfstate") is False
    assert TERRAFORM_HCL.matches("notes.txt") is False
    # .tfvars is configuration, not resource declarations.
    assert TERRAFORM_HCL.matches("prod.tfvars") is False


def test_adding_a_detector_did_not_disturb_the_existing_one():
    """The extensibility claim, asserted rather than assumed."""
    from app.services.scanning.detectors import DETECTORS

    names = [d.name for d in DETECTORS]
    assert "docker_compose" in names and "terraform_hcl" in names
    compose = next(d for d in DETECTORS if d.name == "docker_compose")
    assert compose.matches("docker-compose.yml") is True
    assert compose.matches("main.tf") is False
