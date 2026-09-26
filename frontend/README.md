# Alibi review UI

Next.js 16 (App Router), TypeScript, Tailwind 4. Components are hand-written (no shadcn CLI:
its registry is not reachable from the build environment).

## Run locally

```bash
# backend on :8000 with ALIBI_API_KEYS set (see ../.env.example, `alibi api-key --org <org>`)
cd frontend
npm install
ALIBI_BACKEND_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

## How it talks to the backend

- Sign-in takes the organisation's API key, checks it against `GET /runs`, and stores it in an
  httpOnly, SameSite=Strict cookie for 8 hours. Page scripts cannot read it.
- Pages are server components that call the backend from the server with that key.
- Overrides are a server action calling `POST /decisions/{id}/overrides`.
- New runs upload through `/api/run`, a route handler that forwards to `POST /agent`.
- Nothing is decided in the UI. It only displays what the backend returns; money and
  confidence are strings from the server and are never computed on here.

## Pages

- `/` decisions of the newest run (or `?run=`), REVIEW first, filter by decision.
- `/decisions/[id]` reason, recovery checks, evidence trail with hash checks, amounts and
  claim computation, override form and history, traceability, other runs of the line.
- `/run` upload a report and the four upstream files.

Limitation: the reviewer name on an override is typed by the operator. The API key identifies
an organisation, not a person.
