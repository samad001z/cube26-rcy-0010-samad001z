import { CircleCheck, CircleHelp, CircleSlash, CircleX, Clock, Hand, UserPen } from "lucide-react";
import type { ComponentProps } from "react";

import { Badge } from "@/components/ui/badge";
import type { DecisionValue, RecordStatus, Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";

// One look per decision, used everywhere. Icon + word + colour: colour is never the only signal.
export const DECISION = {
  CLAIM: { word: "CLAIM", tone: "claim", icon: CircleCheck },
  DO_NOT_CLAIM: { word: "DO NOT CLAIM", tone: "dnc", icon: CircleSlash },
  REVIEW: { word: "REVIEW", tone: "review", icon: Hand },
} as const satisfies Record<DecisionValue, { word: string; tone: string; icon: unknown }>;

export function DecisionChip({
  value,
  size = "md",
  className,
}: {
  value: DecisionValue;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const d = DECISION[value];
  const Icon = d.icon;
  return (
    <Badge tone={d.tone} size={size} className={cn("font-semibold tracking-wide", className)}>
      <Icon aria-hidden />
      {d.word}
    </Badge>
  );
}

const VERDICT = {
  PASS: { icon: CircleCheck, className: "text-pass", word: "Pass" },
  FAIL: { icon: CircleX, className: "text-fail", word: "Fail" },
  UNCERTAIN: { icon: CircleHelp, className: "text-unc", word: "Uncertain" },
} as const;

export function VerdictIcon({ value, className, ...props }: { value: Verdict } & ComponentProps<"svg">) {
  const v = VERDICT[value];
  const Icon = v.icon;
  return <Icon aria-hidden className={cn("size-4 shrink-0", v.className, className)} {...props} />;
}

/** Icon plus the verdict word, for lists where the word must be read. */
export function Verdict({ value, className }: { value: Verdict; className?: string }) {
  const v = VERDICT[value];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", v.className, className)}>
      <VerdictIcon value={value} />
      {v.word}
    </span>
  );
}

export function StatusChip({ status }: { status: RecordStatus }) {
  if (status === "final") return null;
  return status === "pending" ? (
    <Badge tone="fail">
      <Clock aria-hidden />
      Pending: engine did not finish
    </Badge>
  ) : (
    <Badge tone="outline">
      <UserPen aria-hidden />
      Overridden by a reviewer
    </Badge>
  );
}
