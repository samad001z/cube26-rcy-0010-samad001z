import { CircleAlert, FileUp, Hash, History, Sparkles } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";

import { DecisionsTable } from "@/components/decisions/decisions-table";
import { KpiTiles } from "@/components/decisions/kpi-tiles";
import { EmptyState, Notice } from "@/components/notice";
import { Button } from "@/components/ui/button";
import { BackendError, api } from "@/lib/api";
import type { DecisionList, DecisionValue } from "@/lib/types";
import { dateTime, shortId } from "@/lib/utils";

export const metadata: Metadata = { title: "Decisions" };

const DECISIONS: DecisionValue[] = ["REVIEW", "CLAIM", "DO_NOT_CLAIM"];

export default async function DecisionsPage({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const param = (k: string) => (typeof sp[k] === "string" && sp[k] ? (sp[k] as string) : undefined);
  const runParam = param("run");
  const show = DECISIONS.includes(param("show") as DecisionValue) ? (param("show") as DecisionValue) : undefined;
  const typeParam = param("type");
  const ruleParam = param("rule");

  let data: DecisionList;
  try {
    const q = new URLSearchParams();
    if (runParam) q.set("run_id", runParam);
    if (show) q.set("decision", show);
    if (typeParam) q.set("charge_type", typeParam);
    if (ruleParam) q.set("rule_id", ruleParam);
    data = await api<DecisionList>(`/decisions${q.size ? `?${q}` : ""}`);
  } catch (err) {
    unstable_rethrow(err); // let redirect() to the login page through
    const msg = err instanceof BackendError ? `${err.status}: ${err.message}` : "unknown error";
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold tracking-tight">Decisions</h1>
        <Notice tone="error" title="Decisions could not be loaded">
          The Alibi API answered {msg}. Nothing was changed. Try again in a moment.
        </Notice>
      </div>
    );
  }

  if (!data.run) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold tracking-tight">Decisions</h1>
        <EmptyState
          icon={<FileUp aria-hidden />}
          title="No runs yet"
          action={
            <>
              <Button asChild variant="primary">
                <Link href="/run">
                  <FileUp aria-hidden />
                  Run a report
                </Link>
              </Button>
              <Button asChild>
                <Link href="/run#demo">
                  <Sparkles aria-hidden />
                  Load demo data
                </Link>
              </Button>
            </>
          }
        >
          Upload a fee report with the upstream evidence files, and every charge gets a decision
          with its reason and evidence.
        </EmptyState>
      </div>
    );
  }

  const run = data.run;
  const overridden = data.items.filter((i) => i.override_count > 0).length;
  const pending = data.items.filter((i) => i.status === "pending").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Decisions</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Hash className="size-3.5" aria-hidden />
              Run <span className="font-mono text-xs text-foreground">{shortId(run.run_id)}</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <History className="size-3.5" aria-hidden />
              {dateTime(run.decided_at)}
            </span>
            {overridden > 0 && (
              <span>
                <span className="num text-foreground">{overridden}</span> changed by a reviewer
              </span>
            )}
          </p>
        </div>
      </div>

      {pending > 0 && (
        <Notice tone="error" title={`${pending} charge${pending === 1 ? "" : "s"} could not be evaluated`}>
          The engine or the database failed on {pending === 1 ? "it" : "them"}, so{" "}
          {pending === 1 ? "it was" : "they were"} kept as REVIEW, pending. Nothing was dropped.
        </Notice>
      )}

      <KpiTiles totals={data.totals} active={show} params={{ run: runParam, type: typeParam, rule: ruleParam }} />

      {data.items.some((i) => i.integrity_problems.length > 0) && (
        <Notice tone="error" title="Some stored history does not verify">
          Rows marked <CircleAlert className="inline size-3.5" aria-label="history does not verify" /> have
          an override history whose hashes do not check out. Overrides on them are blocked.
        </Notice>
      )}

      <DecisionsTable
        items={data.items}
        total={run.charges}
        facets={data.facets}
        filters={{ run: runParam, show, type: typeParam, rule: ruleParam }}
      />
    </div>
  );
}
