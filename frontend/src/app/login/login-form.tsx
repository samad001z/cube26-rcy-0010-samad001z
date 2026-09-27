"use client";

import { CircleAlert, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { useActionState, useState } from "react";

import { type FormState, login } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const initial: FormState = { error: null };

export function LoginForm({ expired }: { expired: boolean }) {
  const [state, action, pending] = useActionState(login, initial);
  const [show, setShow] = useState(false);
  const error = state.error ?? (expired ? "Your key is no longer accepted. Sign in again." : null);
  return (
    <form action={action} className="mt-5 space-y-4" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="key">API key</Label>
        <div className="relative">
          <Input
            id="key"
            name="key"
            type={show ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            required
            autoFocus
            placeholder="Paste your organisation's key"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "key-error" : "key-hint"}
            className="pr-10 font-mono placeholder:font-sans"
          />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-pressed={show}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground"
          >
            {show ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            <span className="sr-only">{show ? "Hide key" : "Show key"}</span>
          </button>
        </div>
        {error ? (
          <p id="key-error" role="alert" className="flex items-start gap-1.5 text-sm text-fail">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {error}
          </p>
        ) : (
          <p id="key-hint" className="text-xs text-muted-foreground">
            One key per organisation. Ask your administrator if you do not have one.
          </p>
        )}
      </div>
      <Button type="submit" variant="primary" className="w-full" disabled={pending}>
        {pending && <LoaderCircle className="animate-spin" aria-hidden />}
        {pending ? "Checking key…" : "Sign in"}
      </Button>
    </form>
  );
}
