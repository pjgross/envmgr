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

### ~~`ecdsa` — CVE-2024-23342~~ — retired 2026-07-30

Was accepted as unreachable (unfixable upstream, reached only via `python-jose`, and
`security.py` is HS256-only). **Now moot**: `python-jose` was replaced with `PyJWT`, which has
no `ecdsa` dependency, so the package is gone along with `rsa` and `pyasn1`. The allowlist
entry was removed rather than left behind — a stale acceptance would silently re-cover the
advisory if something pulled `ecdsa` back in.

The two tests in `tests/unit/test_security.py` that pin algorithm confinement (a token signed
with another algorithm, and a hand-crafted `alg=none` token, must both be rejected) are kept:
the defence that matters is the explicit `algorithms=` allowlist, not the library behind it.

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

- ~~**`passlib` 1.7.4**~~ — **removed** 2026-07-30 in favour of calling `bcrypt` (now 5.0.0)
  directly, which also retired the `bcrypt<4` pin passlib forced. Stored `$2b$` hashes are
  unchanged and still verify; a test pins a passlib-era hash to prove it.
- ~~**`neo4j` 5.16.0 and `pika` 1.3.2**~~ — both **removed** 2026-07-30; neither was imported by
  any backend module. See [decisions/2026-07-30-drop-neo4j.md](decisions/2026-07-30-drop-neo4j.md).

---

## Added 2026-08-03 — GitHub repository scanning

- **`cryptography` 50.0.0** — Fernet, encrypting third-party credentials at rest in
  `tenant_secret`. This app had no reversible secret storage before; `api_key` stores a
  one-way hash, which is right for verifying inbound keys and useless for a token that must
  be replayed outbound.

  **Pinned at 50.0.0 rather than the 43.0.1 the plan first specified**, because 43.0.1 fails
  `scripts/audit_dependencies.py` on four advisories — CVE-2024-12797, CVE-2026-26007,
  CVE-2026-34073 and GHSA-537c-gmf6-5ccf. The audit gate caught this before CI did, which is
  what it is for. 50.0.0 reports no unaccepted advisories.

- **`python-hcl2` 7.3.1** — parses Terraform `.tf` source for the repository scanner. The
  pre-existing `terraform_import_service` parses `.tfstate` **JSON**, which is normally not
  committed to a repository (it contains secrets; best practice is remote state), so a
  scanner expecting it would find nothing. Clean on the audit gate.

  Note the two parsers are not interchangeable: HCL gives *declared* resources — no computed
  values, no resource ids — so scanning `.tf` and importing `.tfstate` for the same
  infrastructure will not produce identical rows.

## Added 2026-08-09 — environment naming conventions (Phase 7 B2)

- **`regex` 2026.7.19** — the mrab-regex engine, for its per-match `timeout=` argument.
  Already in the tree as a `python-hcl2` transitive; this **promotes it to a direct
  dependency**, so it adds no new supply-chain surface, only a declared reliance on it.
  Clean on the audit gate (`no unaccepted advisories across 59 packages`).

  The reason is that `re` has no per-match timeout. B2's environment naming pattern is
  written by a **tenant admin** and evaluated in the shared multi-tenant process — on every
  environment write and once per row of a tenant-wide sweep — so every match has to be
  bounded or one tenant's regex pins the server for all of them. Two earlier designs bounded
  only the *policy save*, with a subprocess probe, and left the write path and the sweep with
  no bound at all. `regex` is a syntax superset of `re`, so patterns written for one work in
  the other, and `environment_compliance_service` imports exactly one engine — there is no
  second opinion anywhere for the first to disagree with.

  **The swap opens a hole of its own, and it is worse than the one it closes.** `regex`
  expands bounded repeats at **compile** time where `re` does not, and no match timeout
  covers compilation: `(((a{1000}){1000}){1000})` is 25 characters, well inside the pattern
  length cap, and compiles under `re` in 0.2 ms while taking unbounded time and memory under
  `regex` — memory exhaustion takes the container down rather than failing one request. That
  is what `MAX_REPEAT_WEIGHT` exists for, checked before `regex.compile` is ever called. Any
  future change to this dependency, or to the guard, has to keep the compile-time ceiling and
  the per-match timeout together; either alone leaves the service exposed.
