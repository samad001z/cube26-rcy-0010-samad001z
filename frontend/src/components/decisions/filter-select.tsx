"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const ALL = "__all__";

/** A labelled dropdown filter. Radix Select has no empty value, so "All" is a sentinel. */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
  wide = false,
}: {
  label: string;
  value?: string;
  options: { value: string; label: string; mono?: boolean }[];
  onChange: (v: string | undefined) => void;
  wide?: boolean;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={(v) => onChange(v === ALL ? undefined : v)}>
      <SelectTrigger aria-label={label} className={cn("lg:w-48", wide && "lg:w-64")}>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 text-muted-foreground">{label}:</span>
          <span className={cn("truncate", options.find((o) => o.value === value)?.mono && "font-mono text-xs")}>
            <SelectValue />
          </span>
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} className={cn(o.mono && "font-mono text-xs")}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
