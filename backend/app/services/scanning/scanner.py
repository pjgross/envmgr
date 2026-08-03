"""Walk a repository once, hand matched files to the detectors that claimed them."""
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.github_client import (
    GitHubClient,
    GitHubNotFound,
    GitHubUnavailable,
    GitHubUnexpectedResponse,
)
from app.services.scanning import reconcile
from app.services.scanning.declared import DeclaredState
from app.services.scanning.reconcile import ApplyResult
from app.services.scanning.registry import Detector, ParseContext

_REPO_URL = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+)")


def _transport() -> Optional[httpx.BaseTransport]:
    """Seam for tests; None means the real network."""
    return None


def get_detectors() -> list[Detector]:
    from app.services.scanning.detectors import DETECTORS
    return DETECTORS


def parse_repo_url(url: Optional[str]) -> tuple[str, str]:
    match = _REPO_URL.search(url or "")
    if not match:
        raise ValueError(
            f"could not read an owner/repo from the system's GitHub URL: {url!r}"
        )
    return match.group(1), match.group(2)


#: Systems with a scan in flight. In-process only, which is honest for a
#: single-process deployment: it stops the double-click and the impatient
#: second tab, not a second replica. A distributed lock would need Redis and
#: is not warranted until the app runs more than one worker.
_in_flight: set[tuple[int, int]] = set()


class ScanAlreadyRunning(RuntimeError):
    pass


@dataclass
class DetectorWalk:
    detector: Detector
    paths: list[str] = field(default_factory=list)
    declared: DeclaredState = field(default_factory=DeclaredState)
    errors: list[str] = field(default_factory=list)
    #: Paths this detector claimed that the file cap dropped before the fetch
    #: loop reached them. Without this, a detector starved by the cap looks
    #: identical to one that read everything and found nothing: 300 .tf files
    #: ahead of docker-compose.yml in tree order means Compose is never
    #: fetched, yet its report is all zeros with no error.
    paths_unread: int = 0


@dataclass
class WalkResult:
    ref: str
    files_scanned: int
    truncated: bool
    stopped_early: bool
    walks: list[DetectorWalk]


def absence_is_computable(
    walk: DetectorWalk, *, truncated: bool, stopped_early: bool
) -> tuple[bool, Optional[str]]:
    """Whether "in the catalogue but not in the code" can be trusted.

    Positive findings survive a partial read; absence findings do not. A file
    that was never read is indistinguishable from one that was deleted, so
    when any part of this detector's input went unseen the absence categories
    are left uncomputed rather than computed wrong.
    """
    if truncated:
        return False, (
            "GitHub returned only a partial listing of this repository's file "
            "tree, so files it never listed cannot be told apart from deleted "
            "ones."
        )
    if stopped_early:
        return False, (
            "The scan stopped at its file limit, so files it never read cannot "
            "be told apart from deleted ones."
        )
    if walk.paths_unread:
        return False, (
            f"{walk.paths_unread} matching file(s) were not read, so they cannot "
            "be told apart from deleted ones."
        )
    if walk.errors:
        return False, (
            "Some matching files could not be fetched, so they cannot be told "
            "apart from deleted ones."
        )
    return True, None


