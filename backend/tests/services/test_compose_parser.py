"""Parsing a compose file is now a pure function — no database at all.

That is the whole point of the split: the drift report needs the declared
services as a value it can compare, and a parser that writes as it goes never
produces one.
"""
import pytest

from app.services.docker_compose_import_service import parse_docker_compose

COMPOSE = b"""
services:
  api:
    image: nginx:1.25
    ports:
      - "8080:80"
    depends_on:
      - db
  db:
    image: postgres:15
"""


def test_services_become_declared_subsystems():
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    by_name = {s.name: s for s in declared.subsystems}
    assert set(by_name) == {"api", "db"}
    assert by_name["db"].component_type == "database"
    assert by_name["db"].technology == "postgres"
    assert by_name["api"].component_type == "api_gateway"


def test_every_declaration_records_the_path_that_declared_it():
    declared = parse_docker_compose(COMPOSE, "deploy/docker-compose.yml")
    assert {s.source_path for s in declared.subsystems} == {"deploy/docker-compose.yml"}


def test_depends_on_becomes_an_edge_carrying_the_published_port():
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    assert len(declared.edges) == 1
    edge = declared.edges[0]
    assert (edge.from_name, edge.to_name) == ("api", "db")
    assert edge.port == 80


def test_depends_on_accepts_the_long_form_with_conditions():
    content = b"""
services:
  api:
    image: nginx
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres
"""
    declared = parse_docker_compose(content, "docker-compose.yml")
    assert [(e.from_name, e.to_name) for e in declared.edges] == [("api", "db")]


def test_a_long_service_name_is_truncated_to_the_column_width():
    """PostgreSQL raises on an over-length value where SQLite silently stores
    it. Truncating here rather than in apply() also keeps a stored row equal to
    the declaration it came from, so diff() does not report a phantom change."""
    long_name = "x" * 250
    content = f"services:\n  {long_name}:\n    image: nginx\n".encode()
    declared = parse_docker_compose(content, "docker-compose.yml")
    assert len(declared.subsystems[0].name) == 200


def test_invalid_yaml_raises_value_error():
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_docker_compose(b"services: [unclosed", "docker-compose.yml")


def test_a_file_with_no_services_raises_value_error():
    with pytest.raises(ValueError, match="No services"):
        parse_docker_compose(b"version: '3'\n", "docker-compose.yml")
