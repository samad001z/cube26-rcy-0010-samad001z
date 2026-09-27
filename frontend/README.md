# Alibi review UI

Next.js 16 (App Router), TypeScript, Tailwind 4, Radix UI primitives, TanStack Table 9,
lucide-react icons, Geist Sans and Geist Mono (the `geist` package, self-hosted by
`next/font`). The components in `src/components/ui/` follow shadcn/ui but are written by hand:
the shadcn registry is not reachable from the build environment.

## Run locally

```bash
# backend on :8000 with ALIBI_API_KEYS set (see ../.env.example, `alibi api-key --org <org>`)
cd frontend
npm install
ALIBI_BACKEND_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Or from the repo root: `make review-ui` (API and UI together, dev-only keys).

## How it talks to the backend

- Sign-in takes the organisation's API key, checks it against `GET /runs`, and stores it in an
  httpOnly, SameSite=Strict cookie for 8 hours. Page scripts cannot read it.
- The organisation name in the top bar comes from a second httpOnly cookie. No endpoint
  returns it yet, so it is read at sign-in from the newest decision record, and refreshed from
  the `X-Alibi-Organization` header after a run. An organisation with no run shows "Signed in".
  Backlog: `GET /me` (docs/BACKLOG.md).
- Pages are server components that call the backend from the server with that key.
- Overrides are a server action calling `POST /decisions/{id}/overrides`.
- New runs upload through `/api/run`, a route handler that forwards to `POST /agent`.
  **Load demo data** posts to `/api/run/demo`, which reads `../demo/` (or `ALIBI_DEMO_DIR`) on
  the server and forwards it the same way.
- Nothing is decided in the UI. It only displays what the backend returns. Money and
  confidence are strings from the server and are never computed on here; the KPI tiles show
  counts only. Sorting the money columns compares the decimal strings, it adds nothing up.

## Pages

- `/login`: key field with show/hide, error state, a note on how the key is stored.
- `/` decisions of the newest run (or `?run=`, also chosen in the top bar).
  - KPI tiles: all charges, CLAIM, DO NOT CLAIM, REVIEW, counts of equal weight; a tile filters.
  - Table: sortable columns, sticky header, filters for decision, charge type and rule (in the
    URL, applied by the backend), search by line or unit ID, 25 rows a page, a row opens the
    detail. Below 1024px the rows become cards, so nothing scrolls sideways.
  - The "Why" column is a plain-English headline per rule from `src/lib/reasons.ts`, one entry
    per rule id (with wording per charge type where it helps). A rule with no entry shows the
    engine's reason. The headline restates the rule; it never adds a fact.
  - Badges: changed by a reviewer, pending, history does not verify, and an earlier run's
    override of the same line (with a tooltip).
- `/decisions/[id]`
  - Header: line, decision, charge summary, charged and claim amounts, routing confidence with
    a tooltip on what it measures, and the **Override decision** button.
  - Why: the headline and the next action. The engine's full reason, rule, rule path,
    evidence status and reason code are under **Technical detail**.
  - Recovery checks with PASS / FAIL / UNCERTAIN icons and plain-English names.
  - Evidence as a timeline: records in time order around the posting date, each pod's custody
    window drawn as a shaded rail, records cited by the decision solid, records read but not
    cited dashed.
  - Amounts with the claim computation, the filing deadline card, the override history as a
    timeline, **Record integrity** (every hash, with copy buttons), other runs of the line.
  - Override side sheet: new decision, required reason, reviewer. When the backend says CLAIM
    is not allowed, CLAIM is shown disabled with the backend's reason. The backend checks
    everything again on save.
- `/run` **Load demo data** (see ../demo/README.md) and an upload form for a report and the
  four upstream files.
- `/about` what the outcomes mean, who decides, overrides, demo data.
- Loading skeletons with the same outline as each page, an error page with retry, a not-found
  page, and empty states.

## Design

- Tokens are CSS variables in `src/app/globals.css`, light and dark, following the system
  setting. Neutral greys, one blue accent, and three decision colours used everywhere: CLAIM
  green, DO NOT CLAIM slate, REVIEW amber. Every decision chip and verdict has an icon and its
  word, so colour is never the only signal.
- 14px base text, Tailwind's 4px spacing scale, tabular numbers for amounts and counts,
  Geist Mono for IDs and hashes.
- Visible focus outline on every control, a skip link, labelled icon buttons.
- `node scripts/contrast.mjs` checks every text/background token pair against WCAG AA
  (4.5:1) in both themes.

## Checks

```bash
npx eslint && npx next build
node scripts/contrast.mjs
# with the API and UI running and the demo run newest for org_demo_alpha:
ALIBI_KEY=dev-only-alpha-review-key node scripts/screenshots.mjs
```

`scripts/screenshots.mjs` writes `docs/screenshots/*.png` (sign-in, list, detail, override;
light and dark; the list at phone width) and fails on a console error, on any page that scrolls
sideways at 375px, or on a missing focus outline.

Limitation: the reviewer name on an override is typed by the operator. The API key identifies
an organisation, not a person.
