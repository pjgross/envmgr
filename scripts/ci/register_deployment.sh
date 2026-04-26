#!/usr/bin/env bash
# Register a build + deployment with EnvManager via the deployment webhook.
#
# Required env vars (typically set by GitLab CI):
#   ENVMGR_API_URL         http://localhost:8000   (laptop dev default)
#   gitlab_ci_envmanager   plaintext API key (masked CI/CD variable)
#   ENVMGR_SYSTEM          "Env Manager"
#   ENVMGR_SUBSYSTEM       "envManager_Frontend" or "envManager_Backend"
#   ENVMGR_ENVIRONMENT     "EnvMgr_SIT"
#   CI_COMMIT_SHA          provided by GitLab — full git SHA
#   CI_COMMIT_REF_NAME     provided by GitLab — branch or tag
#   CI_PIPELINE_ID         provided by GitLab — monotonic pipeline id
#   CI_JOB_STARTED_AT      provided by GitLab — ISO-8601
#
# Optional:
#   ENVMGR_STATUS          deployment status (default "success")
#   PIPELINE_STEP_NAME     name to record for the build's single step (default "ci")
#   PIPELINE_STEP_STATUS   status of that step (default "success")
set -euo pipefail

: "${ENVMGR_API_URL:?ENVMGR_API_URL is not set}"
: "${gitlab_ci_envmanager:?gitlab_ci_envmanager (API key) is not set}"
: "${ENVMGR_SYSTEM:?ENVMGR_SYSTEM is not set}"
: "${ENVMGR_SUBSYSTEM:?ENVMGR_SUBSYSTEM is not set}"
: "${ENVMGR_ENVIRONMENT:?ENVMGR_ENVIRONMENT is not set}"
: "${CI_COMMIT_SHA:?CI_COMMIT_SHA is not set}"
: "${CI_COMMIT_REF_NAME:?CI_COMMIT_REF_NAME is not set}"
: "${CI_PIPELINE_ID:?CI_PIPELINE_ID is not set}"
: "${CI_JOB_STARTED_AT:?CI_JOB_STARTED_AT is not set}"

STATUS="${ENVMGR_STATUS:-success}"
STEP_NAME="${PIPELINE_STEP_NAME:-ci}"
STEP_STATUS="${PIPELINE_STEP_STATUS:-success}"

EVENT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

PAYLOAD=$(cat <<JSON
{
  "event_id": "${EVENT_ID}",
  "system_slug": "${ENVMGR_SYSTEM}",
  "subsystem_slug": "${ENVMGR_SUBSYSTEM}",
  "environment_slug": "${ENVMGR_ENVIRONMENT}",
  "status": "${STATUS}",
  "deployed_at": "${NOW_ISO}",
  "deployer_name": "gitlab-ci:${GITLAB_USER_LOGIN:-unknown}",
  "build": {
    "git_sha": "${CI_COMMIT_SHA}",
    "git_branch": "${CI_COMMIT_REF_NAME}",
    "build_number": "${CI_PIPELINE_ID}",
    "commit_timestamp": "${CI_COMMIT_TIMESTAMP:-${NOW_ISO}}",
    "build_started_at": "${CI_JOB_STARTED_AT}",
    "build_finished_at": "${NOW_ISO}",
    "jira_tickets": [],
    "pipeline_steps": [
      {
        "name": "${STEP_NAME}",
        "status": "${STEP_STATUS}",
        "started_at": "${CI_JOB_STARTED_AT}",
        "finished_at": "${NOW_ISO}"
      }
    ],
    "custom_fields": {
      "ci_pipeline_url": "${CI_PIPELINE_URL:-}",
      "ci_job_url": "${CI_JOB_URL:-}"
    }
  },
  "deployment_custom_fields": {
    "gitlab_project": "${CI_PROJECT_PATH:-}",
    "gitlab_pipeline_id": "${CI_PIPELINE_ID}"
  }
}
JSON
)

echo "Posting deployment for ${ENVMGR_SUBSYSTEM} build #${CI_PIPELINE_ID} (${CI_COMMIT_SHA:0:8}) to ${ENVMGR_ENVIRONMENT}..."

# -f makes curl fail on HTTP >= 400; -sS stays quiet on success but prints errors.
HTTP_BODY=$(curl -sS -f -X POST "${ENVMGR_API_URL}/api/v1/webhooks/deployment" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${gitlab_ci_envmanager}" \
  --data "${PAYLOAD}")

echo "EnvManager response: ${HTTP_BODY}"
