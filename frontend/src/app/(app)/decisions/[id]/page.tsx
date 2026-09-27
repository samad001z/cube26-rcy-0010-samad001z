import { ChevronRight, History, Info, UserPen } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";
import type { ReactNode } from "react";

import { AmountsCard } from "@/components/decision/amounts-card";
import { ChecksCard } from "@/components/decision/checks-card";
import { DeadlineCard } from "@/components/decision/deadline-card";
import { EvidenceTimeline } from "@/components/decision/evidence-timeline";
import { IntegrityCard } from "@/components/decision/integrity-card";
import { OverrideHistory } from "@/components/decision/override-history";
import { OverrideSheet } from "@/components/decision/override-sheet";
import { WhyCard } from "@/components/decision/why-card";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { DecisionChip, StatusChip } from "@/components/status";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Tooltip } from "@/components/ui/tooltip";
import { BackendError, api } from "@/lib/api";
import type { DecisionDetail } from "@/lib/types";
import { day, sentence, shortId } from "@/lib/utils";

export const metadata: Metadata = { title: "Decision" };

function Stat({ name, children }: { name: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-xs font-medium text-muted-foreground lg:justify-end">{name}</dt>
      <dd className="mt-1 text-base font-semibold tracking-tight sm:text-lg">{children}</dd>
    </div>
  );
}

function Meta({ name, children, mono = true }: { name: string; children: ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="inline">{name} </dt>
      <dd className={mono ? "inline font-mono text-foreground" : "inline text-foreground"}>{children}</dd>
    </div>
  );
}

export default async function DecisionPage({ params }: PageProps<"/decisions/[id]">) {
  const { id } = await params;
  let d: DecisionDetail;
  try {
    d = await api<DecisionDetail>(`/decisions/${encodeURIComponent(id)}`);
  } catch (err) {
    unstable_rethrow(err); // let redirect() to the login page through
    if (err instanceof BackendError && err.status === 404) notFound();
    const msg = err instanceof BackendError ? `${err.status}: ${err.message}` : "unknown error";
    return (
      <Notice tone="error" title="This decision could not be loaded">
        The Alibi API answered {msg}. Nothing was changed.
      </Notice>
    );
  }
  const r = d.record;
  const eng = d.engine_record;
  const s = r.subject;
  const posted = typeof d.charge?.posted_date === "string" ? d.charge.posted_date : null;
  const quantity = typeof d.charge?.quantity === "number" ? d.charge.quantity : null;
  const history = d.line_history.filter((h) => h.record_id !== r.record_id);
  const blocked =
    d.integrity_problems.length > 0
      ? "Overrides are blocked: the stored history of this decision does not verify."
      : !d.overridable
        ? "A newer run decided this charge line. Override the newest decision; this one is kept as history."
        : null;

  return (
    <div className="space-y-6">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted-foreground">
        <Link href={`/?run=${r.run_id}`} className="rounded hover:text-foreground">
          Decisions
        </Link>
        <ChevronRight className="size-3.5" aria-hidden />
        <span className="font-mono text-xs text-foreground" aria-current="page">
          {s.line_id}
        </span>
      </nav>

      <Card>
        <div className="flex flex-col gap-5 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-xl font-semibold tracking-tight">{s.line_id}</h1>
              <DecisionChip value={r.decision} size="lg" />
              <StatusChip status={r.status} />
            </div>
            <p className="text-sm">
              {sentence(s.charge_type)}
              {s.defect_category && (
                <span className="text-muted-foreground"> · stated defect: {s.defect_category.replaceAll("_", " ")}</span>
              )}
              {quantity !== null && <span className="text-muted-foreground"> · quantity {quantity}</span>}
            </p>
            <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <Meta name="Unit">{s.unit_id}</Meta>
              {s.fba_shipment_id && <Meta name="Shipment">{s.fba_shipment_id}</Meta>}
              {s.order_id && <Meta name="Order">{s.order_id}</Meta>}
              {posted && (
                <Meta name="Posted" mono={false}>
                  {day(`${posted}T00:00:00Z`)}
                </Meta>
              )}
              <Meta name="Run">{shortId(r.run_id)}</Meta>
            </dl>
          </div>
          <div className="flex flex-col gap-4 lg:items-end">
            <dl className="grid grid-cols-3 gap-4 sm:gap-6 lg:text-right">
              <Stat name="Charged">
                <Money amount={r.amount_charged} currency={r.currency} />
              </Stat>
              <Stat name="Claim">
                <Money amount={r.claim?.amount ?? null} currency={r.currency} />
              </Stat>
              <Stat
                name={
                  <>
                    <span className="truncate">Routing confidence</span>
                    <Tooltip
                      content={
                        <>
                          How directly the recorded data settles the check this decision rests on: 1.00 is an
                          exact comparison of ingested data, 0.90 rests on an operator&apos;s recorded check. It is
                          not the chance that the decision is right, nor that a claim is accepted.
                        </>
                      }
                    >
                      <button type="button" className="shrink-0 rounded-full text-muted-foreground hover:text-foreground">
                        <Info className="size-3.5" aria-hidden />
                        <span className="sr-only">What routing confidence measures</span>
                      </button>
                    </Tooltip>
                  </>
                }
              >
                <span className="num">{r.confidence}</span>
              </Stat>
            </dl>
            <OverrideSheet
              recordId={r.record_id}
              current={r.decision}
              claimRefusal={d.claim_refusal}
              blocked={blocked}
              history={<OverrideHistory overrides={d.overrides} />}
            />
          </div>
        </div>
      </Card>

      {d.integrity_problems.length > 0 && (
        <Notice tone="error" title="The stored history does not verify">
          New overrides are blocked until this is looked into.
          <ul className="mt-1 list-disc pl-5">
            {d.integrity_problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      )}

      {d.overrides.length > 0 && (
        <Notice tone="info" title="Changed by a reviewer">
          <span className="inline-flex flex-wrap items-center gap-1.5">
            The engine decided <DecisionChip value={eng.decision} size="sm" /> and a reviewer changed it to{" "}
            <DecisionChip value={r.decision} size="sm" />. The engine&apos;s reason and evidence below are unchanged.
          </span>
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <WhyCard r={eng} />
          <ChecksCard checks={eng.checks} />
          <EvidenceTimeline evidence={d.evidence} postedDate={posted} />
        </div>
        <div className="min-w-0 space-y-6">
          <AmountsCard r={r} />
          <DeadlineCard d={d.deadline} />
          <Card>
            <CardHeader icon={<UserPen aria-hidden />} title="Override history" />
            <CardBody>
              <OverrideHistory overrides={d.overrides} />
            </CardBody>
          </Card>
          <IntegrityCard d={d} />
          {history.length > 0 && (
            <Card>
              <CardHeader
                icon={<History aria-hidden />}
                title="Other runs of this line"
                description="Overrides are not carried over between runs."
              />
              <ul className="divide-y divide-border">
                {history.map((h) => (
                  <li key={h.record_id}>
                    <Link
                      href={`/decisions/${encodeURIComponent(h.record_id)}`}
                      className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm hover:bg-surface-2"
                    >
                      <span className="font-mono text-xs">run {shortId(h.run_id)}</span>
                      <span className="flex items-center gap-2">
                        {h.override_count > 0 && <span className="text-xs text-muted-foreground">overridden</span>}
                        <DecisionChip value={h.decision} size="sm" />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
