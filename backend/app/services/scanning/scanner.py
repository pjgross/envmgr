"""Walk a repository once, hand matched files to the detectors that claimed them."""
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.github_client import (
    GitHubClient,
    GitHubNotFound,
    GitHubUnavailable,
    GitHubUnexpectedResponse,
)
from app.services.scanning.registry import Detector, DetectorResult, ParseContext

_REPO_URL = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+)")


def _transport() -> Optional[httpx.BaseTransport]:
    """Seam for tests; None means the real network."""
    return None


def get_detectors() -> list[Detector]:
    from app.services.scanning.detectors import DETECTORS
    return DETECTORS


@dataclass
class DetectorReport:
    detector: str
    paths: list[str] = field(default_factory=list)
    result: DetectorResult = field(default_factory=DetectorResult)
    errors: list[str] = field(default_factory=list)
    #: Paths this detector claimed that the file cap dropped before the fetch
    #: loop ever reached them. Without this, a detector starved by the cap
    #: looks identical to one that read everything and found nothing: e.g.
    #: 300 .tf files ahead of docker-compose.yml in tree order means Compose
    #: is never fetched, yet its report is all zeros with no error. A path
    #: whose *fetch* fails (as opposed to being dropped by the cap) is
    #: recorded in `errors` instead — see the per-path try/except below.
    paths_unread: int = 0


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


async def scan_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    owner, repo = parse_repo_url(repo_url)

    key = (tenant_id, system_id)
    if key in _in_flight:
        raise ScanAlreadyRunning("a scan of this system is already running")
    _in_flight.add(key)
    try:
        client = GitHubClient(token=token, transport=_transport())
        try:
            ref = await client.get_default_branch(owner, repo)
            tree = await client.get_tree(owner, repo, ref)

            detectors = get_detectors()
            reports = {d.name: DetectorReport(detector=d.name) for d in detectors}

            # A path goes to EVERY detector that claims it — "first match wins"
            # would make behaviour depend on registry order.
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
                    reports[detector.name].paths_unread += 1

            async def fetch(path: str) -> Optional[bytes]:
                try:
                    return await client.get_blob(owner, repo, path, ref)
                except Exception:
                    return None

            for path, wanted in claimed:
                try:
                    content = await client.get_blob(owner, repo, path, ref)
                except (GitHubNotFound, GitHubUnavailable, GitHubUnexpectedResponse) as exc:
                    # A transient 5xx, a 404 (the file existed in the tree but
                    # is gone by the time it's fetched), or a malformed body on
                    # ONE file must not abort the whole scan — that discards
                    # every write earlier detectors already made (the request
                    # rolls back) and blames "repository not found, or the
                    # token cannot see it" on a single-file hiccup. Record it
                    # against every detector that claimed this path and move
                    # on to the next one.
                    #
                    # GitHubAuthError and GitHubRateLimited are deliberately
                    # NOT caught here: a 401 means the token is dead for every
                    # remaining file too (not just this one) and must still
                    # reach the endpoint's cleanup in systems.py, and a 429
                    # means every subsequent call would fail the same way —
                    # continuing would just burn through the rest of the tree
                    # collecting the same error per path.
                    for detector in wanted:
                        reports[detector.name].errors.append(f"{path}: {exc}")
                    continue
                for detector in wanted:
                    report = reports[detector.name]
                    report.paths.append(path)
                    try:
                        # Each detector writes inside its own SAVEPOINT. Without this a
                        # failed flush — an IntegrityError from a duplicate name, say —
                        # marks the whole session for rollback, and the NEXT use of the
                        # session raises PendingRollbackError: one detector's failure
                        # would erase every other detector's results at commit time.
                        async with db.begin_nested():
                            parsed = await detector.parse(
                                ParseContext(
                                    content=content, path=path, system_id=system_id,
                                    tenant_id=tenant_id, db=db, fetch=fetch,
                                )
                            )
                        report.result = report.result + parsed
                    except Exception as exc:
                        # One detector failing must not take the others with it.
                        report.errors.append(f"{path}: {exc}")

            return {
                "ref": ref,
                "files_scanned": len(claimed),
                "truncated": tree.truncated,
                "stopped_early": stopped_early,
                "detectors": [
                    {
                        "detector": r.detector,
                        "paths": r.paths,
                        "subsystems_created": r.result.subsystems_created,
                        "subsystems_updated": r.result.subsystems_updated,
                        "dependencies_written": r.result.dependencies_written,
                        "warnings": r.result.warnings,
                        "errors": r.errors,
                        "paths_unread": r.paths_unread,
                    }
                    for r in reports.values()
                ],
            }
        finally:
            # GitHubClient holds one pooled httpx client for its lifetime; a
            # scan that raises must still release it, or every failed scan
            # leaks a connection pool.
            try:
                await client.aclose()
            except Exception:
                # Never let a close failure replace the exception that is
                # already propagating: the endpoint dispatches on that type,
                # and losing it means a revoked token is never cleared.
                pass
    finally:
        _in_flight.discard(key)