async def _walk(client: GitHubClient, owner: str, repo: str) -> WalkResult:
    """Read the repository once and parse everything the detectors claim.

    Touches no database: both the scan and the drift report run this and then
    do their own thing with the result.
    """
    ref = await client.get_default_branch(owner, repo)
    tree = await client.get_tree(owner, repo, ref)

    detectors = get_detectors()
    walks = {d.name: DetectorWalk(detector=d) for d in detectors}

    # A path goes to EVERY detector that claims it — "first match wins" would
    # make behaviour depend on registry order.
    claimed: list[tuple[str, list[Detector]]] = []
    for path in tree.paths:
        wanted = [d for d in detectors if d.matches(path)]
        if wanted:
            claimed.append((path, wanted))

    stopped_early = len(claimed) > settings.MAX_SCAN_FILES
    dropped, claimed = (
        claimed[settings.MAX_SCAN_FILES:],
        claimed[: settings.MAX_SCAN_FILES],
    )
    for _, wanted in dropped:
        for detector in wanted:
            walks[detector.name].paths_unread += 1

    async def fetch(path: str) -> Optional[bytes]:
        try:
            return await client.get_blob(owner, repo, path, ref)
        except Exception:
            return None

    for path, wanted in claimed:
        try:
            content = await client.get_blob(owner, repo, path, ref)
        except (GitHubNotFound, GitHubUnavailable, GitHubUnexpectedResponse) as exc:
            # A transient 5xx, a 404, or a malformed body on ONE file must not
            # abort the whole walk. GitHubAuthError and GitHubRateLimited are
            # deliberately NOT caught: a 401 is dead for every remaining file
            # and must reach the endpoint's cleanup, and a 429 means every
            # subsequent call fails the same way.
            for detector in wanted:
                walks[detector.name].errors.append(f"{path}: {exc}")
            continue
        for detector in wanted:
            walk = walks[detector.name]
            walk.paths.append(path)
            try:
                walk.declared = walk.declared + await detector.parse(
                    ParseContext(content=content, path=path, fetch=fetch)
                )
            except Exception as exc:
                # One detector failing must not take the others with it.
                walk.errors.append(f"{path}: {exc}")

    return WalkResult(
        ref=ref,
        files_scanned=len(claimed),
        truncated=tree.truncated,
        stopped_early=stopped_early,
        walks=list(walks.values()),
    )


@asynccontextmanager
async def _locked_scan(*, system_id: int, tenant_id: int) -> AsyncIterator[None]:
    """Hold the per-system in-flight marker for an entire scan or drift
    report — the network-bound walk AND whatever the caller does with its
    result — not just the walk.

    A marker released as soon as the walk returns would let a second request
    pass the in-flight check while the first request's database writes are
    still in progress: two `reconcile.apply` calls are check-then-act over
    `catalogue()`, and there is no unique constraint on
    (name, system_id, tenant_id) to catch them interleaving — the loser
    silently disappears from both `apply()` and `diff()`. The forthcoming
    drift report needs this too: comparing against a catalogue a concurrent
    scan is mutating reports differences that exist on neither side.
    """
    key = (tenant_id, system_id)
    if key in _in_flight:
        raise ScanAlreadyRunning("a scan of this system is already running")
    _in_flight.add(key)
    try:
        yield
    finally:
        _in_flight.discard(key)


async def _walk_repository(*, token: str, repo_url: str) -> WalkResult:
    """Open a GitHubClient, run the shared walk, and close the client.

    Takes no lock and no session: callers hold `_locked_scan` around this and
    do their own thing — apply, diff — with the result.
    """
    owner, repo = parse_repo_url(repo_url)
    client = GitHubClient(token=token, transport=_transport())
    try:
        return await _walk(client, owner, repo)
    finally:
        # GitHubClient holds one pooled httpx client for its lifetime; a walk
        # that raises must still release it, or every failure leaks a
        # connection pool. Never let a close failure replace the exception
        # already propagating — the endpoint dispatches on that type, and
        # losing it means a revoked token is never cleared.
        try:
            await client.aclose()
        except Exception:
            pass


