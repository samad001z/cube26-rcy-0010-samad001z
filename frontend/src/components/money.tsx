import { cn } from "@/lib/utils";

/** An amount exactly as the backend sent it (a Decimal string). Never computed on here. */
export function Money({
  amount,
  currency,
  className,
}: {
  amount: string | null | undefined;
  currency: string;
  className?: string;
}) {
  if (amount === null || amount === undefined) {
    return (
      <span className={cn("text-muted-foreground", className)}>
        <span aria-hidden>—</span>
        <span className="sr-only">none</span>
      </span>
    );
  }
  return (
    <span className={cn("num whitespace-nowrap", className)}>
      {amount}
      <span className="ml-1 text-[0.85em] text-muted-foreground">{currency}</span>
    </span>
  );
}
