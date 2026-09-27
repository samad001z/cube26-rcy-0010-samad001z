import type { Metadata } from "next";

import { DemoCard } from "./demo-card";
import { RunForm } from "./run-form";

export const metadata: Metadata = { title: "Run a report" };

export default function RunPage() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Run a report</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every charge gets a decision, judged as of today (UTC). A run decides every charge stored for your
          organisation, including ones uploaded earlier. Rows for other organisations are skipped; rows that
          cannot be read are quarantined, not guessed.
        </p>
      </div>
      <DemoCard />
      <RunForm />
    </div>
  );
}
