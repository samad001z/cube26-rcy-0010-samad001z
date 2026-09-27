import { ChevronDown, Fingerprint, ShieldAlert, ShieldCheck } from "lucide-react";

import { HashValue } from "@/components/copy-button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { DecisionDetail } from "@/lib/types";

function Item({ name, value, ok }: { name: string; value: string | null; ok?: boolean }) {
  return (
    <div className="py-2.5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {name}
        {ok === true && <ShieldCheck className="size-3.5 text-pass" aria-label="verifies" />}
        {ok === false && <ShieldAlert className="size-3.5 text-fail" aria-label="does not verify" />}
      </p>
      <HashValue value={value} label={name} />
    </div>
  );
}

/** Content hashes of everything the decision rests on, collapsed by default. */
export function IntegrityCard({ d }: { d: DecisionDetail }) {
  const r = d.record;
  const eng = d.engine_record;
  const badEvidence = d.evidence.filter((e) => !(e.hash_matches_decision && e.record_hash_verifies)).length;
  const ok = d.integrity_problems.length === 0 && badEvidence === 0;
  return (
    <Card>
      <Collapsible>
        <CollapsibleTrigger className="group flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
          <span className="min-w-0">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Fingerprint className="size-4 text-muted-foreground" aria-hidden />
              Record integrity
            </span>
            <span className={`mt-0.5 flex items-center gap-1.5 text-xs ${ok ? "text-muted-foreground" : "text-fail"}`}>
              {ok ? <ShieldCheck className="size-3.5 text-pass" aria-hidden /> : <ShieldAlert className="size-3.5" aria-hidden />}
              {ok ? "Every stored hash verifies" : "Some stored hashes do not verify"}
            </span>
          </span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" aria-hidden />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-border px-4 pb-2">
          <div className="divide-y divide-border">
            <Item name="Decision record ID" value={r.record_id} />
            <Item name="Engine record hash" value={eng.content_hash} />
            {d.overrides.length > 0 && <Item name="Effective record hash" value={r.content_hash} />}
            <Item name="Charge hash" value={r.subject.charge_content_hash} />
            <Item name="Rules hash" value={r.rules_hash} />
            <Item name="Engine config hash" value={r.config_hash} />
            {d.evidence.map((e) => (
              <Item
                key={`${e.agent}:${e.record_id}`}
                name={`Evidence ${e.record_id}`}
                value={e.hash_at_decision}
                ok={e.hash_matches_decision && e.record_hash_verifies}
              />
            ))}
            {d.overrides.map((o) => (
              <Item key={o.sequence} name={`Override #${o.sequence}`} value={o.content_hash} />
            ))}
          </div>
          <p className="py-2.5 text-xs text-muted-foreground">
            Engine <span className="font-mono">{r.engine_version}</span> · model{" "}
            {r.model_version ?? "none (rules only)"}
          </p>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
