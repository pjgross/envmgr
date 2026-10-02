"""Every database session must commit BEFORE the response is sent.

FastAPI 0.121+ runs a yield-dependency's teardown — get_db's commit — after
the response bytes are on the wire unless the dependency is declared
`Depends(get_db, scope="function")`. With the default, a client receives
"201 Created" and its very next request can read pre-commit state: measured on
the dev server on 2026-10-02, 113 of 200 `POST /releases` → `GET /releases/{id}`
pairs got a 404 for the release just created. A failed commit was also
invisible to the client, which had already been told the write succeeded.

Nothing behavioural notices a request-scoped session — every test still
passes — so this sweep is the only guard. It walks the WHOLE dependency tree of
every route (get_current_user and api_key_auth take a session too), not just a
route's direct parameters."""
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.db.base import get_db
from app.main import app


def _db_dependants(dependant: Dependant):
    for sub in dependant.dependencies:
        if sub.call is get_db:
            yield sub
        yield from _db_dependants(sub)


def _api_routes(application: FastAPI | APIRouter):
    """FastAPI 0.141 keeps an included router as a lazy `_IncludedRouter` in
    `app.routes` rather than flattening its routes, so walk `original_router`.
    No router in this app declares include-time `dependencies=`, so each
    route's own dependant tree is complete."""
    for route in application.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router)


def _request_scoped_db_routes(application: FastAPI | APIRouter) -> list[str]:
    bad = []
    for route in _api_routes(application):
        if any(d.scope != "function" for d in _db_dependants(route.dependant)):
            bad.append(f"{sorted(route.methods)} {route.path}")
    return bad


def test_every_route_commits_before_the_response():
    routes = list(_api_routes(app))
    with_db = [r for r in routes if any(True for _ in _db_dependants(r.dependant))]
    assert len(with_db) > 300, "the sweep found far fewer database routes than the app declares"
    assert _request_scoped_db_routes(app) == []


def test_the_sweep_sees_through_nested_dependencies():
    """A bare Depends(get_db) is caught directly AND one level down."""
    async def current_user(db=Depends(get_db)):
        return None

    probe = APIRouter()

    @probe.get("/scoped")
    async def scoped(db=Depends(get_db, scope="function")):
        return None

    @probe.get("/bare")
    async def bare(db=Depends(get_db)):
        return None

    @probe.get("/nested")
    async def nested(user=Depends(current_user), db=Depends(get_db, scope="function")):
        return None

    assert _request_scoped_db_routes(probe) == ["['GET'] /bare", "['GET'] /nested"]
