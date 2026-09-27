# Deploying Alibi

The API runs on Google Cloud Run in project `bytesofjoy-501900`, the database on Supabase
Postgres, and the review UI on Vercel.

## Model access (Vertex AI)

Model explanations are optional (`LLM_ENABLED=false` by default, D-022). When they are on,
the API calls Gemini on Vertex AI. **No credential file is ever part of the image or the
repository.**

### Production: the Cloud Run service identity (preferred)

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

Deploy the service with `--service-account $SA` and these plain environment variables (not
secrets; none of them grants access):

```
LLM_ENABLED=true
LLM_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=bytesofjoy-501900
GOOGLE_CLOUD_LOCATION=<region where the chosen model is available>
LLM_MODEL=<model ID from Vertex AI → Model Garden>
LLM_PRICE_INPUT_USD_PER_MTOK=<from the Vertex AI pricing page>
LLM_PRICE_OUTPUT_USD_PER_MTOK=<from the Vertex AI pricing page>
```

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
