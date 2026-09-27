import { Lock } from "lucide-react";
import type { Metadata } from "next";

import { Brand } from "@/components/shell/brand";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { expired } = await searchParams;
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Brand />
        </div>
        <div className="rounded-xl border border-border bg-surface p-6 shadow-card">
          <h1 className="text-lg font-semibold tracking-tight">Sign in to review decisions</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Alibi checks each fee and reimbursement charge against warehouse records and decides:
            claim, do not claim, or review, with the evidence behind it.
          </p>
          <LoginForm expired={Boolean(expired)} />
        </div>
        <p className="mt-4 flex gap-2 px-1 text-xs leading-relaxed text-muted-foreground">
          <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            Your key is kept in an httpOnly cookie for 8 hours. Scripts on this page cannot read
            it; only this server sends it to the Alibi API.
          </span>
        </p>
      </div>
    </main>
  );
}
