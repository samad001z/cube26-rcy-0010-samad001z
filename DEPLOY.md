# Deploying Alibi

The API runs on **Google Cloud Run** in project `bytesofjoy-501900`, the database on
**Supabase Postgres**, and the review UI on **Vercel**. Nothing secret is ever in the
repository or an image: database URLs, the attachment secret and the API key hashes live
in Secret Manager; model access comes from the Cloud Run service identity.

```
browser ──> Vercel (Next.js UI, syd1) ──X-API-Key──> Cloud Run alibi-api (australia-southeast1)
                                                        │  Secret Manager: DATABASE_URL,
                                                        │  ATTACHMENT_KEY_SECRET, ALIBI_API_KEYS
                                                        ├──> Supabase Postgres (schema alibi,
                                                        │    role alibi_app, RLS forced, SSL)
                                                        └──> Vertex AI Gemini (service identity)
```

Do the steps in order the first time. Every command runs from the repository root on your
machine, with `gcloud`, `psql`, `uv` and Node installed. Regions: Cloud Run
`australia-southeast1` and Supabase `ap-southeast-2` (both Sydney), Vercel functions
`syd1`. Change them together.

## 1. Supabase: project, roles and schema

1. Create a Supabase project in region **Oceania (Sydney)**. Keep the database password
   of the `postgres` user in your password manager.
2. **Project Settings → Database → SSL Configuration**: turn on *Enforce SSL on incoming
   connections*.
3. **Connect → Session pooler**: note the host (`aws-0-ap-southeast-2.pooler.supabase.com`,
   port `5432`) and your project ref. Through the pooler the user name is
   `<role>.<project-ref>`. Use the session pooler: the direct host is IPv6-only unless the
   project has the IPv4 add-on, and Cloud Run's default egress is IPv4; the transaction
   pooler does not support the prepared statements psycopg uses.
