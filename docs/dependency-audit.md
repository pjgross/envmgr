# Dependency Audit

Status: **clean** as of 2026-07-30, with two documented acceptances.

Both audits run in CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) and fail the
build on any advisory that is not explicitly accepted. Run them locally with:

```bash
cd backend  && uv run python scripts/audit_dependencies.py
cd frontend && npm run audit
```

They query OSV / `npm audit` directly rather than wrapping `pip-audit` — that tool builds a
throwaway venv via `ensurepip`, which dies with SIGABRT on this project's macOS toolchain.

---

## What the 2026-07-30 bump fixed

The pre-bump tree had 12 backend packages and 5 frontend packages with advisories, including
`python-jose` **in the request auth path**.

| Package | Was | Now | Cleared |
|---|---|---|---|
| `python-jose` | 3.3.0 | 3.5.0 | CVE-2024-33663 (algorithm confusion), CVE-2024-33664 (JWT bomb), CVE-2024-29370 |
| `starlette` | 0.35.1 | 1.3.1 | 7, incl. CVE-2024-47874 (multipart DoS), CVE-2025-54121 |
| `python-multipart` | 0.0.6 | 0.0.32 | 9, incl. CVE-2024-24762 (ReDoS), CVE-2024-53981 |
| `fastapi` | 0.109.0 | 0.141.1 | CVE-2024-24762 |
| `python-dotenv` | 1.0.0 | 1.2.2 | CVE-2026-28684 |
| `pytest` | 7.4.4 | 9.1.1 | CVE-2025-71176 |
| `alembic` | 1.13.1 | 1.18.5 | (moves `mako` past CVE-2026-41205 / -44307) |
| `uvicorn` | 0.27.0 | 0.52.0 | (moves `click` past CVE-2026-7246) |
| `react-router-dom` | 6.x | 7.18.2 | open redirect via backslash in `Link`/`useNavigate`, SSR `deserializeErrors` injection |
| `form-data`, `follow-redirects` | — | — | CRLF injection (high) + redirect leaks, via `npm audit fix` |

`pydantic` 2.5.3 → 2.13.4 and `pydantic-settings` 2.1.0 → 2.14.2 came along because
fastapi 0.141 requires `pydantic>=2.9`. Transitives (`cryptography`, `idna`, `pyasn1`,
`ecdsa`, `mako`, `click`) were refreshed with `uv lock --upgrade`.

`starlette` is now pinned as a **direct** dependency with an explicit `>=1.3.1` floor.
fastapi only asks for `>=0.46.0`, and *every* starlette 0.x release is affected by
CVE-2026-48710 / -48817 / -48818 / -54282 / -54283 — so relying on fastapi's floor would
allow a vulnerable resolution.

### Behaviour changes worth knowing

- **`HTTPBearer` now returns 401, not 403**, for absent or unparseable credentials. This is
  correct semantics (fastapi < 0.112 was wrong) and two tests asserted the old value. The
  frontend improves as a result: `services/api.ts` only clears the session on 401, so a
  corrupt token now logs the user out instead of stranding them on a 403.
- **`HTTP_422_UNPROCESSABLE_ENTITY` is deprecated** in favour of
  `HTTP_422_UNPROCESSABLE_CONTENT` (same value, 422). Renamed across 15 files.

---

## Accepted advisories

An advisory is only acceptable with a **reachability argument**. "No fixed version exists" is
not sufficient on its own.

### `ecdsa` — CVE-2024-23342 (Minerva timing attack)

Upstream **declined to fix**: constant-time operations are considered out of scope for a
pure-Python implementation. It reaches us as a hard dependency of `python-jose`.

Unreachable: `app/core/security.py` signs and verifies exclusively with **HS256** (HMAC) and
passes an explicit `algorithms=[settings.ALGORITHM]` allowlist to `jwt.decode`, so no ECDSA
code path is ever exercised. Two tests in `tests/unit/test_security.py` pin that confinement —
a token signed with another algorithm, and a hand-crafted `alg=none` token, must both be
rejected.

**To retire it properly:** migrate from `python-jose` to `PyJWT`, which has no `ecdsa`
dependency and is actively maintained. `python-jose` itself is close to dormant.

### `react-router` — GHSA-qwww-vcr4-c8h2 (RSC-mode CSRF bypass)

There is no clean release. Affected ranges overlap to cover everything currently published:

| Advisory | Affected | Reachable? |
|---|---|---|
| Open redirect via backslash in `Link`/`useNavigate` | ≤ 7.17.0 | **Yes** — this is the routing API the app uses |
| SSR `deserializeErrors` injection | ≤ 7.17.0 | No — client-only SPA |
| RSC-mode CSRF bypass | 7.12.0 – 8.2.0 | No — no React Server Components |

7.18.2 is therefore the right choice: it fixes the only reachable advisory. `npm audit`'s
suggested "fix" is a downgrade to 7.11.0, which would trade a reachable open redirect for an
unreachable RSC issue. Revisit once a release above 8.2.0 ships.

---

## Known-stale, no advisory

- **`passlib` 1.7.4** — last released 2020, effectively unmaintained. It breaks against
  `bcrypt>=4`, which is what the `bcrypt<4` pin exists for. No advisories, so the audit is
  quiet, but it is a dead dependency holding back another. Replacing it means calling `bcrypt`
  directly; stored hashes are compatible, so the migration is mechanical.
- ~~**`neo4j` 5.16.0 and `pika` 1.3.2**~~ — both **removed** 2026-07-30; neither was imported by
  any backend module. See [decisions/2026-07-30-drop-neo4j.md](decisions/2026-07-30-drop-neo4j.md).
