#!/usr/bin/env bash
# Deploy the Alibi API to Cloud Run (DEPLOY.md walks through it). Run from anywhere; steps:
#
#   deploy/cloudrun.sh setup     APIs, Artifact Registry repo, service account + IAM (once)
#   deploy/cloudrun.sh secrets   create or update the three secrets from environment variables
#   deploy/cloudrun.sh deploy    build the image with Cloud Build and deploy a new revision
#   deploy/cloudrun.sh url       print the service URL
#
# Settings (environment, with defaults): PROJECT=bytesofjoy-501900 REGION=australia-southeast1
# SERVICE=alibi-api REPO=alibi. DRY_RUN=1 prints the commands instead of running them.
# No secret value is ever passed on a command line or printed.
set -euo pipefail

PROJECT="${PROJECT:-bytesofjoy-501900}"
REGION="${REGION:-australia-southeast1}"
SERVICE="${SERVICE:-alibi-api}"
REPO="${REPO:-alibi}"
SA_NAME="${SA_NAME:-alibi-api}"
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/api:$TAG"
# Secret Manager secret -> environment variable in the container.
SECRETS=(
  "alibi-database-url:DATABASE_URL"
  "alibi-attachment-key-secret:ATTACHMENT_KEY_SECRET"
  "alibi-api-keys:ALIBI_API_KEYS"
)

run() {
  if [ "${DRY_RUN:-}" = 1 ]; then printf '+ %q' "$1"; shift; printf ' %q' "$@"; echo; else "$@"; fi
}

setup() {
  run gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    cloudbuild.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com \
    --project "$PROJECT"
  if [ "${DRY_RUN:-}" = 1 ] || ! gcloud artifacts repositories describe "$REPO" \
      --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    run gcloud artifacts repositories create "$REPO" --repository-format docker \
      --location "$REGION" --project "$PROJECT" --description "Alibi images"
  fi
  if [ "${DRY_RUN:-}" = 1 ] || ! gcloud iam service-accounts describe "$SA" \
      --project "$PROJECT" >/dev/null 2>&1; then
    run gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
      --display-name "Alibi API (Cloud Run)"
  fi
  # Vertex AI through the service identity: no key file anywhere (D-022, DEPLOY.md).
  run gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/aiplatform.user --condition None
}

secrets() {
  # Values come from these environment variables, piped to gcloud on stdin:
  #   ALIBI_DATABASE_URL     alibi_app URL through the Supabase session pooler, sslmode=require
  #   ATTACHMENT_KEY_SECRET  long random string (openssl rand -hex 32), same as bin/seed-demo uses
  #   ALIBI_API_KEYS         org:sha256,... hashes from `alibi api-key` (never the keys)
  local pair name var value
  for pair in "${SECRETS[@]}"; do
    name="${pair%%:*}"
    var="${pair##*:}"
    [ "$var" = DATABASE_URL ] && var=ALIBI_DATABASE_URL
    value="${!var:-}"
    if [ -z "$value" ]; then
      echo "cloudrun.sh: set $var to create secret $name" >&2
      exit 2
    fi
    if [ "${DRY_RUN:-}" = 1 ]; then
      echo "+ gcloud secrets create-or-add-version $name --data-file=- (value from \$$var)"
      echo "+ gcloud secrets add-iam-policy-binding $name --member serviceAccount:$SA --role roles/secretmanager.secretAccessor"
      continue
    fi
    if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
      printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --project "$PROJECT"
    else
      printf '%s' "$value" | gcloud secrets create "$name" --data-file=- \
        --replication-policy automatic --project "$PROJECT"
    fi
    gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT" \
      --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null
  done
}

deploy() {
  run gcloud builds submit "$ROOT" --project "$PROJECT" --region "$REGION" \
    --config "$ROOT/deploy/cloudbuild.yaml" --substitutions "_IMAGE=$IMAGE"
  local secret_flags env_flags
  secret_flags="$(printf '%s,' "${SECRETS[@]/%/:latest}" | sed 's/,$//')"
  secret_flags="$(echo "$secret_flags" | sed -E 's/([a-z-]+):([A-Z_]+):latest/\2=\1:latest/g')"
  # Plain settings. MIGRATION_DATABASE_URL is required by the settings but never used by the
  # API: migrations run from an operator machine as alibi_owner, so the API never holds the
  # owner password. LLM settings are read from the caller's environment (DEPLOY.md).
  env_flags="MIGRATION_DATABASE_URL=unused-in-the-api"
  env_flags+=",LLM_ENABLED=${LLM_ENABLED:-false}"
  if [ "${LLM_ENABLED:-false}" = true ]; then
    for v in LLM_PROVIDER GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_LOCATION LLM_MODEL; do
      if [ -z "${!v:-}" ]; then echo "cloudrun.sh: LLM_ENABLED=true needs $v" >&2; exit 2; fi
      env_flags+=",$v=${!v}"
    done
    for v in LLM_PRICE_INPUT_USD_PER_MTOK LLM_PRICE_OUTPUT_USD_PER_MTOK LLM_TIMEOUT_S; do
      [ -n "${!v:-}" ] && env_flags+=",$v=${!v}"
    done
  fi
  run gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --image "$IMAGE" --service-account "$SA" \
    --allow-unauthenticated \
    --port 8080 --cpu 1 --memory 512Mi --concurrency 20 --max-instances 3 --timeout 300 \
    --set-secrets "$secret_flags" \
    --set-env-vars "$env_flags"
}

url() {
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format 'value(status.url)'
}

case "${1:-}" in
  setup) setup ;;
  secrets) secrets ;;
  deploy) deploy ;;
  url) url ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
