import { CalendarClock } from "lucide-react";

import { Verdict } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { Deadline } from "@/lib/types";
import { day } from "@/lib/utils";

const STATUS: Record<Deadline["status"], { word: string; tone: "neutral" | "fail" | "review" | "accent" }> = {
  open: { word: "Open", tone: "accent" },
  passed: { word: "Passed", tone: "fail" },
  not_yet_open: { word: "Not open yet", tone: "review" },
  not_verified: { word: "Not verified", tone: "review" },
  unknown: { word: "Unknown", tone: "neutral" },
};

function sentence(d: Deadline): string {
  switch (d.status) {
    case "open":
      return `The window to file is open. The deadline is ${d.deadline ? day(d.deadline) : "not stated"}.`;
    case "passed":
      return `The filing deadline${d.deadline ? ` (${day(d.deadline)})` : ""} has passed, so no claim can be filed.`;
    case "not_yet_open":
      return `The window to file opens ${d.opens ? day(d.opens) : "later"}. A claim cannot be filed before then.`;
    case "not_verified":
      return "No filing deadline for this charge type has been sourced from the channel's documentation yet, so it is not checked.";
    default:
      return `The deadline could not be worked out: ${d.detail}.`;
  }
}

export function DeadlineCard({ d }: { d: Deadline }) {
  const s = STATUS[d.status];
  return (
    <Card>
      <CardHeader
        icon={<CalendarClock aria-hidden />}
        title="Filing deadline"
        action={<Badge tone={s.tone}>{s.word}</Badge>}
      />
      <CardBody className="space-y-3">
        <p className="text-sm">{sentence(d)}</p>
        <p className="text-xs text-muted-foreground">Judged today, {day(d.as_of)}.</p>
        {d.at_decision.verdict && (
          <div className="rounded-md bg-surface-2 p-3">
            <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              When decided <Verdict value={d.at_decision.verdict} />
            </p>
            {d.at_decision.detail && <p className="mt-1 text-xs">{d.at_decision.detail}</p>}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
