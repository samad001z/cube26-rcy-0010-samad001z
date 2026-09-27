import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONE = {
  error: { icon: CircleAlert, className: "border-fail-line bg-fail-soft text-fail" },
  warn: { icon: TriangleAlert, className: "border-review-line bg-review-soft text-review" },
  info: { icon: Info, className: "border-border bg-surface-2 text-foreground" },
} as const;

export function Notice({
  tone,
  title,
  children,
  className,
}: {
  tone: keyof typeof TONE;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const t = TONE[tone];
  const Icon = t.icon;
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className={cn("flex gap-3 rounded-lg border px-4 py-3 text-sm", t.className, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn(title && "text-foreground/90")}>{children}</div>}
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-border-strong bg-surface px-6 py-12 text-center">
      <div className="flex size-10 items-center justify-center rounded-full bg-surface-2 text-muted-foreground [&_svg]:size-5">
        {icon}
      </div>
      <h2 className="mt-3 text-base font-semibold">{title}</h2>
      {children && <div className="mt-1 max-w-md text-sm text-muted-foreground">{children}</div>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}
