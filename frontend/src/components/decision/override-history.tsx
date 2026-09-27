import { ArrowRight } from "lucide-react";

import { DecisionChip } from "@/components/status";
import type { OverrideRecord } from "@/lib/types";
import { dateTime } from "@/lib/utils";

/** Overrides of this decision, newest first, as a timeline. */
export function OverrideHistory({ overrides }: { overrides: OverrideRecord[] }) {
  if (overrides.length === 0) {
    return <p className="text-sm text-muted-foreground">No reviewer has changed this decision.</p>;
  }
  const items = [...overrides].reverse();
  return (
    <ol className="relative">
      {items.map((o, idx) => (
        <li key={o.sequence} className="flex gap-3">
          <div className="relative flex w-3 shrink-0 justify-center" aria-hidden>
            {idx < items.length - 1 && <span className="absolute bottom-0 top-3 w-px bg-border-strong" />}
            <span className="relative mt-1.5 block size-2.5 rounded-full bg-foreground" />
          </div>
          <div className={idx < items.length - 1 ? "min-w-0 pb-4" : "min-w-0"}>
            <div className="flex flex-wrap items-center gap-1.5">
              <DecisionChip value={o.override.original_decision} size="sm" />
              <ArrowRight className="size-3.5 text-muted-foreground" aria-label="changed to" />
              <DecisionChip value={o.override.new_decision} size="sm" />
            </div>
            <p className="mt-1.5 break-words text-sm">&ldquo;{o.override.reason}&rdquo;</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {o.override.reviewer} · {dateTime(o.override.at)} · #{o.sequence}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
