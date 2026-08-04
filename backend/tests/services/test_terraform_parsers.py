"""Both Terraform parsers, as pure functions.

.tf declares resources with no computed values and no resource ids; .tfstate
records what was actually built. The two never produce identical rows, which
is why they carry different provenance and are never compared against each
other.
"""
import json

import pytest

from app.services.terraform_hcl_import_service import parse_terraform_hcl
from app.services.terraform_import_service import parse_tfstate

HCL = b"""
resource "aws_db_instance" "main" {
  allocated_storage = 20
}

resource "aws_lambda_function" "worker" {
  runtime = "python3.12"
}

variable "region" {
  default = "eu-west-2"
}

variable "tags" {
  default = { env = "prod" }
}
"""


def test_resource_blocks_become_declared_subsystems_addressed_as_terraform_does():
    declared = parse_terraform_hcl(HCL, "infra/main.tf")

    by_name = {s.name: s for s in declared.subsystems}
    assert set(by_name) == {"aws_db_instance.main", "aws_lambda_function.worker"}
    assert by_name["aws_db_instance.main"].component_type == "database"
    assert by_name["aws_lambda_function.worker"].component_type == "worker"


def test_non_resource_blocks_are_not_inventoried():
    """variable, output, provider and locals are not infrastructure.

    The `tags` variable in the fixture is what makes this discriminate. hcl2
    parses every block into the same {key: {name: body}} shape, so a variable
    whose default is a MAP is structurally indistinguishable from a resource —
    it would be inventoried as `tags.default` with no warning at all. A
    variable with a scalar default cannot show that: its body is a string, so
    it trips the missing-name-label guard by accident and the test passes for
    a reason unrelated to what it claims to check.
    """
    declared = parse_terraform_hcl(HCL, "infra/main.tf")
    assert not any("region" in s.name for s in declared.subsystems)
    assert not any("tags" in s.name for s in declared.subsystems)


def test_hcl_declares_no_edges():
    """HCL dependency wiring is implicit in interpolations, which this does not
    read. Declaring zero edges is honest; guessing would not be."""
    assert parse_terraform_hcl(HCL, "infra/main.tf").edges == []


def test_the_declaring_path_is_recorded():
    declared = parse_terraform_hcl(HCL, "infra/modules/db/main.tf")
    assert {s.source_path for s in declared.subsystems} == {"infra/modules/db/main.tf"}


def test_a_resource_block_missing_its_name_label_is_warned_about_not_invented():
    """Without the guard the resource's own attributes parse as names, so one
    bogus subsystem per attribute is created while the scan reports success."""
    content = b'resource "aws_db_instance" {\n  allocated_storage = 20\n}\n'
    declared = parse_terraform_hcl(content, "main.tf")
    assert declared.subsystems == []
    assert any("name label" in w for w in declared.warnings)


def test_an_empty_file_declares_nothing_rather_than_raising():
    assert parse_terraform_hcl(b"   \n", "empty.tf").subsystems == []


def test_invalid_hcl_raises_value_error():
    with pytest.raises(ValueError, match="Invalid Terraform HCL"):
        parse_terraform_hcl(b'resource "x" {{{ unclosed', "main.tf")


def test_tfstate_managed_resources_become_declared_subsystems():
    state = json.dumps({
        "resources": [
            {"mode": "managed", "type": "aws_db_instance", "name": "main"},
            {"mode": "data", "type": "aws_ami", "name": "ubuntu"},
        ]
    }).encode()

    declared = parse_tfstate(state, "terraform.tfstate")

    assert [s.name for s in declared.subsystems] == ["aws_db_instance.main"]


def test_tfstate_data_sources_are_skipped():
    """A data source is something Terraform reads, not something it manages."""
    state = json.dumps({
        "resources": [{"mode": "data", "type": "aws_ami", "name": "ubuntu"}]
    }).encode()
    assert parse_tfstate(state, "terraform.tfstate").subsystems == []


def test_invalid_tfstate_json_raises_value_error():
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_tfstate(b"{not json", "terraform.tfstate")
