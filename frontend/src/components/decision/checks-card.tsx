import { ListChecks } from "lucide-react";

import { Verdict } from "@/components/status";
import { Card, CardHeader } from "@/components/ui/card";
import { Tooltip } from "@/components/ui/tooltip";
import { checkName, confidenceExplanation } from "@/lib/checks";
import type { Check } from "@/lib/types";

export function ChecksCard({ checks }: { checks: Check[] }) {
  return (
    <Card>
      <CardHeader
        icon={<ListChecks aria-hidden />}
        title="Recovery checks"
        description="What the engine checked for this charge before deciding."
      />
      <ul className="divide-y divide-border">
        {checks.map((c) => (
          <li key={c.check_key} className="grid grid-cols-[96px_minmax(0,1fr)] gap-3 px-4 py-3 sm:grid-cols-[112px_minmax(0,1fr)_auto]">
            <Verdict value={c.verdict} className="pt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-medium">{checkName(c.check_key)}</p>
              {c.detail && <p className="mt-0.5 break-words text-xs text-muted-foreground">{c.detail}</p>}
              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{c.check_key}</p>
            </div>
            {c.confidence && (
              <p className="col-start-2 text-xs text-muted-foreground sm:col-start-3 sm:text-right">
                <Tooltip content={confidenceExplanation(c.verdict)}>
                  <button type="button" className="rounded underline decoration-dotted underline-offset-2">
                    <span className="sr-only">Routing confidence (not a probability of a favourable outcome): </span>
                    <span className="num">{c.confidence}</span>
                  </button>
                </Tooltip>
              </p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
