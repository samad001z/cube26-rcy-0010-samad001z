import Link from "next/link";
import { unstable_rethrow } from "next/navigation";

import { DecisionBadge, Money, Notice, label } from "@/components/ui";
import { BackendError, api } from "@/lib/api";
import type { DecisionList, DecisionValue, Run } from "@/lib/types";

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
    style: "border-claim-line bg-claim-bg text-claim",
  },
  DO_NOT_CLAIM: {
    title: "Do not claim",
    hint: "Evidence supports the charge, or it is reimbursed or out of time.",
    style: "border-dnc-line bg-dnc-bg text-dnc",
  },
};

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

export default async function DecisionsPage({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const param = (k: string) => (typeof sp[k] === "string" && sp[k] ? (sp[k] as string) : undefined);
  const runParam = param("run");
  const show = ORDER.includes(param("show") as DecisionValue) ? (param("show") as DecisionValue) : undefined;
  const typeParam = param("type");
  const ruleParam = param("rule");

  let runs: Run[];
  let data: DecisionList;
  try {
    runs = await api<Run[]>("/runs");
    const q = new URLSearchParams();
    if (runParam) q.set("run_id", runParam);
    if (show) q.set("decision", show);
    if (typeParam) q.set("charge_type", typeParam);
    if (ruleParam) q.set("rule_id", ruleParam);
    data = await api<DecisionList>(`/decisions${q.size ? `?${q}` : ""}`);
  } catch (err) {
    unstable_rethrow(err); // let redirect() to the login page through
    const msg = err instanceof BackendError ? `${err.status}: ${err.message}` : "unknown error";
    return <Notice tone="error">Could not load decisions ({msg}).</Notice>;
  }

  /** Link to this page with some filters changed (undefined removes one). */
  const href = (change: Record<string, string | undefined>) => {
    const next = { run: runParam, show, type: typeParam, rule: ruleParam, ...change };
    const q = new URLSearchParams(Object.entries(next).filter((e): e is [string, string] => !!e[1]));
    return q.size ? `/?${q}` : "/";
  };

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
  const counts = Object.fromEntries(ORDER.map((d) => [d, data.counts[d] ?? 0])) as Record<DecisionValue, number>;
  const overridden = data.items.filter((i) => i.override_count > 0).length;
  const pending = data.items.filter((i) => i.status === "pending").length;
  const filtered = !!(show || typeParam || ruleParam);
  const reviewReasons = Object.entries(
    data.items
      .filter((i) => i.decision === "REVIEW")
      .reduce<Record<string, number>>((acc, i) => {
        const k = i.reason_code ?? i.rule_id.replace(/^R_/, "").toLowerCase();
        acc[k] = (acc[k] ?? 0) + 1;
        return acc;
      }, {}),
  ).sort((a, b) => b[1] - a[1]);

  const rows = [...data.items].sort(
    (a, b) => ORDER.indexOf(a.decision) - ORDER.indexOf(b.decision) || a.line_id.localeCompare(b.line_id),
  );

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
            href={href({ show: show === d ? undefined : d })}
            className={`rounded-lg border p-4 transition hover:shadow-sm ${TILE[d].style} ${show === d ? "ring-2 ring-focus" : ""}`}
          >
            <div className="text-xs font-semibold uppercase tracking-wide">{TILE[d].title}</div>
            <div className="num mt-1 text-3xl font-bold">{counts[d]}</div>
            <div className="mt-1 text-xs opacity-80">{TILE[d].hint}</div>
          </Link>
        ))}
      </div>

      <form method="get" action="/" className="flex flex-wrap items-end gap-3 text-sm">
        {runParam && <input type="hidden" name="run" value={runParam} />}
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">Decision</span>
          <select name="show" defaultValue={show ?? ""} className="rounded-md border border-line bg-surface px-2 py-1.5">
            <option value="">All</option>
            {ORDER.map((d) => (
              <option key={d} value={d}>
                {label(d)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">Charge type</span>
          <select name="type" defaultValue={typeParam ?? ""} className="rounded-md border border-line bg-surface px-2 py-1.5">
            <option value="">All</option>
            {(data.facets.charge_type ?? []).map((t) => (
              <option key={t} value={t}>
                {label(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">Rule</span>
          <select name="rule" defaultValue={ruleParam ?? ""} className="rounded-md border border-line bg-surface px-2 py-1.5">
            <option value="">All</option>
            {(data.facets.rule_id ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <button className="rounded-md bg-ink px-3 py-1.5 font-medium text-bg">Filter</button>
        {filtered && (
          <Link href={href({ show: undefined, type: undefined, rule: undefined })} className="py-1.5 text-muted hover:text-ink hover:underline">
            Clear filters
          </Link>
        )}
        {filtered && (
          <span className="py-1.5 text-muted">
            Showing <span className="num font-semibold text-ink">{data.items.length}</span> of {run.charges}
          </span>
        )}
      </form>

      {reviewReasons.length > 0 && (!show || show === "REVIEW") && (
        <div className="text-sm">
          <span className="font-medium">Why {filtered ? "these" : ""} charges need review: </span>
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
                    {i.integrity_problems.length > 0 && (
                      <span className="text-[11px] font-medium text-fail">history does not verify</span>
                    )}
                    {i.earlier_override && (
                      <span
                        className="max-w-[11rem] text-[11px] text-review"
                        title={`"${i.earlier_override.reason}"`}
                      >
                        earlier run: {i.earlier_override.reviewer} set {label(i.earlier_override.decision)},{" "}
                        {when(i.earlier_override.at)}
                      </span>
                    )}
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
                  No decisions in this run match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
