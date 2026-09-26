import type { Metadata } from "next";
import Link from "next/link";

import { logout } from "@/app/actions";
import { currentKey } from "@/lib/api";

import "./globals.css";

export const metadata: Metadata = {
  title: "Alibi Review",
  description: "Review Recovery Manager decisions: evidence, reasons and human overrides.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const signedIn = Boolean(await currentKey());
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-base font-bold tracking-tight">Alibi</span>
              <span className="text-xs text-muted">Recovery Manager · review</span>
            </Link>
            {signedIn && (
              <nav className="flex items-center gap-4 text-sm">
                <Link href="/" className="hover:underline">
                  Decisions
                </Link>
                <Link href="/run" className="hover:underline">
                  New run
                </Link>
                <form action={logout}>
                  <button className="text-muted hover:text-ink hover:underline">Sign out</button>
                </form>
              </nav>
            )}
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="mx-auto w-full max-w-6xl px-4 pb-6 text-xs text-muted">
          Decisions come from the rule engine. A reviewer can override one, with a reason; the
          engine&apos;s record is kept unchanged.
        </footer>
      </body>
    </html>
  );
}
