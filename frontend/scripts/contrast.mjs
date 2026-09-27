// WCAG AA check of the colour tokens in src/app/globals.css, both themes: `node scripts/contrast.mjs`.
import fs from "node:fs";
const css = fs.readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const blocks = { light: css.split("@media (prefers-color-scheme: dark)")[0], dark: css.split("@media (prefers-color-scheme: dark)")[1].split("@theme")[0] };
const lum = (h) => { const c = [1,3,5].map(i => parseInt(h.slice(i,i+2),16)/255).map(v => v<=0.03928? v/12.92 : ((v+0.055)/1.055)**2.4); return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]; };
const ratio = (a,b) => { const [x,y]=[lum(a),lum(b)].sort((p,q)=>q-p); return (x+0.05)/(y+0.05); };
const pairs = [["foreground","background"],["foreground","surface"],["muted-foreground","surface"],["muted-foreground","surface-2"],["muted-foreground","background"],["accent-text","surface"],["accent-text","accent-soft"],["accent-foreground","accent"],
["claim","claim-soft"],["claim","surface"],["dnc","dnc-soft"],["dnc","surface"],["review","review-soft"],["review","surface"],["fail","fail-soft"],["fail","surface"],["pass","pass-soft"],["unc","unc-soft"]];
let bad = 0;
for (const [mode, b] of Object.entries(blocks)) {
  const v = Object.fromEntries([...b.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/g)].map(m => [m[1], m[2]]));
  for (const [f, g] of pairs) { const r = ratio(v[f], v[g]); if (r < 4.5) bad++; console.log(`${mode.padEnd(5)} ${f} on ${g}: ${r.toFixed(2)}${r < 4.5 ? "  FAIL" : ""}`); }
}
console.log(bad ? `${bad} pair(s) below 4.5:1` : "all pairs >= 4.5:1 (WCAG AA, normal text)");
process.exit(bad ? 1 : 0);
