#!/usr/bin/env bash
# Call EnvManager's deployment preflight gate. Informational only —
# logs the verdict and any blockers/warnings but does NOT fail the
# pipeline (yet). Flip BLOCK_ON_BLOCKERS=1 to make blockers a hard fail.
#
# Required env vars (typically set by GitLab CI):
#   ENVMGR_API_URL         http://localhost:8000
#   gitlab_ci_envmanager   plaintext API key
#   ENVMGR_ENVIRONMENT     "EnvMgr_SIT"
#   ENVMGR_SUBSYSTEM       "envManager_Frontend" or "envManager_Backend"
#
# Optional claim tokens:
#   ENVMGR_RELEASE_ID      pass to unlock an exclusive booking linked to that release
#   ENVMGR_BOOKING_ID      direct booking-owner claim
#
# Optional behaviour:
#   BLOCK_ON_BLOCKERS=1    exit 1 if blockers is non-empty
set -euo pipefail

: "${ENVMGR_API_URL:?ENVMGR_API_URL is not set}"
: "${gitlab_ci_envmanager:?gitlab_ci_envmanager (API key) is not set}"
: "${ENVMGR_ENVIRONMENT:?ENVMGR_ENVIRONMENT is not set}"
: "${ENVMGR_SUBSYSTEM:?ENVMGR_SUBSYSTEM is not set}"

# URL-encode env+subsystem (spaces, etc).
encode() { python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$1"; }

ENV_ENC=$(encode "${ENVMGR_ENVIRONMENT}")
SUB_ENC=$(encode "${ENVMGR_SUBSYSTEM}")

URL="${ENVMGR_API_URL}/api/v1/webhooks/can-deploy?environment_slug=${ENV_ENC}&subsystem_slug=${SUB_ENC}"

if [[ -n "${ENVMGR_RELEASE_ID:-}" ]]; then
  URL="${URL}&release_id=${ENVMGR_RELEASE_ID}"
fi
if [[ -n "${ENVMGR_BOOKING_ID:-}" ]]; then
  URL="${URL}&booking_id=${ENVMGR_BOOKING_ID}"
fi

echo "Preflight: ${URL}"
RESP=$(curl -sS -f -H "X-Api-Key: ${gitlab_ci_envmanager}" "${URL}")
echo "Response: ${RESP}"

OK=$(echo "${RESP}" | python3 -c "import json,sys; print(json.load(sys.stdin)['ok'])")

if [[ "${OK}" == "True" ]]; then
  echo "Preflight: OK — safe to deploy."
  exit 0
fi

echo "Preflight: BLOCKED. Inspect blockers above."

if [[ "${BLOCK_ON_BLOCKERS:-0}" == "1" ]]; then
  echo "BLOCK_ON_BLOCKERS=1 — failing the job."
  exit 1
fi

echo "BLOCK_ON_BLOCKERS not set — continuing (informational mode)."
exit 0
