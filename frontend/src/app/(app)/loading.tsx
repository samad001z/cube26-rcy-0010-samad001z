import { Skeleton } from "@/components/ui/skeleton";

/** Placeholder with the same outline as the decisions page, so nothing jumps when it loads. */
export default function Loading() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading decisions">
      <div className="space-y-2">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-5 w-72" />
      </div>
      <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-[172px] rounded-lg" />
        ))}
      </div>
      <div className="flex flex-col gap-2 lg:flex-row">
        <Skeleton className="h-9 lg:w-72" />
        <div className="grid flex-1 grid-cols-1 gap-2 sm:grid-cols-3 lg:flex lg:justify-end">
          <Skeleton className="h-9 lg:w-48" />
          <Skeleton className="h-9 lg:w-48" />
          <Skeleton className="h-9 lg:w-64" />
        </div>
      </div>
      <div className="space-y-px overflow-hidden rounded-lg border border-border bg-surface">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="flex items-center gap-4 border-b border-border px-3 py-3 last:border-0">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="hidden h-4 w-20 sm:block" />
          </div>
        ))}
      </div>
    </div>
  );
}
