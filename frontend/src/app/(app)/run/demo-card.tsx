"use client";

import { CircleAlert, LoaderCircle, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import { readError } from "./read-error";

export function DemoCard() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/run/demo", { method: "POST" });
      if (res.status === 401) return router.push("/login?expired=1");
      if (!res.ok) return setError(await readError(res));
      const runId = res.headers.get("X-Alibi-Run-Id");
      router.push(runId ? `/?run=${runId}` : "/");
      router.refresh();
    } catch {
      setError("The request failed. Check the connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="demo" className="scroll-mt-20">
      <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="flex gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-text">
            <Sparkles className="size-4" aria-hidden />
          </span>
          <div>
            <h2 className="text-sm font-semibold">Load demo data</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              A 10-line made-up fee report with its upstream files, built to show CLAIM, DO NOT CLAIM and REVIEW in
              one run. Demo data only; its rows belong to <span className="font-mono text-xs">org_demo_alpha</span>.
            </p>
          </div>
        </div>
        <Button onClick={load} disabled={busy} className="sm:w-auto">
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
          {busy ? "Deciding…" : "Load demo data"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="flex items-start gap-2 border-t border-border px-4 py-3 text-sm text-fail sm:px-5">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </Card>
  );
}
