# GitHub repository scanning — design

**Status**: design, not started. Phase 6, sub-project 2 of 2 remaining.

## What this is

Connect a tenant's GitHub account once, then scan a system's repository on demand to discover
infrastructure — instead of hand-uploading files on the System detail page, which is how it
works today.

## What already exists, and what does not

Checked against the code, not the roadmap:

| | |
|---|---|
| `System.github_repository_url` | A `String(500)` field. **Nothing reads it.** |
| Docker Compose parser | **Exists and works** (`docker_compose_import_service`), writes `ComponentDependency` with `source=docker_compose` |
| Terraform parser | **Exists**, but parses **`.tfstate` JSON**, not `.tf` source |
| Background jobs | One supervised asyncio loop (`workers/event_publisher.py`). **No task queue** — no celery, apscheduler or arq |
| Credential storage | **Does not exist.** `api_key.key_hash` is a one-way hash: right for verifying inbound keys, useless for a token we must replay outbound |
| `cryptography` | **Not installed.** PyJWT uses HS256; bcrypt is separate |
| `httpx` | Declared, but currently only used by tests — available for the client |

Two of these shape the whole design. There is **no reversible secret storage**, so that has to
be built before anything can authenticate. And the existing Terraform parser reads `.tfstate`,
which is normally *not* committed to a repository — it contains secrets and best practice is
remote state — so a scanner expecting it would find nothing in most repos.

## Scope

Three things were separable here: encrypted secrets, connect-and-scan-on-demand, and
automation. **This spec covers the first two.** Automation — scheduled polling or webhooks —
is deliberately excluded: the app has no scheduler, and adding one is a decision that deserves
its own spec rather than being folded in.

## Extensibility is a requirement, not a nicety

New infrastructure technologies keep appearing, so **adding a scanner must not require
refactoring the ones already working**. That constraint shapes the architecture rather than
being retrofitted.

A detector is three things:

```python
@dataclass(frozen=True)
class Detector:
    name: str                                    # "docker_compose", "terraform_hcl"
    matches: Callable[[str], bool]               # given a repo path, do I want it?
    parse: Callable[[ParseContext], Awaitable[DetectorResult]]

DETECTORS: list[Detector] = [DOCKER_COMPOSE, TERRAFORM_HCL]
```

Adding one is a module plus a list entry. It cannot alter traversal, authentication or
rate-limit handling, because it never sees them — it receives only the paths it claimed.

`DetectorResult` is deliberately narrow — `{subsystems_created, subsystems_updated,
dependencies_written, warnings: list[str]}` — so the scan can total results across detectors
without knowing what any of them did. A detector that later needs to report something new adds
a warning rather than widening the shared type.

**A path goes to every detector that claims it**, not the first. Detectors are independent by
construction, and "first match wins" would make behaviour depend on registry order — which is
exactly the kind of coupling this registry exists to avoid.

`ParseContext` carries `content`, `path`, `system_id`, `tenant_id`, `db`, and a **`fetch(path)`
callback**. The callback is the one deliberate concession to detector autonomy: a future Helm
or Kustomize detector needs a companion file (`values.yaml`, an `.env` beside a compose file),
and without it that detector would have to own the walk. One parameter now avoids that.

## Credential storage

**`tenant_secret`**: `(tenant_id, kind)` unique, plus `ciphertext`, `key_version`,
`created_at`, `created_by`, `last_used_at`, `expires_at` (nullable). Kinds used here are
`github_oauth_token` and `github_device_pending`.

**Fernet, from `cryptography`** — a new dependency, subject to `scripts/audit_dependencies.py`
in CI.

Two decisions worth holding to:

- **A key separate from `SECRET_KEY`.** `SECRET_KEY` signs JWTs. Reusing it to encrypt stored
  credentials couples two things with different blast radii and different rotation schedules.
  A distinct `SECRETS_ENCRYPTION_KEY`.
- **`key_version` from day one.** It costs a column now. Retrofitting rotation onto an
  unversioned column means a migration that must decrypt every row using the key you are
  trying to retire.

**No endpoint ever returns a secret.** `GET /integrations/github` answers
`{connected, github_login, connected_at}`. There is no read-back path; the only consumer is
the scanner, in-process.

## The connect journey (OAuth device flow)

1. `POST /integrations/github/connect` (tenant admin) calls GitHub's device-code endpoint and
   returns `user_code`, `verification_uri`, `expires_in`, `interval`, and an opaque handle.
   **The `device_code` stays server-side, encrypted** — it is the credential that redeems the
   token, so it must never reach the browser. It lives in `tenant_secret` under
   `github_device_pending` with an `expires_at`, reusing the same encryption path rather than
   introducing a second one.
