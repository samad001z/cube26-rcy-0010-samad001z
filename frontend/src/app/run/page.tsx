import { redirect } from "next/navigation";

import { currentKey } from "@/lib/api";

import { RunForm } from "./run-form";

export default async function RunPage() {
  if (!(await currentKey())) redirect("/login");
  return (
    <div className="max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">New run</h1>
        <p className="mt-1 text-sm text-muted">
          Upload a fee, adjustment or reimbursement report and one evidence file from each upstream pod. Every
          charge gets a decision, judged as of today (UTC). Rows for other organisations are skipped; rows that
          cannot be read are quarantined, not guessed.
        </p>
      </div>
      <RunForm />
    </div>
  );
}
