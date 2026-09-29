"""Ruling R13: every runbook route must take its session through
`Depends(get_db, scope="function")`, so the write commits BEFORE the response
is sent. A route that drops the scope silently reverts to "request" scope,
where get_db's commit runs after the bytes are on the wire and a client's next
read can race it (browser-pass finding B2). Nothing else would notice: every
behavioural test still passes on a request-scoped session.

Only the route's OWN (direct) dependencies are checked. `get_current_user`
opens its own request-scoped, read-only session by design — see the comment
above `_db` in app/api/v1/runbooks.py."""
from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.api.v1 import runbooks
from app.db.base import get_db


def _unscoped_db_routes(router: APIRouter) -> list[str]:
    bad = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        db_deps = [d for d in route.dependant.dependencies if d.call is get_db]
        if not db_deps or any(d.scope != "function" for d in db_deps):
            bad.append(f"{sorted(route.methods)} {route.path}")
    return bad


def test_every_runbook_route_takes_a_function_scoped_session():
    routes = [r for r in runbooks.router.routes if isinstance(r, APIRoute)]
    assert len(routes) >= 11, "the sweep found fewer routes than the router declares"
    assert _unscoped_db_routes(runbooks.router) == []


def test_the_sweep_flags_a_route_with_a_request_scoped_session():
    """The check itself discriminates: a bare Depends(get_db) is caught."""
    probe = APIRouter()

    @probe.get("/scoped")
    async def scoped(db=Depends(get_db, scope="function")):
        return None

    @probe.get("/bare")
    async def bare(db=Depends(get_db)):
        return None

    assert _unscoped_db_routes(probe) == ["['GET'] /bare"]