2. The UI shows the code and the link; the user authorises on github.com.
3. `POST /integrations/github/connect/{handle}/poll` polls GitHub **once per call**, returning
   `pending` / `slow_down` / `connected` / `denied` / `expired`. The frontend polls at the
   interval GitHub specifies.

The user is present while this happens, so polling lives in the request cycle. **No background
worker and no scheduler** — which is what keeps this sub-project clear of infrastructure the
app does not have.

OAuth App tokens do not expire by default, so there is no refresh machinery. If expiring
tokens are ever enabled on the App, that becomes a follow-on, not a silent breakage: a 401 is
already handled below.

`DELETE /integrations/github` deletes the stored secret. It does **not** revoke server-side at
GitHub — that needs the client secret, which device flow otherwise avoids. **The UI must say
so plainly**: disconnecting stops EnvManager using the token, but the grant stands until
revoked in GitHub's settings. Telling someone their token is dead when it is not would be
worse than the extra sentence.

**Config**: `GITHUB_OAUTH_CLIENT_ID`, `SECRETS_ENCRYPTION_KEY`. Absent either, the connect
endpoints return a clear 503 rather than failing obscurely inside an HTTP call.

## The scan

`POST /systems/{system_id}/github/scan` (tenant admin):

1. Load the tenant's token — **409** if not connected, naming where to connect.
2. Parse `system.github_repository_url` into owner/repo — **422** if missing or unparseable,
   quoting what it found.
3. One call for the default branch, **one call for the whole tree**
   (`git/trees/{sha}?recursive=1`).
4. Ask each detector which paths it wants.
5. Fetch only those blobs; call each detector.
6. Return a per-detector summary: paths matched, subsystems created/updated, dependencies
   written, and errors.

**Blob fetches are bounded.** A repository with hundreds of `.tf` files would otherwise mean
hundreds of sequential API calls against a rate limit. The scan fetches at most
`MAX_SCAN_FILES` (200) blobs and **reports when it stopped early**, the same way truncation is
reported — a partial scan must never be indistinguishable from a complete one.

**One scan at a time per system.** A second concurrent scan of the same system is rejected
with 409 rather than allowed to interleave writes with the first, since both would be
upserting the same subsystems by name.

### The two detectors

**Compose** matches `docker-compose.y{a,}ml` and `compose.y{a,}ml` at any depth, and delegates
to the import service that already exists. No new parsing — which is what makes it a control
for the registry itself.

**Terraform HCL** matches `*.tf` and uses a **new** parser over `python-hcl2` (a second new
dependency), writing subsystems with `source=terraform` and upserting by name, as the tfstate
importer does.

**HCL gives *declared* resources**: no computed values, no resource ids. A `.tf` scan and a
`.tfstate` import of the same infrastructure will not produce identical rows. Stated here
because drift detection is the next sub-project and would otherwise inherit the assumption
that they agree.

## Failure modes

This is where the design earns its keep.

- **The tree API truncates.** GitHub sets `truncated: true` on large repositories and returns
  a partial tree. Unhandled, a scan of a big repo reports success having seen only part of it.
  **Truncation is a first-class outcome in the response** — it is the one failure here that
  otherwise looks exactly like success.
- **A detector raises.** Recorded against that detector; the others still run and the scan
  still reports. A new detector must not be able to break the ones already working — the
  extensibility requirement holding under failure, not only at authoring time.
- **401** — token revoked or expired. The stored secret is deleted and the response says
  reconnect, so the UI cannot keep claiming "connected".
- **403 with rate-limit headers** — surfaced with the reset time. Not retried blindly.
- **404** — repository gone, or the token lacks access. The message names the repository and
  distinguishes the two cases where GitHub's response allows it.

## Testing

The GitHub client is the seam: tests inject a fake transport, so the scanner, the registry and
both detectors are exercised without network access.

- A detector that throws leaves the other detectors' results intact.
- `truncated: true` surfaces as truncation rather than passing as success.
- A 401 clears the stored token.
- A scan writes only rows carrying its own `source`, never manually-created ones.
- Hitting `MAX_SCAN_FILES` reports early termination rather than reporting success.
- A path claimed by two detectors reaches both.
- Encryption round-trips, and decryption with the wrong key fails closed rather than returning
  garbage.
- Tenant isolation: one tenant's scan can never load another tenant's token, and
  `(tenant_id, kind)` is enforced.

Every test verified by breaking what it covers. Backend tests run on both engines.

## Out of scope

- **Automation** — scheduled scanning and webhooks. Needs a scheduler the app does not have.
- **Drift detection** — the other remaining Phase 6 sub-project.
- **Writing back to GitHub.** Scanning is read-only; the token requests read scope only.
- **Server-side token revocation at GitHub**, which needs the client secret device flow avoids.
- **Repository or organisation discovery** — this scans the repo a system already names, not
  a browser of everything the token can see.
