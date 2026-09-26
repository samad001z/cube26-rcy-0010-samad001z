import Link from "next/link";
import { unstable_rethrow } from "next/navigation";

import { DecisionBadge, Money, Notice, label } from "@/components/ui";
import { BackendError, api } from "@/lib/api";
import type { DecisionSummary, DecisionValue, Run } from "@/lib/types";

const ORDER: DecisionValue[] = ["REVIEW", "CLAIM", "DO_NOT_CLAIM"];
const TILE: Record<DecisionValue, { title: string; hint: string; style: string }> = {
  REVIEW: {
    title: "Needs review",
    hint: "Evidence is missing, conflicting or out of window. A person decides.",
    style: "border-review-line bg-review-bg text-review",
  },
  CLAIM: {
    title: "Claim",
    hint: "Evidence contradicts the charge, with full coverage.",
    style: "border-line bg-surface text-claim",
  },
  DO_NOT_CLAIM: {
    title: "Do not claim",
    hint: "Evidence supports the charge, or it is reimbursed or out of time.",
    style: "border-line bg-surface text-dnc",
  },
};

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

export default async function DecisionsPage({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const runParam = typeof sp.run === "string" ? sp.run : undefined;
  const show = typeof sp.show === "string" && ORDER.includes(sp.show as DecisionValue) ? (sp.show as DecisionValue) : undefined;

  let runs: Run[];
  let data: { run: Run | null; items: DecisionSummary[] };
  try {
    runs = await api<Run[]>("/runs");
    data = await api<{ run: Run | null; items: DecisionSummary[] }>(
      `/decisions${runParam ? `?run_id=${encodeURIComponent(runParam)}` : ""}`,
    );
  } catch (err) {
    unstable_rethrow(err); // let redirect() to the login page through
    const msg = err instanceof BackendError ? `${err.status}: ${err.message}` : "unknown error";
    return <Notice tone="error">Could not load decisions ({msg}).</Notice>;
  }

  if (!data.run) {
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">No runs yet</h1>
        <p className="text-sm text-muted">
          Upload a fee report and the upstream evidence files to get a decision for every charge.
        </p>
        <Link href="/run" className="inline-block rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg">
          Start a run
        </Link>
      </div>
    );
  }

  const run = data.run;
  const counts = Object.fromEntries(ORDER.map((d) => [d, data.items.filter((i) => i.decision === d).length])) as Record<DecisionValue, number>;
  const overridden = data.items.filter((i) => i.override_count > 0).length;
  const pending = data.items.filter((i) => i.status === "pending").length;
  const reviewReasons = Object.entries(
    data.items
      .filter((i) => i.decision === "REVIEW")
      .reduce<Record<string, number>>((acc, i) => {
        const k = i.reason_code ?? i.rule_id.replace(/^R_/, "").toLowerCase();
        acc[k] = (acc[k] ?? 0) + 1;
        return acc;
      }, {}),
  ).sort((a, b) => b[1] - a[1]);

  const rows = [...data.items]
    .filter((i) => !show || i.decision === show)
    .sort((a, b) => ORDER.indexOf(a.decision) - ORDER.indexOf(b.decision) || a.line_id.localeCompare(b.line_id));
  const base = runParam ? `/?run=${encodeURIComponent(runParam)}` : "/?";
  const sep = runParam ? "&" : "";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Decisions</h1>
          <p className="mt-0.5 text-sm text-muted">
            Run <code className="font-mono text-xs">{run.run_id.slice(0, 8)}</code> · {when(run.decided_at)} ·{" "}
            {run.charges} charges
            {overridden > 0 && <> · {overridden} overridden</>}
          </p>
        </div>
        {runs.length > 1 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted hover:text-ink">Other runs ({runs.length - 1})</summary>
            <ul className="mt-2 space-y-1">
              {runs.map((r) => (
                <li key={r.run_id}>
                  <Link href={`/?run=${r.run_id}`} className={r.run_id === run.run_id ? "font-semibold" : "hover:underline"}>
                    {r.run_id.slice(0, 8)} · {when(r.decided_at)} · {r.charges} charges
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {pending > 0 && (
        <Notice tone="error">
          {pending} charge{pending === 1 ? "" : "s"} could not be evaluated (engine or database failure) and
          {pending === 1 ? " was" : " were"} kept as REVIEW, pending. Nothing was dropped.
        </Notice>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        {ORDER.map((d) => (
          <Link
            key={d}
            href={show === d ? (runParam ? `/?run=${runParam}` : "/") : `${base}${sep}show=${d}`}
            className={`rounded-lg border p-4 transition hover:shadow-sm ${TILE[d].style} ${show === d ? "ring-2 ring-focus" : ""}`}
          >
            <div className="text-xs font-semibold uppercase tracking-wide">{TILE[d].title}</div>
            <div className="num mt-1 text-3xl font-bold">{counts[d]}</div>
            <div className="mt-1 text-xs opacity-80">{TILE[d].hint}</div>
          </Link>
        ))}
      </div>

      {reviewReasons.length > 0 && (!show || show === "REVIEW") && (
        <div className="text-sm">
          <span className="font-medium">Why charges need review: </span>
          <span className="text-muted">
            {reviewReasons.map(([k, n], i) => (
              <span key={k}>
                {i > 0 && " · "}
                {label(k)} <span className="num font-semibold text-ink">{n}</span>
              </span>
            ))}
          </span>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Decision</th>
              <th className="px-3 py-2 font-medium">Line</th>
              <th className="px-3 py-2 font-medium">Charge type</th>
              <th className="px-3 py-2 font-medium">Unit</th>
              <th className="px-3 py-2 text-right font-medium">Charged</th>
              <th className="px-3 py-2 text-right font-medium">Claim</th>
              <th className="px-3 py-2 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.record_id} className="border-b border-line last:border-0 hover:bg-surface-2">
                <td className="px-3 py-2 align-top">
                  <div className="flex flex-col items-start gap-1">
                    <DecisionBadge value={i.decision} />
                    {i.override_count > 0 && (
                      <span className="text-[11px] text-muted">engine: {label(i.engine_decision)}</span>
                    )}
                    {i.status === "pending" && <span className="text-[11px] font-medium text-fail">pending</span>}
                  </div>
                </td>
                <td className="px-3 py-2 align-top">
                  <Link href={`/decisions/${encodeURIComponent(i.record_id)}`} className="whitespace-nowrap font-mono text-xs font-medium text-focus hover:underline">
                    {i.line_id}
                  </Link>
                </td>
                <td className="px-3 py-2 align-top">{label(i.charge_type)}</td>
                <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-xs">{i.unit_id}</td>
                <td className="px-3 py-2 text-right align-top">
                  <Money amount={i.amount_charged} currency={i.currency} />
                </td>
                <td className="px-3 py-2 text-right align-top">
                  <Money amount={i.claim_amount} currency={i.currency} />
                </td>
                <td className="max-w-md px-3 py-2 align-top text-xs text-muted">
                  {i.reason_code && <span className="mr-1 font-semibold text-ink">{label(i.reason_code)}.</span>}
                  <span className="line-clamp-2">{i.reason}</span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-muted">
                  No {show ? label(show) : ""} decisions in this run.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
