import { ScanSearch } from "lucide-react";

export function Brand({ subtitle = true }: { subtitle?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-8 items-center justify-center rounded-md bg-foreground text-background">
        <ScanSearch className="size-4" aria-hidden />
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-sm font-semibold tracking-tight">Alibi</span>
        {subtitle && <span className="text-xs text-muted-foreground">Recovery Manager</span>}
      </span>
    </span>
  );
}
