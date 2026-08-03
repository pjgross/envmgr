"""Detector path-matching pinned against a real repository's file list.

The unit tests in `test_scanning_registry.py` check hand-written paths, which
prove the regex does what its author meant. This file checks the same
detectors against the 59 real blob paths of
https://github.com/pjgross/local-ai-packaged, captured from the tree API — so
a regex change that looks harmless against invented examples has to survive a
layout somebody actually wrote.

It is the difference between "the pattern matches what I typed" and "the
pattern claims the right files in a repository that exists".
"""
import json
from pathlib import Path

import pytest

from app.services.scanning.detectors import DETECTORS

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "github_tree_local_ai_packaged.json"


def _paths() -> list[str]:
    return json.loads(_FIXTURE.read_text())["paths"]


def _claimed_by(name: str) -> set[str]:
    detector = next(d for d in DETECTORS if d.name == name)
    return {p for p in _paths() if detector.matches(p)}


def test_the_fixture_is_a_real_repository_layout():
    """Guards the fixture itself: an empty or truncated capture would make
    every assertion below vacuously true."""
    paths = _paths()
    assert len(paths) == 59
    assert "docker-compose.yml" in paths
    assert "supabase/pnpm-lock.yaml" in paths


def test_compose_claims_exactly_the_two_real_compose_files():
    assert _claimed_by("docker_compose") == {
        "docker-compose.yml",
        # Three levels down — the any-depth match, on a real layout rather
        # than an invented one.
        "supabase/docker/docker-compose.yml",
    }


def test_terraform_claims_nothing_in_a_repository_with_no_terraform():
    """A detector that claims files in a repo of the wrong technology would
    hand its parser content it cannot read."""
    assert _claimed_by("terraform_hcl") == set()


@pytest.mark.parametrize("path,why", [
    ("supabase/docker/dev/docker-compose.dev.yml",
     "an overlay fragment: merging onto a base, not a whole application"),
    ("supabase/docker/docker-compose.s3.yml",
     "an overlay fragment: merging onto a base, not a whole application"),
    ("supabase/pnpm-lock.yaml", "a lockfile that happens to be YAML"),
    ("supabase/pnpm-workspace.yaml", "a workspace file that happens to be YAML"),
    (".github/ISSUE_TEMPLATE/config.yml", "GitHub metadata, not infrastructure"),
    ("searxng/settings-base.yml", "application config, not infrastructure"),
])
def test_compose_skips_the_near_misses_this_repository_actually_contains(path, why):
    """Every one of these is a real file in the repository, and every one is a
    plausible false positive for a loosened pattern. The two overlay files are
    the case the exclusion was reasoned about before anyone had seen a repo
    that contained them."""
    assert path in _paths(), "fixture drifted — this path is no longer in the capture"
    assert _claimed_by("docker_compose").isdisjoint({path}), why


def test_no_detector_claims_a_file_no_detector_can_parse():
    """Whatever the detectors claim, between them they must not pull in a file
    outside the two technologies they support — a claimed path is fetched, and
    a fetch that cannot be parsed is a wasted API call against a rate limit."""
    claimed = set()
    for detector in DETECTORS:
        claimed |= {p for p in _paths() if detector.matches(p)}
    for path in claimed:
        assert path.endswith((".yml", ".yaml", ".tf")), path
