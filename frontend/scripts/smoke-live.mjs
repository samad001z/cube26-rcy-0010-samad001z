// Live smoke test of a deployment (bin/smoke-live). Fails on the first broken check.
//
//   API_URL=https://<cloud-run-url> UI_URL=https://<vercel-url> \
//   ALPHA_KEY=<org_demo_alpha key> BRAVO_KEY=<org_demo_bravo key> node scripts/smoke-live.mjs
//
// Expects the seed (bin/seed-demo): the demo run newest for alpha, the sample for bravo.
// Browser checks need Chromium once: npx playwright install chromium (or CHROMIUM_PATH).
import { chromium } from "playwright";

const API = (process.env.API_URL ?? "").replace(/\/$/, "");
const UI = (process.env.UI_URL ?? "").replace(/\/$/, "");
const ALPHA = process.env.ALPHA_KEY;
const BRAVO = process.env.BRAVO_KEY;
for (const [k, v] of Object.entries({ API_URL: API, UI_URL: UI, ALPHA_KEY: ALPHA, BRAVO_KEY: BRAVO })) {
  if (!v) {
    console.error(`smoke-live: set ${k}`);
    process.exit(2);
  }
}

let passed = 0;
function ok(what) {
  passed += 1;
  console.log(`ok    ${what}`);
}
function fail(what, detail) {
  console.log(`FAIL  ${what}${detail ? `: ${detail}` : ""}`);
  console.log(`smoke-live: FAILED after ${passed} passing check(s)`);
  process.exit(1);
}
function check(cond, what, detail) {
  if (cond) ok(what);
  else fail(what, detail);
}

async function api(path, key) {
  const res = await fetch(`${API}${path}`, { headers: key ? { "X-API-Key": key } : {} });
  let body = null;
  try {
    body = await res.json();
  } catch {}
  return { status: res.status, body };
}

// --- API -------------------------------------------------------------------------------
const health = await api("/health");
check(health.status === 200 && health.body?.status === "ok" && health.body?.db === "ok", "API /health: ok, database ok", JSON.stringify(health.body));

check((await api("/me")).status === 401, "API /me without a key: 401");
check((await api("/me", "not-a-real-key")).status === 401, "API /me with a wrong key: 401");
const meA = await api("/me", ALPHA);
check(meA.body?.organization_id === "org_demo_alpha", "API /me with the alpha key: org_demo_alpha", JSON.stringify(meA.body));
const meB = await api("/me", BRAVO);
check(meB.body?.organization_id === "org_demo_bravo", "API /me with the bravo key: org_demo_bravo", JSON.stringify(meB.body));

const listA = (await api("/decisions", ALPHA)).body;
check(listA?.run, "API alpha has a run");
const demo = listA.items.filter((i) => i.line_id.startsWith("DEMO-"));
const counts = Object.fromEntries(["CLAIM", "DO_NOT_CLAIM", "REVIEW"].map((d) => [d, demo.filter((i) => i.decision === d).length]));
check(
  demo.length === 10 && counts.CLAIM === 3 && counts.DO_NOT_CLAIM === 3 && counts.REVIEW === 4,
  "API alpha's newest run has the 10 demo lines: 3 CLAIM, 3 DO NOT CLAIM, 4 REVIEW",
  JSON.stringify(counts),
);
check(listA.totals?.ALL?.count === listA.items.length, "API totals cover the whole run", JSON.stringify(listA.totals?.ALL));

const listB = (await api("/decisions", BRAVO)).body;
check(listB?.run && listB.items.length > 0, "API bravo has its own run");
const alphaIds = new Set(listA.items.map((i) => i.record_id));
check(!listB.items.some((i) => alphaIds.has(i.record_id)), "API bravo's list has none of alpha's decisions");
check(!listB.items.some((i) => i.line_id.startsWith("DEMO-")), "API bravo's list has no demo (alpha) lines");
const aId = listA.items[0].record_id;
const bId = listB.items[0].record_id;
check((await api(`/decisions/${encodeURIComponent(aId)}`, BRAVO)).status === 404, "API bravo fetching an alpha decision by ID: 404");
check((await api(`/decisions/${encodeURIComponent(bId)}`, ALPHA)).status === 404, "API alpha fetching a bravo decision by ID: 404");
check((await api(`/decisions/${encodeURIComponent(aId)}`, ALPHA)).status === 200, "API alpha fetching its own decision: 200");

// --- UI --------------------------------------------------------------------------------
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await (await browser.newContext()).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const first = await page.goto(`${UI}/`);
check(page.url().startsWith(`${UI}/login`), "UI without a session redirects to sign-in", `${first?.status()} ${page.url()}`);
await page.fill("#key", "not-a-real-key");
await page.click("button[type=submit]");
// The form's own error (Next.js also renders a route announcer with role="alert").
await page.locator("#key-error").waitFor({ timeout: 15000 });
check((await page.locator("#key-error").innerText()).includes("not accepted"), "UI refuses a wrong key");

await page.fill("#key", ALPHA);
await page.click("button[type=submit]");
await page.waitForURL(`${UI}/`, { timeout: 20000 });
check(true, "UI signs in with the alpha key");
check((await page.locator("header").innerText()).includes("org_demo_alpha"), "UI top bar names org_demo_alpha (GET /me)");
check((await page.evaluate(() => document.cookie)) === "", "UI key cookie is not readable by page scripts");
const tile = await page.getByRole("link", { name: /^All charges:/ }).innerText();
check(tile.includes(String(listA.items.length)), "UI decisions list shows the run's charge count", tile.replace(/\s+/g, " "));
await page.locator('a[href$="-DEMO-F01-1"]:visible').first().click();
await page.getByRole("heading", { level: 1, name: "DEMO-F01-1" }).waitFor({ timeout: 20000 });
check((await page.locator("main").innerText()).includes("CLAIM"), "UI opens a decision (DEMO-F01-1, CLAIM)");
await page.getByRole("button", { name: /Sign out/ }).first().click();
await page.waitForURL(/\/login/, { timeout: 15000 });
check(true, "UI signs out");
check(errors.length === 0, "UI raised no page errors", errors.join(" | "));
await browser.close();

console.log(`smoke-live: all ${passed} checks passed (${API}, ${UI})`);
