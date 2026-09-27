import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const fieldClass =
  "w-full rounded-md border border-input bg-surface px-3 text-sm text-foreground shadow-card placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring disabled:opacity-50 aria-[invalid=true]:border-fail aria-[invalid=true]:focus-visible:outline-fail";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(fieldClass, "h-9", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(fieldClass, "min-h-20 py-2", className)} {...props} />;
}
