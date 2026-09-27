import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";

import { Card, DecisionBadge, Field, Hash, Money, Notice, StatusPill, VerdictBadge, label } from "@/components/ui";
import { BackendError, api } from "@/lib/api";
import { checkName } from "@/lib/checks";
import type { CustodyWindow, DecisionDetail, Deadline, EvidenceItem } from "@/lib/types";

import { OverrideForm } from "./override-form";

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" });
}

const BASIS: Record<CustodyWindow["basis"], string> = {
  before_posting: "before the charge was posted",
  after_posting: "after the charge was posted",
  around_posting: "around the date the charge was posted",
};

/** One sentence: when the record was captured and whether that falls in the window. */
function windowSentence(e: EvidenceItem): string | null {
  const w = e.custody_window;
  if (!e.captured_at) return null;
  const captured = `Recorded ${when(e.captured_at)}.`;
  if (!w) return `${captured} The custody window is described in the note above.`;
  // End is exclusive: the last day inside the window is the day before `end`.
  const lastDay = new Date(new Date(w.end).getTime() - 1).toISOString();
  return (
    `${captured} Records from this pod count if made ${BASIS[w.basis]} ` +
    `(posted ${day(w.posted_date)}): from ${day(w.start)} to ${day(lastDay)}. ` +
    (w.captured_inside ? "This one is inside that window." : "This one is outside that window.")
  );
}

const DEADLINE_TEXT: Record<Deadline["status"], string> = {
  open: "The filing window is open: a claim can still be filed.",
  passed: "The filing deadline has passed: no claim can be filed.",
  not_yet_open: "The filing window has not opened yet: a claim cannot be filed before it opens.",
  not_verified: "No sourced filing deadline for this charge type: the deadline is not verified.",
  unknown: "The filing deadline was not checked.",
};

