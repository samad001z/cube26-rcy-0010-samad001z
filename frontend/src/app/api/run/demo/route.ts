import { readFile } from "node:fs/promises";
import path from "node:path";

import type { NextRequest } from "next/server";

import { KEY_COOKIE } from "@/lib/api";

import { forwardToAgent } from "../forward";

// Runs the demo data in demo/ (repo root) through POST /agent, exactly like an upload.
// Demo data only: never data/ or eval/. ALIBI_DEMO_DIR overrides where it is read from.
const PODS = ["receiving", "prep", "pack", "returns"] as const;

function demoDir(): string {
  // Read at request time from the repository, not bundled (hence turbopackIgnore).
  return process.env.ALIBI_DEMO_DIR ?? path.join(/*turbopackIgnore: true*/ process.cwd(), "..", "demo");
}

export async function POST(request: NextRequest) {
  const key = request.cookies.get(KEY_COOKIE)?.value;
  if (!key) return Response.json({ detail: "not signed in" }, { status: 401 });
  const dir = demoDir();
  const form = new FormData();
  try {
    const csv = (name: string) => readFile(path.join(dir, name)).then((b) => new Blob([b], { type: "text/csv" }));
    form.append("report", await csv("fee_report_demo.csv"), "fee_report_demo.csv");
    for (const pod of PODS) {
      form.append("upstream", await csv(`upstream/${pod}_demo.csv`), `${pod}_demo.csv`);
    }
  } catch {
    return Response.json({ detail: `the demo files were not found in ${dir}` }, { status: 500 });
  }
  return forwardToAgent(key, form);
}
