import { ArrowRight, ChevronDown, TriangleAlert } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { headline } from "@/lib/reasons";
import type { DecisionRecord } from "@/lib/types";
import { dateTime, sentence } from "@/lib/utils";

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-4">
      <dt className="text-xs font-medium text-muted-foreground">{name}</dt>
      <dd className="min-w-0 break-words text-sm">{children}</dd>
    </div>
  );
}

/** Plain-English reason and next step first; the engine's own words under "Technical detail". */
export function WhyCard({ r }: { r: DecisionRecord }) {
  return (
    <Card aria-labelledby="why-title">
      <div className="p-4 sm:p-5">
        <p id="why-title" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Why
        </p>
        <p className="mt-1.5 text-base font-medium leading-snug sm:text-lg">
          {headline(r.rule_id, r.subject.charge_type, r.reason)}
        </p>
        {r.next_action && (
          <div className="mt-4 flex gap-3 rounded-md bg-surface-2 p-3">
            <ArrowRight className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
            <div>
              <p className="text-xs font-medium text-muted-foreground">What to do next</p>
              <p className="mt-0.5 text-sm">{r.next_action}</p>
            </div>
          </div>
        )}
        {r.warnings.length > 0 && (
          <ul className="mt-3 space-y-1">
            {r.warnings.map((w) => (
              <li key={w} className="flex items-start gap-2 text-sm text-review">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>{w.charAt(0).toUpperCase() + w.slice(1)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Collapsible className="border-t border-border">
        <CollapsibleTrigger className="group flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-medium text-muted-foreground hover:text-foreground sm:px-5">
          Technical detail
          <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" aria-hidden />
        </CollapsibleTrigger>
        <CollapsibleContent className="px-4 pb-4 sm:px-5">
          <dl className="divide-y divide-border">
            <Row name="Engine reason">{r.reason}</Row>
            <Row name="Rule">
              <code className="font-mono text-xs">{r.rule_id}</code>
            </Row>
            <Row name="Rule path">
              <code className="break-words font-mono text-xs">{r.rule_path.join(" → ")}</code>
            </Row>
            <Row name="Evidence status">{sentence(r.evidence_status)}</Row>
            <Row name="Reason code">{r.reason_code ? <code className="font-mono text-xs">{r.reason_code}</code> : "none"}</Row>
            {r.coverage !== null && (
              <Row name="Coverage">
                <span className="num">{r.coverage}</span> of the charged units
              </Row>
            )}
            <Row name="Decided by">
              <code className="font-mono text-xs">{r.outcome.decided_by}</code>, {dateTime(r.outcome.decided_at)}
            </Row>
          </dl>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
