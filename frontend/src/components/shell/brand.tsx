export function Brand({ subtitle = true }: { subtitle?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element -- a static brand mark, not a page image */}
      <img src="/alibi-mark.svg" alt="" className="size-8" />
      <span className="flex flex-col leading-tight">
        <span className="text-sm font-semibold tracking-tight">Alibi</span>
        {subtitle && <span className="text-xs text-muted-foreground">Recovery Manager</span>}
      </span>
    </span>
  );
}
