// Prebuild: copy the demo files (../demo) into demo-data/ so the "Load demo data" route has
// them on hosts that deploy only this folder (Vercel). demo/ stays the single source; this
// copy is git-ignored and rebuilt on every build. Fails the build if demo/ is missing.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";

const root = path.dirname(new URL(import.meta.url).pathname);
const src = path.resolve(root, "..", "..", "demo");
const dst = path.resolve(root, "..", "demo-data");
if (!existsSync(path.join(src, "fee_report_demo.csv"))) {
  console.error(`copy-demo: ${src}/fee_report_demo.csv not found (on Vercel, keep "Include files outside the root directory" on)`);
  process.exit(1);
}
rmSync(dst, { recursive: true, force: true });
mkdirSync(path.join(dst, "upstream"), { recursive: true });
cpSync(path.join(src, "fee_report_demo.csv"), path.join(dst, "fee_report_demo.csv"));
for (const f of readdirSync(path.join(src, "upstream")).filter((f) => f.endsWith(".csv"))) {
  cpSync(path.join(src, "upstream", f), path.join(dst, "upstream", f));
}
console.log(`copy-demo: ${src} -> ${dst}`);
