"""`X-Total-Count` must be readable by JavaScript.

`allow_headers=["*"]` governs *request* headers; it does not expose response
headers to the browser. Nothing is broken today because the bundle is served
same-origin with the API, but the whole frontend now depends on reading this
header, and the failure mode if the origins are ever split is a grid that
believes the total equals the current page length.
"""
from app.main import app


def test_cors_exposes_the_total_count_header():
    cors = [m for m in app.user_middleware if "CORSMiddleware" in str(m)]
    assert cors, "CORSMiddleware is not installed"
    assert "X-Total-Count" in cors[0].kwargs["expose_headers"]