function EvidenceCard({ e }: { e: EvidenceItem }) {
  const hashOk = e.hash_matches_decision && e.record_hash_verifies;
  return (
    <li className={`rounded-md border p-3 ${e.cited ? "border-ink/30 bg-surface" : "border-line bg-surface-2"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-dnc-bg px-1.5 py-0.5 text-[11px] font-semibold uppercase text-dnc">{e.agent}</span>
        <code className="font-mono text-xs font-medium">{e.record_id}</code>
        {e.cited ? (
          <span className="text-[11px] font-semibold text-ink">cited by the decision</span>
        ) : (
          <span className="text-[11px] text-muted">read, not cited</span>
        )}
        <span className={`ml-auto text-[11px] font-medium ${hashOk ? "text-pass" : "text-fail"}`}>
          {hashOk ? "hash verifies" : "hash does NOT match the decision"}
        </span>
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {e.usable ? "Usable: " : "Not usable: "}
        {e.why}
      </p>
      {windowSentence(e) && (
        <p className={`mt-1 text-xs ${e.custody_window && !e.custody_window.captured_inside ? "text-review" : ""}`}>
          {windowSentence(e)}
        </p>
      )}
      {e.record && (
        <>
          <p className="mt-1 text-[11px] text-muted">
            {[
              e.record.operator_label && `by ${e.record.operator_label}`,
              e.record.outcome && `pod outcome ${e.record.outcome.decision}`,
              `status ${e.record.status}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {e.record.checks.length > 0 && (
            <ul className="mt-2 space-y-1">
              {e.record.checks.map((c) => (
                <li key={c.check_key} className="flex flex-wrap items-baseline gap-2 text-xs">
                  <VerdictBadge value={c.verdict} />
                  <span>{checkName(c.check_key)}</span>
                  <span className="font-mono text-[10px] text-muted">{c.check_key}</span>
                  {c.detail && <span className="text-muted">· {c.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {!e.record && <p className="mt-1 text-xs text-fail">The record is no longer in the store.</p>}
    </li>
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
    return <Notice tone="error">Could not load this decision ({msg}).</Notice>;
  }
  const r = d.record;
  const eng = d.engine_record;
  const overridden = d.overrides.length > 0;
  const cited = d.evidence.filter((e) => e.cited);
  const other = d.evidence.filter((e) => !e.cited);
  const history = d.line_history.filter((h) => h.record_id !== r.record_id);

  return (
    <div className="space-y-5">
      <div>
        <Link href={`/?run=${r.run_id}`} className="text-sm text-muted hover:text-ink hover:underline">
          ← Decisions of this run
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-xl font-semibold">{r.subject.line_id}</h1>
          <DecisionBadge value={r.decision} size="lg" />
          <StatusPill status={r.status} />
        </div>
        <p className="mt-1 text-sm text-muted">
          {label(r.subject.charge_type)} · unit <span className="font-mono">{r.subject.unit_id}</span>
          {r.subject.fba_shipment_id && <> · shipment <span className="font-mono">{r.subject.fba_shipment_id}</span></>}
          {r.subject.order_id && <> · order <span className="font-mono">{r.subject.order_id}</span></>}
          {" · "}decided by <span className="font-mono">{r.outcome.decided_by}</span> {when(r.outcome.decided_at)}
        </p>
      </div>

      {d.integrity_problems.length > 0 && (
        <Notice tone="error">
          <strong>Stored history does not verify.</strong> New overrides are blocked until this is investigated.
          <ul className="mt-1 list-disc pl-5">
            {d.integrity_problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      )}

      {overridden && (
        <Notice tone="info">
          The engine decided <DecisionBadge value={eng.decision} /> ({eng.rule_id}). A reviewer changed it to{" "}
          <DecisionBadge value={r.decision} />. The engine&apos;s reason and evidence below are unchanged.
        </Notice>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Why">
            <p className="text-sm leading-relaxed">{r.reason}</p>
            {r.next_action && (
              <p className="mt-3 text-sm">
                <span className="font-semibold">Next: </span>
                {r.next_action}
              </p>
            )}
            <p className={`mt-3 text-sm ${d.deadline.status === "passed" || d.deadline.status === "not_yet_open" ? "text-fail" : ""}`}>
              <span className="font-semibold">Deadline: </span>
              {DEADLINE_TEXT[d.deadline.status]}
              {d.deadline.detail && <span className="text-xs text-muted"> ({d.deadline.detail})</span>}
            </p>
            {r.warnings.length > 0 && (
              <ul className="mt-3 space-y-1">
                {r.warnings.map((w) => (
                  <li key={w} className="text-xs text-review">
                    ⚠ {w}
                  </li>
                ))}
              </ul>
            )}
            <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field name="Evidence">{label(r.evidence_status)}</Field>
              <Field name="Reason code">{r.reason_code ? label(r.reason_code) : "–"}</Field>
              <Field name="Rule">
                <code className="font-mono text-xs">{r.rule_id}</code>
              </Field>
              <Field name="Routing confidence">
                <span className="num">{r.confidence}</span>
              </Field>
            </dl>
          </Card>

          <Card title="Recovery checks">
            <table className="w-full text-left text-sm">
              <tbody>
                {r.checks.map((c) => (
                  <tr key={c.check_key} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3 align-top">
                      <VerdictBadge value={c.verdict} />
                    </td>
                    <td className="py-1.5 pr-3 align-top text-xs">
                      {checkName(c.check_key)}
                      <div className="font-mono text-[10px] text-muted">{c.check_key}</div>
                    </td>
                    <td className="num py-1.5 pr-3 align-top text-xs text-muted">{c.confidence ?? ""}</td>
                    <td className="py-1.5 align-top text-xs text-muted">{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title={`Evidence trail (${d.evidence.length} record${d.evidence.length === 1 ? "" : "s"} read)`}>
            {d.evidence.length === 0 ? (
              <p className="text-sm text-muted">
                No upstream record was found for this charge. That is why it cannot be decided from evidence.
              </p>
            ) : (
              <ul className="space-y-2">
                {[...cited, ...other].map((e) => (
                  <EvidenceCard key={`${e.agent}:${e.record_id}`} e={e} />
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card title="Amounts">
            <dl className="space-y-2">
              <Field name="Charged">
                <Money amount={r.amount_charged} currency={r.currency} />
              </Field>
              <Field name="Already reimbursed">
                <Money amount={r.amount_reimbursed} currency={r.currency} />
              </Field>
              <Field name="Claim">
                <Money amount={r.claim?.amount ?? null} currency={r.currency} />
              </Field>
            </dl>
            {r.claim && (
              <ol className="mt-3 space-y-0.5 border-t border-line pt-2 font-mono text-[11px] text-muted">
                {r.claim.computation.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            )}
          </Card>

          <Card title="Override">
            <OverrideForm
              recordId={r.record_id}
              current={r.decision}
              claimRefusal={d.claim_refusal}
              blocked={
                d.integrity_problems.length > 0
                  ? "Overrides are blocked: the stored history does not verify."
                  : !d.overridable
                    ? "A newer run decided this charge line. Override the newest decision; this one is kept as history."
                    : null
              }
            />
            {d.overrides.length > 0 && (
              <ol className="mt-4 space-y-3 border-t border-line pt-3">
                {[...d.overrides].reverse().map((o) => (
                  <li key={o.sequence} className="text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-muted">#{o.sequence}</span>
                      <DecisionBadge value={o.override.original_decision} />
                      <span className="text-muted">→</span>
                      <DecisionBadge value={o.override.new_decision} />
                    </div>
                    <p className="mt-1">&ldquo;{o.override.reason}&rdquo;</p>
                    <p className="mt-0.5 text-muted">
                      {o.override.reviewer} · {when(o.override.at)} · <Hash value={o.content_hash} />
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          <Card title="Traceability">
            <dl className="space-y-2">
              <Field name="Record">
                <code className="break-all font-mono text-[11px]">{r.record_id}</code>
              </Field>
              <Field name="Engine record hash">
                <Hash value={eng.content_hash} />
              </Field>
              {overridden && (
                <Field name="Effective record hash">
                  <Hash value={r.content_hash} />
                </Field>
              )}
              <Field name="Charge hash">
                <Hash value={r.subject.charge_content_hash} />
              </Field>
              <Field name="Rule path">
                <code className="break-words font-mono text-[11px]">{r.rule_path.join(" → ")}</code>
              </Field>
              <Field name="Engine">
                <span className="font-mono text-[11px]">
                  {r.engine_version} · rules <Hash value={r.rules_hash} /> · config <Hash value={r.config_hash} />
                </span>
              </Field>
              <Field name="Model">{r.model_version ?? "none (rules only)"}</Field>
            </dl>
          </Card>

          {history.length > 0 && (
            <Card title="Other runs of this line">
              <ul className="space-y-1.5 text-xs">
                {history.map((h) => (
                  <li key={h.record_id} className="flex items-center gap-2">
                    <DecisionBadge value={h.decision} />
                    <Link href={`/decisions/${encodeURIComponent(h.record_id)}`} className="font-mono text-focus hover:underline">
                      run {h.run_id.slice(0, 8)}
                    </Link>
                    {h.override_count > 0 && <span className="text-muted">overridden</span>}
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
