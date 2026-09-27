"use client";

import { CircleAlert, FileSpreadsheet, LoaderCircle, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { readError } from "./read-error";

const PODS = ["receiving", "prep", "pack", "returns"] as const;
const FIELDS = [
  { name: "report", label: "Fee, adjustment or reimbursement report" },
  ...PODS.map((p) => ({ name: p, label: `${p.charAt(0).toUpperCase()}${p.slice(1)} evidence` })),
];

function FileField({ name, label, file, onPick }: { name: string; label: string; file?: string; onPick: (f?: string) => void }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      <label
        htmlFor={name}
        className={cn(
          "flex h-10 cursor-pointer items-center gap-2 rounded-md border border-dashed px-3 text-sm focus-within:outline-2 focus-within:outline-ring hover:bg-surface-2",
          file ? "border-border-strong" : "border-input text-muted-foreground",
        )}
      >
        <FileSpreadsheet className="size-4 shrink-0" aria-hidden />
        <span className="truncate">{file ?? "Choose a CSV file"}</span>
        <input
          id={name}
          name={name}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => onPick(e.target.files?.[0]?.name)}
        />
      </label>
    </div>
  );
}

export function RunForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<string, string | undefined>>({});

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
      if (!res.ok) return setError(await readError(res));
      const runId = res.headers.get("X-Alibi-Run-Id");
      router.push(runId ? `/?run=${runId}` : "/");
      router.refresh();
    } catch {
      setError("The upload failed. Check the connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        icon={<FileSpreadsheet aria-hidden />}
        title="Upload your own files"
        description="One report and one evidence file from each upstream pod, all CSV."
      />
      <form onSubmit={submit} className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          {FIELDS.map((f, i) => (
            <div key={f.name} className={i === 0 ? "sm:col-span-2" : undefined}>
              <FileField
                name={f.name}
                label={f.label}
                file={picked[f.name]}
                onPick={(n) => setPicked((p) => ({ ...p, [f.name]: n }))}
              />
            </div>
          ))}
        </div>
        {error && (
          <p role="alert" className="flex items-start gap-2 text-sm text-fail">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <Play aria-hidden />}
          {busy ? "Deciding every charge…" : "Run"}
        </Button>
      </form>
    </Card>
  );
}
