import { Layers } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { DECISION } from "@/components/status";
import type { DecisionValue, Total } from "@/lib/types";
import { cn } from "@/lib/utils";

const HINT: Record<DecisionValue | "ALL", string> = {
  ALL: "Every line in this run",
  CLAIM: "Evidence shows the charge is wrong",
  DO_NOT_CLAIM: "Charge stands, repaid or out of time",
  REVIEW: "A person decides",
};

const ICON_TONE: Record<DecisionValue, string> = {
  CLAIM: "bg-claim-soft text-claim",
  DO_NOT_CLAIM: "bg-dnc-soft text-dnc",
  REVIEW: "bg-review-soft text-review",
};

/** Amounts per currency exactly as the backend summed them ("6.25 USD"), or a dash. */
function Amounts({ values }: { values: Record<string, string> | undefined }) {
  const entries = Object.entries(values ?? {});
  if (entries.length === 0) {
    return (
      <span className="text-muted-foreground">
        <span aria-hidden>—</span>
        <span className="sr-only">none</span>
      </span>
    );
  }
  return (
    <span className="num">
      {entries.map(([currency, amount], i) => (
        <span key={currency}>
          {i > 0 && " · "}
          {amount}
          <span className="ml-1 text-muted-foreground">{currency}</span>
        </span>
      ))}
    </span>
  );
}

function Tile({
  href,
  on,
  icon,
  iconTone,
  label,
  total,
  hint,
  ariaLabel,
}: {
  href: string;
  on: boolean;
  icon: ReactNode;
  iconTone: string;
  label: string;
  total: Total | undefined;
  hint: string;
  ariaLabel: string;
}) {
  return (
    <Link
      href={href}
      aria-current={on ? "true" : undefined}
      aria-label={ariaLabel}
      className={cn(
        "flex flex-col gap-3 rounded-lg border bg-surface p-4 shadow-card transition-colors hover:border-border-strong",
        on ? "border-accent ring-1 ring-accent" : "border-border",
      )}
    >
      <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-md", iconTone)}>{icon}</span>
        <span className="truncate">{label}</span>
      </span>
      <span>
        <span className="num block text-2xl font-semibold tracking-tight">{total?.count ?? 0}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </span>
      <dl className="mt-auto space-y-1 border-t border-border pt-2 text-xs">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          <dt className="text-muted-foreground">Fees charged</dt>
          <dd className="font-medium">
            <Amounts values={total?.fees_charged} />
          </dd>
        </div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          <dt className="text-muted-foreground">Claimable</dt>
          <dd className="font-medium">
            <Amounts values={total?.claimable} />
          </dd>
        </div>
      </dl>
    </Link>
  );
}

/**
 * Four tiles of equal weight. Counts and amounts come from the backend (`totals`, Decimal
 * sums as strings); nothing is added up here. Fees charged counts fee lines only.
 */
export function KpiTiles({
  totals,
  active,
  params,
}: {
  totals: Partial<Record<DecisionValue | "ALL", Total>>;
  active?: DecisionValue;
  params: { run?: string; type?: string; rule?: string };
}) {
  const href = (show?: DecisionValue) => {
    const q = new URLSearchParams(Object.entries({ ...params, show }).filter((e): e is [string, string] => !!e[1]));
    return q.size ? `/?${q}` : "/";
  };
  return (
    <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">
      <Tile
        href={href()}
        on={!active}
        icon={<Layers className="size-3.5" aria-hidden />}
        iconTone="bg-surface-2 text-foreground"
        label="All charges"
        total={totals.ALL}
        hint={HINT.ALL}
        ariaLabel={`All charges: ${totals.ALL?.count ?? 0}. Select to show every decision.`}
      />
      {(["CLAIM", "DO_NOT_CLAIM", "REVIEW"] as const).map((d) => {
        const Icon = DECISION[d].icon;
        const on = active === d;
        return (
          <Tile
            key={d}
            href={href(on ? undefined : d)}
            on={on}
            icon={<Icon className="size-3.5" aria-hidden />}
            iconTone={ICON_TONE[d]}
            label={DECISION[d].word}
            total={totals[d]}
            hint={HINT[d]}
            ariaLabel={`${DECISION[d].word}: ${totals[d]?.count ?? 0} charges. ${
              on ? "Showing only these; select to show all." : "Select to show only these."
            }`}
          />
        );
      })}
    </div>
  );
}
