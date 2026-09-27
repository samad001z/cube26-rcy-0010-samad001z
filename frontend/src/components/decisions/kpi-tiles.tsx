import { Layers } from "lucide-react";
import Link from "next/link";

import { DECISION } from "@/components/status";
import type { DecisionValue } from "@/lib/types";
import { cn } from "@/lib/utils";

const HINT: Record<DecisionValue, string> = {
  CLAIM: "Evidence shows the charge is wrong",
  DO_NOT_CLAIM: "Charge stands, repaid or out of time",
  REVIEW: "A person decides",
};

const ICON_TONE: Record<DecisionValue, string> = {
  CLAIM: "bg-claim-soft text-claim",
  DO_NOT_CLAIM: "bg-dnc-soft text-dnc",
  REVIEW: "bg-review-soft text-review",
};

/** Four tiles of equal weight. Counts only: amounts are not added up in the UI. */
export function KpiTiles({
  total,
  counts,
  active,
  params,
}: {
  total: number;
  counts: Partial<Record<DecisionValue, number>>;
  active?: DecisionValue;
  params: { run?: string; type?: string; rule?: string };
}) {
  const href = (show?: DecisionValue) => {
    const q = new URLSearchParams(
      Object.entries({ ...params, show }).filter((e): e is [string, string] => !!e[1]),
    );
    return q.size ? `/?${q}` : "/";
  };
  const tile =
    "group flex min-h-[104px] flex-col gap-3 rounded-lg border bg-surface p-4 shadow-card transition-colors hover:border-border-strong";
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Link
        href={href()}
        aria-current={!active ? "true" : undefined}
        className={cn(tile, !active ? "border-accent ring-1 ring-accent" : "border-border")}
      >
        <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <span className="flex size-6 items-center justify-center rounded-md bg-surface-2 text-foreground">
            <Layers className="size-3.5" aria-hidden />
          </span>
          All charges
        </span>
        <span>
          <span className="num block text-2xl font-semibold tracking-tight">{total}</span>
          <span className="text-xs text-muted-foreground">Every line in this run</span>
        </span>
      </Link>
      {(["CLAIM", "DO_NOT_CLAIM", "REVIEW"] as const).map((d) => {
        const Icon = DECISION[d].icon;
        const on = active === d;
        return (
          <Link
            key={d}
            href={href(on ? undefined : d)}
            aria-current={on ? "true" : undefined}
            aria-label={`${DECISION[d].word}: ${counts[d] ?? 0} charges. ${on ? "Showing only these; select to show all." : "Select to show only these."}`}
            className={cn(tile, on ? "border-accent ring-1 ring-accent" : "border-border")}
          >
            <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <span className={cn("flex size-6 items-center justify-center rounded-md", ICON_TONE[d])}>
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className="truncate">{DECISION[d].word}</span>
            </span>
            <span>
              <span className="num block text-2xl font-semibold tracking-tight">{counts[d] ?? 0}</span>
              <span className="text-xs text-muted-foreground">{HINT[d]}</span>
            </span>
          </Link>
        );
      })}
    </div>
  );
}
