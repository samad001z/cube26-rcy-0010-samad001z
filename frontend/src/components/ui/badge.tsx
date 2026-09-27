import { type VariantProps, cva } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-md border font-medium [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface-2 text-muted-foreground",
        outline: "border-border-strong bg-transparent text-foreground",
        claim: "border-claim-line bg-claim-soft text-claim",
        dnc: "border-dnc-line bg-dnc-soft text-dnc",
        review: "border-review-line bg-review-soft text-review",
        fail: "border-fail-line bg-fail-soft text-fail",
        accent: "border-transparent bg-accent-soft text-accent-text",
      },
      size: {
        sm: "h-5 px-1.5 text-[11px] [&_svg]:size-3",
        md: "h-6 px-2 text-xs [&_svg]:size-3.5",
        lg: "h-7 px-2.5 text-sm [&_svg]:size-4",
      },
    },
    defaultVariants: { tone: "neutral", size: "md" },
  },
);

export function Badge({ className, tone, size, ...props }: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone, size }), className)} {...props} />;
}
