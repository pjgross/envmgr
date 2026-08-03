"""Walk a repository once, hand matched files to the detectors that claimed them."""
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.github_client import GitHubClient
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
            claimed = claimed[: settings.MAX_SCAN_FILES]

            async def fetch(path: str) -> Optional[bytes]:
                try:
                    return await client.get_blob(owner, repo, path, ref)
                except Exception:
                    return None

            for path, wanted in claimed:
                content = await client.get_blob(owner, repo, path, ref)
                for detector in wanted:
                    report = reports[detector.name]
                    report.paths.append(path)
                    try:
                        report.result = report.result + await detector.parse(
                            ParseContext(
                                content=content, path=path, system_id=system_id,
                                tenant_id=tenant_id, db=db, fetch=fetch,
                            )
                        )
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
                    }
                    for r in reports.values()
                ],
            }
        finally:
            # GitHubClient holds one pooled httpx client for its lifetime; a
            # scan that raises must still release it, or every failed scan
            # leaks a connection pool.
            await client.aclose()
    finally:
        _in_flight.discard(key)
