"use client";

import { Check, ChevronsUpDown, History } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Run } from "@/lib/types";
import { dateTime, shortId } from "@/lib/utils";

/** Picks which run the decisions page shows (`/?run=`). Runs arrive newest first. */
export function RunSwitcher({ runs }: { runs: Run[] }) {
  const path = usePathname();
  const params = useSearchParams();
  if (runs.length === 0) {
    return <span className="text-sm text-muted-foreground">No runs yet</span>;
  }
  const onList = path === "/";
  const current = onList ? (runs.find((r) => r.run_id === params.get("run")) ?? runs[0]) : null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-9 min-w-0 items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-sm shadow-card hover:bg-surface-2">
        <History className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        {current ? (
          <span className="min-w-0 truncate">
            <span className="sr-only">Run: </span>
            <span className="font-mono text-xs">{shortId(current.run_id)}</span>
            <span className="hidden text-muted-foreground sm:inline"> · {dateTime(current.decided_at)}</span>
            {current === runs[0] && <span className="ml-1.5 hidden text-xs text-muted-foreground md:inline">(latest)</span>}
          </span>
        ) : (
          <span className="truncate text-muted-foreground">Choose a run</span>
        )}
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        <DropdownMenuLabel>Runs, newest first</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {runs.map((r, i) => (
          <DropdownMenuItem key={r.run_id} asChild>
            <Link href={i === 0 ? "/" : `/?run=${r.run_id}`} className="items-start">
              <Check
                className={`mt-0.5 ${current?.run_id === r.run_id ? "opacity-100" : "opacity-0"}`}
                aria-hidden
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs">{shortId(r.run_id)}</span>
                  {i === 0 && <span className="text-xs text-muted-foreground">latest</span>}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {dateTime(r.decided_at)} · <span className="num">{r.charges}</span> charges
                </span>
              </span>
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
