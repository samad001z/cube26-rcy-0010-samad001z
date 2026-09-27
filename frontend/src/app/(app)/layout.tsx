import { Building2, LogOut } from "lucide-react";
import Link from "next/link";
import { redirect, unstable_rethrow } from "next/navigation";
import { Suspense } from "react";

import { logout } from "@/app/actions";
import { Brand } from "@/components/shell/brand";
import { MobileNav } from "@/components/shell/mobile-nav";
import { Nav } from "@/components/shell/nav";
import { RunSwitcher } from "@/components/shell/run-switcher";
import { Button } from "@/components/ui/button";
import { api, currentKey, currentOrg } from "@/lib/api";
import type { Run } from "@/lib/types";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  if (!(await currentKey())) redirect("/login");
  let runs: Run[] = [];
  try {
    runs = await api<Run[]>("/runs");
  } catch (err) {
    unstable_rethrow(err); // a rejected key redirects to the login page
    // Backend down: the page itself shows the error; the shell still renders.
  }
  const org = await currentOrg();

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-border bg-surface lg:flex">
        <Link href="/" className="flex h-14 items-center border-b border-border px-4">
          <Brand />
        </Link>
        <div className="flex-1 p-3">
          <Nav />
        </div>
        <p className="border-t border-border p-4 text-xs leading-relaxed text-muted-foreground">
          Decisions come from the rule engine. A reviewer can change one, with a reason; the
          engine&apos;s record is kept.
        </p>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-surface px-4 sm:gap-3 sm:px-6">
          <MobileNav />
          <Link href="/" className="lg:hidden" aria-label="Alibi, decisions">
            <Brand subtitle={false} />
          </Link>
          <div className="min-w-0">
            <Suspense fallback={<div className="h-9 w-40 rounded-md border border-border" />}>
              <RunSwitcher runs={runs} />
            </Suspense>
          </div>
          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <span
              className="hidden items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground md:flex"
              title="Organisation of the API key you signed in with"
            >
              <Building2 className="size-4" aria-hidden />
              {org ? <span className="font-mono text-xs text-foreground">{org}</span> : "Signed in"}
            </span>
            <form action={logout}>
              <Button variant="subtle" size="sm" type="submit">
                <LogOut aria-hidden />
                <span className="hidden sm:inline">Sign out</span>
                <span className="sr-only sm:hidden">Sign out</span>
              </Button>
            </form>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
