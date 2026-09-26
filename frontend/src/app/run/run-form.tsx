"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

const PODS = ["receiving", "prep", "pack", "returns"] as const;

export function RunForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setError(null);
    const input = new FormData(ev.currentTarget);
    const out = new FormData();
    const report = input.get("report");
    if (!(report instanceof File) || report.size === 0) return setError("Choose the report file.");
    out.append("report", report, report.name);
    for (const pod of PODS) {
      const f = input.get(pod);
      if (!(f instanceof File) || f.size === 0) return setError(`Choose the ${pod} file.`);
      // The backend expects <pod>_<anything>.csv; keep the operator's name when it already fits.
      const name = f.name.startsWith(`${pod}_`) && f.name.endsWith(".csv") ? f.name : `${pod}_upload.csv`;
      out.append("upstream", f, name);
    }
    setBusy(true);
    try {
      const res = await fetch("/api/run", { method: "POST", body: out });
      if (res.status === 401) return router.push("/login?expired=1");
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
        return setError(`${res.status}: ${detail}`);
      }
      const runId = res.headers.get("X-Alibi-Run-Id");
      router.push(runId ? `/?run=${runId}` : "/");
      router.refresh();
    } catch {
      setError("The upload failed. Check the connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  const input = "mt-1 block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-dnc-bg file:px-3 file:py-1.5 file:text-sm file:font-medium";
  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-line bg-surface p-4">
      <div>
        <label htmlFor="report" className="text-sm font-medium">
          Report (CSV)
        </label>
        <input id="report" name="report" type="file" accept=".csv,text/csv" className={input} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {PODS.map((pod) => (
          <div key={pod}>
            <label htmlFor={pod} className="text-sm font-medium capitalize">
              {pod} evidence (CSV)
            </label>
            <input id={pod} name={pod} type="file" accept=".csv,text/csv" className={input} />
          </div>
        ))}
      </div>
      {error && (
        <p role="alert" className="text-sm text-fail">
          {error}
        </p>
      )}
      <button disabled={busy} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg disabled:opacity-60">
        {busy ? "Deciding every charge…" : "Run"}
      </button>
    </form>
  );
}
