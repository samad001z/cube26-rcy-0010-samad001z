"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

export function CopyButton({ value, label, className }: { value: string; label: string; className?: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      // Clipboard refused (insecure context or permission): the value is still selectable.
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground",
        className,
      )}
    >
      {done ? <Check className="size-3.5 text-pass" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      <span className="sr-only">{done ? "Copied" : `Copy ${label}`}</span>
      <span aria-live="polite" className="sr-only">
        {done ? "Copied" : ""}
      </span>
    </button>
  );
}

/** A full hash in monospace, wrapped, with a copy button. */
export function HashValue({ value, label }: { value: string | null | undefined; label: string }) {
  if (!value) return <span className="text-sm text-muted-foreground">none</span>;
  return (
    <div className="flex items-start gap-1">
      <code className="min-w-0 flex-1 break-all pt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">
        {value}
      </code>
      <CopyButton value={value} label={label} />
    </div>
  );
}
