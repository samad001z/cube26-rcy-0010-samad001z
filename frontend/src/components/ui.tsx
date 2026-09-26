import type { ReactNode } from "react";

import type { DecisionValue, RecordStatus, Verdict } from "@/lib/types";

const DECISION_STYLE: Record<DecisionValue, string> = {
  CLAIM: "bg-claim-bg text-claim",
  DO_NOT_CLAIM: "bg-dnc-bg text-dnc",
  REVIEW: "bg-review-bg text-review ring-1 ring-inset ring-review-line",
};

export function label(v: string): string {
  return v.replaceAll("_", " ");
}

export function DecisionBadge({ value, size = "sm" }: { value: DecisionValue; size?: "sm" | "lg" }) {
  const pad = size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <span className={`inline-flex items-center rounded font-semibold tracking-wide ${pad} ${DECISION_STYLE[value]}`}>
      {label(value)}
    </span>
  );
}

const VERDICT_STYLE: Record<Verdict, string> = {
  PASS: "bg-pass-bg text-pass",
  FAIL: "bg-fail-bg text-fail",
  UNCERTAIN: "bg-unc-bg text-unc",
};

export function VerdictBadge({ value }: { value: Verdict }) {
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-semibold ${VERDICT_STYLE[value]}`}>
      {value}
    </span>
  );
}

export function StatusPill({ status }: { status: RecordStatus }) {
  if (status === "final") return null;
  const style =
    status === "pending" ? "border-fail text-fail" : "border-muted text-muted";
  const text = status === "pending" ? "pending: engine did not finish" : "overridden by a reviewer";
  return <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${style}`}>{text}</span>;
}

export function Card({ title, children, aside }: { title?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface">
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {aside}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Hash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted">none</span>;
  return (
    <code className="font-mono text-[11px] text-muted" title={value}>
      {value.slice(0, 12)}…
    </code>
  );
}

export function Money({ amount, currency }: { amount: string | null; currency: string }) {
  if (amount === null) return <span className="text-muted">–</span>;
  return (
    <span className="num whitespace-nowrap">
      {amount} <span className="text-muted">{currency}</span>
    </span>
  );
}

export function Field({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">{name}</dt>
      <dd className="mt-0.5 break-words text-sm">{children}</dd>
    </div>
  );
}

export function Notice({ tone, children }: { tone: "warn" | "error" | "info"; children: ReactNode }) {
  const style =
    tone === "error"
      ? "border-fail bg-fail-bg text-fail"
      : tone === "warn"
        ? "border-review-line bg-review-bg text-review"
        : "border-line bg-surface-2 text-ink";
  return <div className={`rounded-md border px-3 py-2 text-sm ${style}`}>{children}</div>;
}
