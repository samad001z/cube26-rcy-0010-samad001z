// Headless screenshots of the review UI for the README, light and dark, plus layout checks.
//
//   BASE_URL=http://localhost:3000 ALIBI_KEY=<org_demo_alpha key> node scripts/screenshots.mjs
//
// Needs the API and the UI running, with the demo run (`make demo` or Load demo data) as the
// newest run of org_demo_alpha. Writes docs/screenshots/*.png (OUT overrides the folder) and
// fails if any page scrolls sideways at phone width or logs a console error.
import { mkdirSync } from "node:fs";
import path from "node:path";

import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const KEY = process.env.ALIBI_KEY;
const OUT = process.env.OUT ?? path.join(path.dirname(new URL(import.meta.url).pathname), "..", "..", "docs", "screenshots");
const DETAIL_LINE = process.env.DETAIL_LINE ?? "DEMO-F01-1"; // a CLAIM with cited prep evidence
const OVERRIDE_LINE = process.env.OVERRIDE_LINE ?? "DEMO-F08-1"; // a loss event: CLAIM is refused
if (!KEY) throw new Error("set ALIBI_KEY");
mkdirSync(OUT, { recursive: true });

const problems = [];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

async function session(scheme, viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ colorScheme: scheme, viewport, deviceScaleFactor: 2, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && problems.push(`${scheme} console error: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`${scheme} page error: ${e.message}`));
  return { ctx, page };
}

async function signIn(page) {
  await page.goto(`${BASE}/login`);
  await page.fill("#key", KEY);
  await page.click("button[type=submit]");
  await page.waitForURL(`${BASE}/`);
}

async function openLine(page, line) {
  await page.goto(`${BASE}/`);
  await page.locator(`a[href$="-${line}"]:visible`).first().click();
  await page.waitForURL(/\/decisions\//);
  await page.getByRole("heading", { level: 1, name: line }).waitFor();
}

/** Whole page without sticky-header artefacts: grow the viewport to the page height. */
async function tallShot(page, file) {
  const size = page.viewportSize();
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: size.width, height });
  await page.screenshot({ path: file });
  await page.setViewportSize(size);
}

async function noSideScroll(page, label) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 0) problems.push(`${label}: page scrolls sideways by ${over}px`);
  return over;
}

for (const scheme of ["light", "dark"]) {
  const { ctx, page } = await session(scheme);
  await page.goto(`${BASE}/login`);
  await page.fill("#key", "not-a-real-key");
  await page.click("button[type=submit]");
  await page.getByRole("alert").waitFor();
  await page.fill("#key", "");
  await page.screenshot({ path: `${OUT}/signin-${scheme}.png` });

  await signIn(page);
  await page.getByRole("heading", { name: "Decisions" }).waitFor();
  await tallShot(page, `${OUT}/decisions-${scheme}.png`);

  await openLine(page, DETAIL_LINE);
  await page.getByRole("button", { name: /Record integrity/ }).click();
  await tallShot(page, `${OUT}/detail-${scheme}.png`);

  await openLine(page, OVERRIDE_LINE);
  await page.getByRole("button", { name: "Override decision" }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("radio", { name: /DO NOT CLAIM/ }).click();
  await page.getByLabel(/Reason/).fill("Return DEMO-RTN-08 matches this unit; the loss did not happen.");
  await page.getByLabel("Reviewer").fill("Demo Reviewer");
  await page.screenshot({ path: `${OUT}/override-${scheme}.png` });
  await ctx.close();
}

// Phone width: every page, no horizontal scroll; one screenshot of the list.
{
  const { ctx, page } = await session("light", { width: 375, height: 812 });
  await page.goto(`${BASE}/login`);
  await noSideScroll(page, "375px /login");
  await signIn(page);
  await page.getByRole("heading", { name: "Decisions" }).waitFor();
  await noSideScroll(page, "375px /");
  await tallShot(page, `${OUT}/decisions-phone-light.png`);
  for (const line of [DETAIL_LINE, OVERRIDE_LINE]) {
    await openLine(page, line);
    await noSideScroll(page, `375px ${line}`);
  }
  for (const p of ["/run", "/about"]) {
    await page.goto(`${BASE}${p}`);
    await noSideScroll(page, `375px ${p}`);
  }
  await ctx.close();
}

// Keyboard: the first Tab stops show a visible focus outline.
{
  const { ctx, page } = await session("light");
  await signIn(page);
  for (let i = 0; i < 4; i++) await page.keyboard.press("Tab");
  const outline = await page.evaluate(() => {
    const el = document.activeElement;
    const s = el && getComputedStyle(el);
    return s ? `${s.outlineStyle} ${s.outlineWidth}` : "none";
  });
  if (!outline.startsWith("solid")) problems.push(`focus outline after Tab is "${outline}"`);
  else console.log(`focus outline after 4 Tabs: ${outline}`);
  await ctx.close();
}

await browser.close();
console.log(`screenshots written to ${OUT}`);
if (problems.length) {
  console.log("problems:\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log("no console errors; no horizontal scroll at 375px");
