"use client";

import {
  type ColumnDef,
  type SortingState,
  columnFilteringFeature,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  flexRender,
  globalFilteringFeature,
  rowPaginationFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  CircleAlert,
  Clock,
  History,
  SearchX,
  UserPen,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { Money } from "@/components/money";
import { EmptyState } from "@/components/notice";
import { DECISION, DecisionChip } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, Td, Th } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { headline } from "@/lib/reasons";
import type { DecisionList, DecisionSummary, DecisionValue } from "@/lib/types";
import { cn, compareDecimal, dateTime, sentence } from "@/lib/utils";

import { SearchBox } from "./search-box";
import { FilterSelect } from "./filter-select";

const ORDER: DecisionValue[] = ["REVIEW", "CLAIM", "DO_NOT_CLAIM"];
const PAGE_SIZE = 25;

const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  rowSortingFeature,
  rowPaginationFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
});

type Filters = { run?: string; show?: DecisionValue; type?: string; rule?: string };

function detailHref(i: DecisionSummary) {
  return `/decisions/${encodeURIComponent(i.record_id)}`;
}

/** Badges under the decision chip: overridden, pending, history problems, earlier override. */
function Flags({ i, tooltips = true }: { i: DecisionSummary; tooltips?: boolean }) {
  const flags = [];
  if (i.override_count > 0)
    flags.push(
      <Badge key="o" tone="outline" size="sm">
        <UserPen aria-hidden />
        Engine said {DECISION[i.engine_decision].word}
      </Badge>,
    );
  if (i.status === "pending")
    flags.push(
      <Badge key="p" tone="fail" size="sm">
        <Clock aria-hidden />
        Pending
      </Badge>,
    );
  if (i.integrity_problems.length > 0)
    flags.push(
      <Badge key="h" tone="fail" size="sm">
        <CircleAlert aria-hidden />
        History does not verify
      </Badge>,
    );
  if (i.earlier_override) {
    const e = i.earlier_override;
    const badge = (
      <Badge tone="review" size="sm">
        <History aria-hidden />
        Earlier override: {DECISION[e.decision].word}
      </Badge>
    );
    flags.push(
      !tooltips ? (
        <span key="e">{badge}</span>
      ) : (
      <Tooltip
        key="e"
        content={
          <>
            On an earlier run, {e.reviewer} set this line to {DECISION[e.decision].word} ({dateTime(e.at)}):
            &ldquo;{e.reason}&rdquo;. Overrides are not carried over to new runs.
          </>
        }
      >
        <button type="button" className="rounded-md" onClick={(ev) => ev.stopPropagation()}>
          {badge}
        </button>
      </Tooltip>
      ),
    );
  }
  return flags.length ? <div className="mt-1.5 flex flex-wrap gap-1">{flags}</div> : null;
}

function SortIcon({ dir }: { dir: false | "asc" | "desc" }) {
  if (dir === "asc") return <ArrowUp className="size-3.5" aria-hidden />;
  if (dir === "desc") return <ArrowDown className="size-3.5" aria-hidden />;
  return <ChevronsUpDown className="size-3.5 opacity-50" aria-hidden />;
}