async def scan_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    async with _locked_scan(system_id=system_id, tenant_id=tenant_id):
        walk_result = await _walk_repository(token=token, repo_url=repo_url)

        detectors_out = []
        for walk in walk_result.walks:
            applied = ApplyResult()
            errors = list(walk.errors)
            if walk.declared.subsystems or walk.declared.edges:
                try:
                    # Each detector writes inside its own SAVEPOINT. Without it
                    # a failed flush marks the whole session for rollback, and
                    # the next use raises PendingRollbackError: one detector's
                    # failure would erase every other detector's results at
                    # commit time.
                    async with db.begin_nested():
                        applied = await reconcile.apply(
                            db,
                            system_id=system_id,
                            tenant_id=tenant_id,
                            source=walk.detector.subsystem_source,
                            edge_source=walk.detector.edge_source,
                            declared=walk.declared,
                        )
                except Exception as exc:
                    errors.append(str(exc))
            detectors_out.append({
                "detector": walk.detector.name,
                "paths": walk.paths,
                "subsystems_created": applied.subsystems_created,
                "subsystems_updated": applied.subsystems_updated,
                "dependencies_written": applied.dependencies_written,
                "warnings": walk.declared.warnings,
                "errors": errors,
                "paths_unread": walk.paths_unread,
            })

        return {
            "ref": walk_result.ref,
            "files_scanned": walk_result.files_scanned,
            "truncated": walk_result.truncated,
            "stopped_early": walk_result.stopped_early,
            "detectors": detectors_out,
        }


async def drift_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    """Report where the catalogue and the repository disagree. Writes nothing.

    Shares the scan's lock: comparing against a catalogue a concurrent scan is
    mutating would report differences that exist on neither side.
    """
    async with _locked_scan(system_id=system_id, tenant_id=tenant_id):
        walk_result = await _walk_repository(token=token, repo_url=repo_url)

        detectors_out = []
        for walk in walk_result.walks:
            absence_computed, absence_reason = absence_is_computable(
                walk,
                truncated=walk_result.truncated,
                stopped_early=walk_result.stopped_early,
            )
            report = await reconcile.diff(
                db,
                system_id=system_id,
                tenant_id=tenant_id,
                source=walk.detector.subsystem_source,
                edge_source=walk.detector.edge_source,
                declared=walk.declared,
                absence_computed=absence_computed,
                absence_reason=absence_reason,
            )
            detectors_out.append({
                "detector": walk.detector.name,
                "paths": walk.paths,
                "paths_unread": walk.paths_unread,
                "errors": walk.errors,
                "warnings": report.warnings,
                "absence_computed": report.absence_computed,
                "absence_reason": report.absence_reason,
                "has_drift": report.has_drift,
                "subsystems": {
                    "missing_in_catalogue": [
                        {
                            "name": s.name,
                            "component_type": s.component_type,
                            "technology": s.technology,
                            "source_path": s.source_path,
                        }
                        for s in report.subsystems_missing_in_catalogue
                    ],
                    # None, never [] — "we checked and found nothing missing" and
                    # "we could not check" are opposite conclusions.
                    "missing_in_code": report.subsystems_missing_in_code,
                    "changed": [
                        {
                            "name": c.name,
                            "field": c.field,
                            "catalogue": c.catalogue,
                            "declared": c.declared,
                            "source_path": c.source_path,
                        }
                        for c in report.subsystems_changed
                    ],
                },
                "edges": {
                    "missing_in_catalogue": [
                        {
                            "from_name": e.from_name,
                            "to_name": e.to_name,
                            "port": e.port,
                            "source_path": e.source_path,
                        }
                        for e in report.edges_missing_in_catalogue
                    ],
                    "missing_in_code": None if report.edges_missing_in_code is None else [
                        {"from_name": e.from_name, "to_name": e.to_name, "port": e.port}
                        for e in report.edges_missing_in_code
                    ],
                    "changed": [
                        {
                            "from_name": c.from_name,
                            "to_name": c.to_name,
                            "catalogue_port": c.catalogue_port,
                            "declared_port": c.declared_port,
                            "source_path": c.source_path,
                        }
                        for c in report.edges_changed
                    ],
                },
            })

        return {
            "ref": walk_result.ref,
            "files_scanned": walk_result.files_scanned,
            "truncated": walk_result.truncated,
            "stopped_early": walk_result.stopped_early,
            "has_drift": any(d["has_drift"] for d in detectors_out),
            "detectors": detectors_out,
        }
