import { Coins } from "lucide-react";

import { Money } from "@/components/money";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { DecisionRecord } from "@/lib/types";

export function AmountsCard({ r }: { r: DecisionRecord }) {
  const rows = [
    { name: "Charged", amount: r.amount_charged },
    { name: "Already reimbursed", amount: r.amount_reimbursed },
    { name: "Claim", amount: r.claim?.amount ?? null },
  ];
  return (
    <Card>
      <CardHeader icon={<Coins aria-hidden />} title="Amounts" description="As computed by the backend." />
      <CardBody>
        <dl className="space-y-2">
          {rows.map((x) => (
            <div key={x.name} className="flex items-baseline justify-between gap-3">
              <dt className="text-sm text-muted-foreground">{x.name}</dt>
              <dd className="text-sm font-medium">
                <Money amount={x.amount} currency={r.currency} />
              </dd>
            </div>
          ))}
        </dl>
        {r.claim && r.claim.computation.length > 0 && (
          <div className="mt-3 border-t border-border pt-3">
            <p className="text-xs font-medium text-muted-foreground">How the claim was worked out</p>
            <ol className="mt-1.5 space-y-0.5 font-mono text-[11px] text-muted-foreground">
              {r.claim.computation.map((line) => (
                <li key={line} className="break-words">
                  {line}
                </li>
              ))}
            </ol>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
