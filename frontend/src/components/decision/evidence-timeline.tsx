import {
  CalendarRange,
  CircleCheck,
  FileSearch,
  Link2,
  Receipt,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { VerdictIcon } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { checkName } from "@/lib/checks";
import type { CustodyWindow, EvidenceItem } from "@/lib/types";
import { cn, dateTime, day, sentence } from "@/lib/utils";

const POD: Record<string, string> = { prep: "Prep", receiving: "Receiving", returns: "Returns", pack: "Pack" };

const BASIS: Record<CustodyWindow["basis"], string> = {
  before_posting: "records made before the charge was posted",
  after_posting: "records made after the charge was posted",
  around_posting: "records made around the date the charge was posted",
};

interface Window {
  key: string;
  pod: string;
  w: CustodyWindow;
}

type Event =
  | { kind: "open" | "close"; t: number; win: Window }
  | { kind: "posted"; t: number; date: string }
  | { kind: "record"; t: number | null; e: EvidenceItem };

// Same instant: a window closes, then the charge is posted, then a window opens, then records.
const TIE: Record<Event["kind"], number> = { close: 0, posted: 1, open: 2, record: 3 };

function podName(agent: string) {
  return POD[agent] ?? sentence(agent);
}

/** The last day inside a window whose `end` is exclusive. */
function lastDay(w: CustodyWindow): string {
  return new Date(new Date(w.end).getTime() - 1).toISOString();
}

function buildEvents(evidence: EvidenceItem[], postedDate: string | null) {
  const windows = new Map<string, Window>();
  for (const e of evidence) {
    if (!e.custody_window) continue;
    const key = `${e.agent}|${e.custody_window.start}|${e.custody_window.end}`;
    if (!windows.has(key)) windows.set(key, { key, pod: e.agent, w: e.custody_window });
  }
  const posted = postedDate ?? [...windows.values()][0]?.w.posted_date ?? null;
  const events: Event[] = [];
  for (const win of windows.values()) {
    events.push({ kind: "open", t: Date.parse(win.w.start), win });
    events.push({ kind: "close", t: Date.parse(win.w.end), win });
  }
  if (posted) events.push({ kind: "posted", t: Date.parse(`${posted}T00:00:00Z`), date: posted });
  for (const e of evidence) events.push({ kind: "record", t: e.captured_at ? Date.parse(e.captured_at) : null, e });
  events.sort((a, b) => {
    if (a.t === null) return 1;
    if (b.t === null) return -1;
    return a.t - b.t || TIE[a.kind] - TIE[b.kind];
  });
  return { events, windows: [...windows.values()] };
}

function inside(ev: Event, win: Window): boolean {
  if (ev.kind === "open" || ev.kind === "close") return ev.win.key === win.key;
  if (ev.t === null) return false;
  return ev.t >= Date.parse(win.w.start) && ev.t < Date.parse(win.w.end);
}

function RecordCard({ e }: { e: EvidenceItem }) {
  const hashOk = e.hash_matches_decision && e.record_hash_verifies;
  const w = e.custody_window;
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        e.cited ? "border-border-strong bg-surface shadow-card" : "border-dashed border-border-strong bg-surface-2/60",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Badge tone="outline" size="sm">
          {podName(e.agent)}
        </Badge>
        <code className="font-mono text-xs font-medium">{e.record_id}</code>
        {e.cited ? (
          <Badge tone="accent" size="sm">
            <Link2 aria-hidden />
            Cited by the decision
          </Badge>
        ) : (
          <Badge tone="neutral" size="sm" className="border-dashed">
            <FileSearch aria-hidden />
            Read, not cited
          </Badge>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>{e.captured_at ? dateTime(e.captured_at) : "Time not recorded"}</span>
        {w &&
          (w.captured_inside ? (
            <span className="inline-flex items-center gap-1">
              <CircleCheck className="size-3.5" aria-hidden />
              Inside the custody window
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium text-review">
              <TriangleAlert className="size-3.5" aria-hidden />
              Outside the custody window
            </span>
          ))}
        <span className={cn("inline-flex items-center gap-1", !hashOk && "font-medium text-fail")}>
          {hashOk ? <ShieldCheck className="size-3.5" aria-hidden /> : <ShieldAlert className="size-3.5" aria-hidden />}
          {hashOk ? "Hash verifies" : "Hash does not match the decision"}
        </span>
        {e.record?.operator_label && <span>by {e.record.operator_label}</span>}
      </div>
      {!e.usable && <p className="mt-2 text-xs text-review">Not used by the engine: {e.why}</p>}
      {!e.record && <p className="mt-2 text-xs text-fail">The record is no longer in the store.</p>}
      {e.record && e.record.checks.length > 0 && (
        <ul className={cn("mt-2.5 grid gap-1 sm:grid-cols-2", !e.cited && "text-muted-foreground")}>
          {e.record.checks.map((c) => (
            <li key={c.check_key} className="flex min-w-0 items-start gap-1.5 text-xs">
              <VerdictIcon value={c.verdict} className="mt-px size-3.5" />
              <span className="sr-only">{c.verdict}:</span>
              <span className="min-w-0">
                {checkName(c.check_key)}
                {c.detail && <span className="text-muted-foreground"> ({c.detail})</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Upstream records in time order around the posting date. Each custody window is a shaded
 * rail on the left: a record inside the band was made when that pod's records can speak to
 * the charge. Cited records are solid; records read but not cited are dashed.
 */
export function EvidenceTimeline({ evidence, postedDate }: { evidence: EvidenceItem[]; postedDate: string | null }) {
  const { events, windows } = buildEvents(evidence, postedDate);
  const cited = evidence.filter((e) => e.cited).length;
  return (
    <Card>
      <CardHeader
        icon={<CalendarRange aria-hidden />}
        title="Evidence"
        description={
          evidence.length === 0
            ? "No upstream record was found for this charge."
            : `${evidence.length} record${evidence.length === 1 ? "" : "s"} read, ${cited} cited by the decision.`
        }
      />
      {evidence.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">
          Nothing from Receiving, Prep, Pack or Returns matched this charge, which is why it cannot be decided from
          evidence.
        </p>
      ) : (
        <div className="p-4">
          {windows.length > 0 && (
            <p className="mb-4 flex items-start gap-2 text-xs text-muted-foreground">
              <span className="mt-0.5 inline-block h-3 w-1.5 shrink-0 rounded-full bg-accent/40" aria-hidden />
              The shaded rail is a custody window: the dates when a pod&apos;s records can speak to this charge.
            </p>
          )}
          <ol className="relative">
            {events.map((ev, idx) => {
              const last = idx === events.length - 1;
              return (
                <li key={idx} className="flex gap-3">
                  {windows.length > 0 && (
                    <div className="flex shrink-0 gap-1" aria-hidden>
                      {windows.map((win) => {
                        const own = (ev.kind === "open" || ev.kind === "close") && ev.win.key === win.key;
                        return (
                          <span key={win.key} className="relative w-1.5">
                            {inside(ev, win) && (
                              <span
                                className={cn(
                                  "absolute inset-x-0 bg-accent/40",
                                  own && ev.kind === "open" ? "bottom-0 top-2 rounded-t-full" : "top-0",
                                  own && ev.kind === "close" ? "h-4 rounded-b-full" : "bottom-0",
                                )}
                              />
                            )}
                          </span>
                        );
                      })}
                    </div>
                  )}
                  <div className="relative flex w-5 shrink-0 justify-center" aria-hidden>
                    {!last && <span className="absolute bottom-0 top-3 w-px bg-border-strong" />}
                    {idx > 0 && <span className="absolute top-0 h-3 w-px bg-border-strong" />}
                    <span className="relative mt-1.5">
                      {ev.kind === "record" ? (
                        <span
                          className={cn(
                            "block size-3 rounded-full border-2",
                            ev.e.cited ? "border-accent bg-accent" : "border-dashed border-muted-foreground bg-surface",
                          )}
                        />
                      ) : ev.kind === "posted" ? (
                        <Receipt className="size-3.5 bg-surface text-foreground" />
                      ) : (
                        <span className="block size-2.5 rotate-45 border border-accent bg-surface" />
                      )}
                    </span>
                  </div>
                  <div className={cn("min-w-0 flex-1", last ? "pb-0" : "pb-4")}>
                    {ev.kind === "record" && <RecordCard e={ev.e} />}
                    {ev.kind === "posted" && (
                      <p className="pt-0.5 text-sm">
                        <span className="font-medium">Charge posted</span>{" "}
                        <span className="text-muted-foreground">{day(`${ev.date}T00:00:00Z`)}</span>
                      </p>
                    )}
                    {ev.kind === "open" && (
                      <p className="pt-0.5 text-sm">
                        <span className="font-medium">{podName(ev.win.pod)} custody window opens</span>{" "}
                        <span className="text-muted-foreground">
                          {day(ev.win.w.start)} · counts {BASIS[ev.win.w.basis]}
                        </span>
                      </p>
                    )}
                    {ev.kind === "close" && (
                      <p className="pt-0.5 text-sm">
                        <span className="font-medium">{podName(ev.win.pod)} custody window closes</span>{" "}
                        <span className="text-muted-foreground">last day {day(lastDay(ev.win.w))}</span>
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </Card>
  );
}