export function DecisionsTable({
  items,
  total,
  facets,
  filters,
}: {
  items: DecisionSummary[];
  total: number;
  facets: DecisionList["facets"];
  filters: Filters;
}) {
  const router = useRouter();
  const [navigating, startTransition] = useTransition();
  const [sorting, setSorting] = useState<SortingState>([{ id: "decision", desc: false }]);
  const [search, setSearch] = useState("");

  const columns = useMemo<ColumnDef<typeof features, DecisionSummary>[]>(
    () => [
      {
        id: "decision",
        header: "Decision",
        accessorFn: (i) => i.decision,
        sortFn: (a, b) =>
          ORDER.indexOf(a.original.decision) - ORDER.indexOf(b.original.decision) ||
          a.original.line_id.localeCompare(b.original.line_id),
        cell: ({ row }) => (
          <>
            <DecisionChip value={row.original.decision} size="sm" />
            <Flags i={row.original} />
          </>
        ),
      },
      {
        id: "line",
        header: "Line",
        accessorFn: (i) => i.line_id,
        cell: ({ row }) => (
          <>
            <Link
              href={detailHref(row.original)}
              className="font-mono text-xs font-medium text-accent-text hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {row.original.line_id}
            </Link>
            <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">{row.original.unit_id}</div>
          </>
        ),
      },
      {
        id: "type",
        header: "Charge type",
        accessorFn: (i) => i.charge_type,
        cell: ({ row }) => <span className="text-sm">{sentence(row.original.charge_type)}</span>,
      },
      {
        id: "why",
        header: "Why",
        enableSorting: false,
        accessorFn: (i) => headline(i.rule_id, i.charge_type, i.reason),
        cell: ({ getValue }) => <p className="line-clamp-2 text-sm">{getValue<string>()}</p>,
      },
      {
        id: "charged",
        header: "Charged",
        accessorFn: (i) => i.amount_charged,
        sortFn: (a, b) => compareDecimal(a.original.amount_charged, b.original.amount_charged),
        cell: ({ row }) => <Money amount={row.original.amount_charged} currency={row.original.currency} />,
      },
      {
        id: "claim",
        header: "Claim",
        accessorFn: (i) => i.claim_amount,
        sortFn: (a, b) => compareDecimal(a.original.claim_amount, b.original.claim_amount),
        cell: ({ row }) => <Money amount={row.original.claim_amount} currency={row.original.currency} />,
      },
    ],
    [],
  );

  const table = useTable({
    features,
    data: items,
    columns,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    // Search matches the line or unit ID only.
    globalFilterFn: (row, _id, value: string) => {
      const q = value.trim().toLowerCase();
      return !q || row.original.line_id.toLowerCase().includes(q) || row.original.unit_id.toLowerCase().includes(q);
    },
    initialState: { pagination: { pageIndex: 0, pageSize: PAGE_SIZE } },
    autoResetPageIndex: true,
  });

  /** Server-side filters live in the URL, so a filtered view can be shared or reloaded. */
  function setFilter(change: Partial<Filters>) {
    const next = { ...filters, ...change };
    const q = new URLSearchParams(Object.entries(next).filter((e): e is [string, string] => !!e[1]));
    startTransition(() => router.push(q.size ? `/?${q}` : "/", { scroll: false }));
  }

  const rows = table.getRowModel().rows;
  const shown = table.getFilteredRowModel().rows.length;
  const anyFilter = !!(filters.show || filters.type || filters.rule || search);
  const { pageIndex } = table.state.pagination;
  const pages = table.getPageCount();

  const cellClass: Record<string, string> = {
    decision: "w-[190px]",
    line: "w-[150px]",
    type: "hidden w-[170px] xl:table-cell",
    why: "",
    charged: "w-[112px] text-right",
    claim: "w-[112px] text-right",
  };

  return (
    <section aria-label="Decisions" className="space-y-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <SearchBox value={search} onChange={setSearch} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 lg:flex lg:flex-1 lg:justify-end">
          <FilterSelect
            label="Decision"
            value={filters.show}
            options={ORDER.map((d) => ({ value: d, label: DECISION[d].word }))}
            onChange={(v) => setFilter({ show: v as DecisionValue | undefined })}
          />
          <FilterSelect
            label="Charge type"
            value={filters.type}
            options={(facets.charge_type ?? []).map((t) => ({ value: t, label: sentence(t) }))}
            onChange={(v) => setFilter({ type: v })}
          />
          <FilterSelect
            label="Rule"
            value={filters.rule}
            wide
            options={(facets.rule_id ?? []).map((r) => ({ value: r, label: r, mono: true }))}
            onChange={(v) => setFilter({ rule: v })}
          />
        </div>
      </div>

      <div className="flex min-h-6 flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <p aria-live="polite">
          Showing <span className="num font-medium text-foreground">{shown}</span> of{" "}
          <span className="num">{total}</span> charges
          {navigating && <span className="ml-2">Updating…</span>}
        </p>
        {anyFilter && (
          <Button
            variant="subtle"
            size="sm"
            onClick={() => {
              setSearch("");
              if (filters.show || filters.type || filters.rule) setFilter({ show: undefined, type: undefined, rule: undefined });
            }}
          >
            <X aria-hidden />
            Clear filters
          </Button>
        )}
      </div>

      {shown === 0 ? (
        <EmptyState icon={<SearchX aria-hidden />} title="No decisions match">
          Nothing in this run matches the search and filters. Clear them to see every charge.
        </EmptyState>
      ) : (
        <div className={cn("transition-opacity", navigating && "opacity-60")}>
          {/* Wide screens: the table. Sticky header sits under the 56px top bar. */}
          <div className="hidden rounded-lg border border-border bg-surface shadow-card lg:block">
            <Table className="table-fixed">
              <thead>
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h, idx) => {
                      const sortable = h.column.getCanSort();
                      const dir = h.column.getIsSorted();
                      return (
                        <Th
                          key={h.id}
                          aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : sortable ? "none" : undefined}
                          className={cn(
                            "sticky top-14 z-10",
                            idx === 0 && "rounded-tl-lg",
                            idx === hg.headers.length - 1 && "rounded-tr-lg",
                            cellClass[h.column.id],
                          )}
                        >
                          {sortable ? (
                            <button
                              type="button"
                              onClick={h.column.getToggleSortingHandler()}
                              className={cn(
                                "-mx-1 inline-flex items-center gap-1 rounded px-1 py-0.5 hover:text-foreground",
                                (h.column.id === "charged" || h.column.id === "claim") && "flex-row-reverse",
                              )}
                            >
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              <SortIcon dir={dir} />
                            </button>
                          ) : (
                            flexRender(h.column.columnDef.header, h.getContext())
                          )}
                        </Th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => router.push(detailHref(row.original))}
                    className="cursor-pointer transition-colors hover:bg-surface-2 [&:last-child>td]:border-b-0"
                  >
                    {row.getAllCells().map((cell) => (
                      <Td key={cell.id} className={cn("align-top", cellClass[cell.column.id])}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>

          {/* Narrow screens: one card per charge, no horizontal scroll. */}
          <ul className="space-y-2 lg:hidden">
            {rows.map(({ original: i }) => (
              <li key={i.record_id}>
                <Link
                  href={detailHref(i)}
                  className="block rounded-lg border border-border bg-surface p-4 shadow-card hover:border-border-strong"
                >
                  <div className="flex items-start justify-between gap-3">
                    <DecisionChip value={i.decision} size="sm" />
                    <Money amount={i.amount_charged} currency={i.currency} className="text-sm" />
                  </div>
                  <p className="mt-2 text-sm font-medium">{headline(i.rule_id, i.charge_type, i.reason)}</p>
                  <p className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                    <span className="font-mono text-accent-text">{i.line_id}</span>
                    <span className="font-mono">{i.unit_id}</span>
                    <span>{sentence(i.charge_type)}</span>
                  </p>
                  {i.claim_amount && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Claim <Money amount={i.claim_amount} currency={i.currency} className="text-foreground" />
                    </p>
                  )}
                  <Flags i={i} tooltips={false} />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>
            Page <span className="num text-foreground">{pageIndex + 1}</span> of <span className="num">{pages}</span>
          </span>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
              <ChevronLeft aria-hidden />
              Previous
            </Button>
            <Button size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
              Next
              <ChevronRight aria-hidden />
            </Button>
          </div>
        </nav>
      )}
    </section>
  );
}
