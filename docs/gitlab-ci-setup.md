# GitLab CI/CD setup — dogfooding EnvManager

This guide turns the local GitLab project into the source of truth for the EnvManager-on-EnvManager dogfooding loop. Every successful pipeline registers two builds (frontend + backend, where they changed) and two deployments to the *EnvMgr_SIT* environment, plus an auto-created `code_deployment` change request per subsystem.

## Prerequisites

| | |
|---|---|
| Local GitLab | `http://localhost:8929` (per `docker-compose.yml`). |
| GitLab project | EnvManager repo, project_id `2`. |
| GitLab runner | A **shell-type** runner registered against this project. The runner host must be the same Mac that runs the EnvManager backend, since the pipeline calls `http://localhost:8000`. |
| EnvManager backend | Must be running on `localhost:8000` when the pipeline runs (`uvicorn app.main:app --reload` from `backend/`). |
| EnvManager demo tenant | Must contain the system *Env Manager* with subsystems *envManager_Frontend* and *envManager_Backend*, plus an environment named *EnvMgr_SIT*. |

## One-time setup

### 1. Create the API key in EnvManager

1. Sign in to EnvManager at `http://localhost:5173` as `admin` / `admin123` (tenant `demo`).
2. Open `/tenant/api-keys` (left nav: *API keys*).
3. Click *New key*.
4. Fill the dialog:
   - **Name**: `gitlab-ci-envmanager`
   - **Scopes**: tick *CI/CD deployment webhook* (`webhooks:deployment`).
   - **Expires at**: leave blank for non-expiring (or set a date you'll remember).
5. Click *Create*. **Copy the plaintext key from the reveal screen — it is shown once.**

### 2. Add the key as a GitLab CI/CD variable

In the local GitLab UI:

1. Open the EnvManager project → *Settings* → *CI/CD* → *Variables* → *Add variable*.
2. Key: `gitlab_ci_envmanager` (lowercase; the `.gitlab-ci.yml` references this name verbatim).
3. Value: paste the plaintext key.
4. Type: *Variable*.
5. **Tick *Mask variable*.** This hides the value in job logs.
6. Untick *Protect variable* unless you only want it on protected branches.
7. Save.

### 3. Verify the runner

```sh
gitlab-runner status
gitlab-runner verify
```

The runner should be tagged for this project and use the *shell* executor. The runner user needs `node`, `npm`, `uv`, `python3`, `curl`, and `uuidgen` on PATH — the same toolchain used for local dev.

## What the pipeline does

| Stage | Job | Runs when | What it does |
|-------|-----|-----------|--------------|
| `validate` | `validate:scripts` | every push | `bash -n` syntax check on the helper scripts. |
| `preflight` | `preflight:frontend` | `frontend/**` changed | `GET /api/v1/webhooks/can-deploy?...subsystem_slug=envManager_Frontend`. Logs blockers/warnings. **Does not fail the pipeline** while `BLOCK_ON_BLOCKERS=0`. |
| `preflight` | `preflight:backend` | `backend/**` changed | Same, for the backend subsystem. |
| `build_test` | `build_test:frontend` | `frontend/**` changed | `npm ci && npm run lint && npm run test -- --run && npm run build`. |
| `build_test` | `build_test:backend` | `backend/**` changed | `uv sync --frozen && uv run pytest -q`. |
| `register_deployment` | `register_deployment:frontend` | `frontend/**` changed AND `build_test:frontend` succeeded | `POST /api/v1/webhooks/deployment` with `system_slug="Env Manager"`, `subsystem_slug="envManager_Frontend"`, `environment_slug="EnvMgr_SIT"`. |
| `register_deployment` | `register_deployment:backend` | `backend/**` changed AND `build_test:backend` succeeded | Same, for the backend subsystem. |

**Trigger:** every push to any branch + MRs.

**Build identity:** each pipeline run gets its own `build_number` (= `CI_PIPELINE_ID`), so two pipeline runs of the same commit produce **two distinct Build rows** with the same SHA. That's deliberate — it lets you tell "fresh build of unchanged code, deployed to a new env" apart from "same artefact promoted."

## Hardening preflight (later)

Once you've watched the preflight job log a few times and trust its verdict, change `BLOCK_ON_BLOCKERS` in `.gitlab-ci.yml` (or set it as a project variable) from `"0"` to `"1"`. The preflight job stays `allow_failure: true` so it doesn't block pipelines while you experiment; switch to `allow_failure: false` to make a blocked preflight kill the build.

## Passing claim tokens (release-managed deploys)

If a release manager has booked *EnvMgr_SIT* exclusively for their release, an unannotated CI run from another developer's branch will be **blocked** by preflight. To pass through:

- Set `ENVMGR_RELEASE_ID` (project or pipeline variable) to the release id that owns the booking. Preflight will compare and unlock.
- Or set `ENVMGR_BOOKING_ID` directly if you know the booking row.

The `register_deployment` step doesn't take these tokens — only the preflight uses them. The deploy webhook itself accepts `release_id` and `change_request_id` at the top level if you want to pre-link the deployment; extending `register_deployment.sh` to forward them is a one-line change.

## First-push verification

1. Make a trivial change in `backend/` (e.g. add a blank line in a comment), commit, push.
2. Open the GitLab pipeline page for this project.
3. Expect `validate:scripts` → `preflight:backend` → `build_test:backend` → `register_deployment:backend` to all run. The frontend jobs should be skipped (no `frontend/**` change).
4. Open EnvManager → `/builds` and `/deployments`. The new build for *envManager_Backend* and a deployment to *EnvMgr_SIT* should appear within seconds of the pipeline finishing.
5. Open the deployment detail. The *Change request* link should point at an auto-created `Deploy <sha8> → EnvMgr_SIT` CR.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `register_deployment` fails with `Unknown system_slug 'Env Manager'` | The system, subsystem, or environment is not present in the demo tenant. Slugs match `name` exactly (case-sensitive, spaces preserved). |
| `register_deployment` fails with `connection refused` | EnvManager backend isn't running. Start `uvicorn` from `backend/`. |
| `register_deployment` fails with `401 Unauthorized` | Wrong `gitlab_ci_envmanager` value, or the key was revoked. Re-issue and update the variable. |
| `register_deployment` fails with `403 Forbidden` | The key exists but lacks the `webhooks:deployment` scope. Re-issue with the correct scope. |
| `build_test:backend` fails with `uv: command not found` | The runner user's PATH is missing `uv`. Install via `curl -LsSf https://astral.sh/uv/install.sh \| sh` and re-source the shell. |
| `preflight` job logs `BLOCKED` but the pipeline passes | Expected while `BLOCK_ON_BLOCKERS=0`. The job is informational. Flip the flag to enforce. |

## Files referenced

- `.gitlab-ci.yml` — pipeline definition.
- `scripts/ci/preflight.sh` — calls `GET /api/v1/webhooks/can-deploy`.
- `scripts/ci/register_deployment.sh` — calls `POST /api/v1/webhooks/deployment`.
- Admin guide ch. 10 — full webhook + preflight + scope reference (`docs/admin-guide.md`).