4. Create the two roles and the `alibi` schema (`deploy/supabase.sql`). Passwords come
   from your shell, not from the file:

   ```bash
   export SUPA_REF=<project-ref>
   export SUPA_HOST=aws-0-ap-southeast-2.pooler.supabase.com
   export ALIBI_OWNER_PASSWORD="$(openssl rand -hex 24)"   # keep both in your password manager
   export ALIBI_APP_PASSWORD="$(openssl rand -hex 24)"
   psql "postgresql://postgres.$SUPA_REF@$SUPA_HOST:5432/postgres?sslmode=require" \
     -v ON_ERROR_STOP=1 -f deploy/supabase.sql
   ```

   `deploy/supabase.sql` reads `ALIBI_OWNER_PASSWORD` and `ALIBI_APP_PASSWORD` from the
   environment with psql's `\getenv`, so they are never typed as a `-v` command-line
   argument (both are already exported above; psql inherits the environment of the shell
   that runs it).

   `alibi_owner` owns the schema and runs migrations; `alibi_app` is what the API uses.
   Neither is a superuser, both are `NOBYPASSRLS`. The tables live in schema `alibi`
   (each role's `search_path`), which Supabase's Data API does not expose, and the `anon`
   and `authenticated` roles get no access to it. Leave `alibi` out of **Project Settings
   → Data API → Exposed schemas**.

## 2. Migrations and database check

Migrations run from your machine as the owner, never from the API:

```bash
export OWNER_URL="postgresql+psycopg://alibi_owner.$SUPA_REF:$ALIBI_OWNER_PASSWORD@$SUPA_HOST:5432/postgres?sslmode=require"
export APP_URL="postgresql+psycopg://alibi_app.$SUPA_REF:$ALIBI_APP_PASSWORD@$SUPA_HOST:5432/postgres?sslmode=require"
MIGRATION_DATABASE_URL="$OWNER_URL" make migrate
CHECK_DB_URL="$OWNER_URL" bin/check-db alibi
```

`bin/check-db` must end with `all checks passed`: RLS enabled and forced on every table,
`alibi_app` limited to SELECT and INSERT, neither role able to bypass RLS, no Data API
role on the schema, and the connection using SSL. If "tables migrated" fails, the
migration did not land in `alibi` (for example the role's `search_path` was not set):
fix that before going on.

For a later release: run `make migrate` against Supabase first, then deploy the API.
Migrations are append-only (CLAUDE.md rule 15), so the running API keeps working.

## 3. API keys and demo data

One key per organisation. The key goes to whoever signs in; only its hash is deployed.

```bash
cd backend
uv run alibi api-key --org org_demo_alpha   # prints the key once, and org:hash
uv run alibi api-key --org org_demo_bravo
cd ..
export ALIBI_API_KEYS="org_demo_alpha:<hash>,org_demo_bravo:<hash>"   # hashes only
export ATTACHMENT_KEY_SECRET="$(openssl rand -hex 32)"               # keep it
```

Seed the demo (alpha: `demo/`, checked line by line; bravo: the sample in `data/`, so the
isolation check has rows on both sides). It connects as `alibi_app` and refuses unless
you repeat the host:

```bash
DATABASE_URL="$APP_URL" ATTACHMENT_KEY_SECRET="$ATTACHMENT_KEY_SECRET" \
SEED_CONFIRM_HOST="$SUPA_HOST" bin/seed-demo
```

It must print `demo check passed`. The seeded runs are judged as of the day you seed them.

## 4. Cloud Run: the API

```bash
gcloud auth login && gcloud config set project bytesofjoy-501900
deploy/cloudrun.sh setup                # APIs, Artifact Registry, service account alibi-api
ALIBI_DATABASE_URL="$APP_URL" deploy/cloudrun.sh secrets   # + ATTACHMENT_KEY_SECRET, ALIBI_API_KEYS
deploy/cloudrun.sh deploy               # Cloud Build image, new revision
export API_URL="$(deploy/cloudrun.sh url)"
curl -s "$API_URL/health"               # {"status":"ok","db":"ok"}
```

What `deploy` does (`DRY_RUN=1 deploy/cloudrun.sh deploy` prints it):

- builds `backend/Dockerfile` with Cloud Build (`deploy/cloudbuild.yaml`). The upload is
  limited by `.gcloudignore` and the image by `.dockerignore` to `backend/` and `config/`:
  no `.env`, no key file, no `eval/`, `data/` or frontend;
- deploys service `alibi-api` as service account `alibi-api@bytesofjoy-501900.iam.gserviceaccount.com`,
  port 8080, 1 CPU, 512 MiB, up to 3 instances, 300 s timeout;
- `DATABASE_URL`, `ATTACHMENT_KEY_SECRET` and `ALIBI_API_KEYS` from Secret Manager
  (`alibi-database-url`, `alibi-attachment-key-secret`, `alibi-api-keys`; the service
  account may read only these);
- `MIGRATION_DATABASE_URL=unused-in-the-api`: the setting is required but the API never
  migrates, so it never holds the owner password;
- `--allow-unauthenticated`: the API checks `X-API-Key` itself on every endpoint except
  `/health`. If an organisation policy forbids public services, grant `roles/run.invoker`
  to a service account instead and have the UI call with an identity token (not built).

Cloud Run refuses HTTP/1 request bodies over 32 MiB, which bounds uploads to `POST /agent`
(an open issue from Day 3). The first request after idle starts an instance and takes a
few seconds; `--min-instances 1` avoids that at a cost.

Rollback: `gcloud run services update-traffic alibi-api --region australia-southeast1
--to-revisions <previous-revision>=100`.

## 5. Vercel: the review UI

1. Import the repository in Vercel. **Root Directory: `frontend`**. `frontend/vercel.json`
   sets the framework (Next.js), `npm ci`, `npm run build` and region `syd1`.
2. **Settings → Build and Deployment**: Node.js 22.x, and keep *Include files outside the
   root directory in the Build Step* **on**. The prebuild step copies `../demo` into
   `frontend/demo-data/` for "Load demo data" and fails the build if it cannot.
3. **Settings → Environment Variables** (Production and Preview):
   `ALIBI_BACKEND_URL` = the Cloud Run URL from step 4. Nothing else: the UI holds no
   secret. Each person signs in with their organisation's key, which the UI keeps in an
   httpOnly, Secure, SameSite=Strict cookie and sends to the API from the server only.
4. Deploy (push to the production branch, or `npx vercel --prod` in `frontend/`).

## 6. Live smoke test

```bash
cd frontend && npm ci && npx playwright install chromium && cd ..
API_URL="$API_URL" UI_URL=https://<your-vercel-domain> \
ALPHA_KEY=<alpha key> BRAVO_KEY=<bravo key> bin/smoke-live
```

It stops at the first failure and ends with `all 23 checks passed` when:

- the API is healthy with its database;
- keys map to their organisations, and a wrong key or no key gets 401;
- alpha's newest run has the 10 demo lines (3 CLAIM, 3 DO NOT CLAIM, 4 REVIEW) and totals;
- bravo sees none of alpha's decisions, and each organisation gets 404 on the other's
  decision IDs;
- in the UI, sign-in refuses a wrong key and accepts alpha's, the top bar names the
  organisation, the key cookie is invisible to page scripts, the list and a decision
  open, sign-out works, and no page error is raised.

## 7. Model access (Vertex AI)

Model explanations are optional (`LLM_ENABLED=false` by default, D-022). When they are on,
the API calls Gemini on Vertex AI. **No credential file is ever part of the image or the
repository.**

### Production: the Cloud Run service identity (preferred)

`deploy/cloudrun.sh setup` already does the `gcloud` steps below; they are listed so it is
clear what access the service has.

The API runs as its own service account. Cloud Run gives the container that identity
through the metadata server, and the google-genai SDK picks it up as Application Default
Credentials. There is no key to store, rotate or leak.

```bash
PROJECT=bytesofjoy-501900
SA=alibi-api@$PROJECT.iam.gserviceaccount.com

gcloud services enable aiplatform.googleapis.com --project $PROJECT
gcloud iam service-accounts create alibi-api --project $PROJECT \
  --display-name "Alibi API (Cloud Run)"
gcloud projects add-iam-policy-binding $PROJECT \
  --member "serviceAccount:$SA" --role roles/aiplatform.user
```

`deploy/cloudrun.sh deploy` runs the service as `$SA`. To turn explanations on, deploy with
these plain environment variables in your shell (not secrets; none of them grants access):

```
LLM_ENABLED=true
LLM_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=bytesofjoy-501900
GOOGLE_CLOUD_LOCATION=<region where the chosen model is available>
LLM_MODEL=<model ID from Vertex AI → Model Garden>
LLM_PRICE_INPUT_USD_PER_MTOK=<from the Vertex AI pricing page>
LLM_PRICE_OUTPUT_USD_PER_MTOK=<from the Vertex AI pricing page>
```

for example `LLM_ENABLED=true LLM_PROVIDER=vertex GOOGLE_CLOUD_PROJECT=bytesofjoy-501900
GOOGLE_CLOUD_LOCATION=... LLM_MODEL=... deploy/cloudrun.sh deploy`. Check it once with
`make llm-smoke` locally against the same project, model and region.

Do **not** set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run. The `roles/aiplatform.user`
grant is the only permission the model call needs; remove it to turn model access off
without a redeploy (explanations then fall back to the standard text, decisions are
unaffected).

### Local and dev: Application Default Credentials or a key file outside the repo

For running `make llm-smoke` or the API on your machine, in order of preference:

1. `gcloud auth application-default login`, as a user with the Vertex AI User role on the
   project. Or impersonate the service account without a key:
   `gcloud auth application-default login --impersonate-service-account $SA`.
2. A service-account key file, only if the two above are not possible. Keep it outside the
   repository, readable only by you, and point to it from `.env`:

   ```bash
   mkdir -p ~/.config/alibi && chmod 700 ~/.config/alibi
   gcloud iam service-accounts keys create ~/.config/alibi/vertex-dev.json --iam-account $SA
   chmod 600 ~/.config/alibi/vertex-dev.json
   # .env
   GOOGLE_APPLICATION_CREDENTIALS=/home/<you>/.config/alibi/vertex-dev.json
   ```

   The settings refuse a path inside the repository. `.gitignore` ignores
   `*service-account*.json`, `*credentials*.json` and `.secrets/`, and `make check-keys`
   (a CI step) fails if any tracked file contains a private key field. Delete the key
   (`gcloud iam service-accounts keys delete`) when you no longer need it.

Then `make llm-smoke` checks the setup with one real call.
