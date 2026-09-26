"use client";

import { useActionState } from "react";

import { type FormState, login } from "@/app/actions";

const initial: FormState = { error: null };

export function LoginForm() {
  const [state, action, pending] = useActionState(login, initial);
  return (
    <form action={action} className="mt-5 space-y-3">
      <label htmlFor="key" className="block text-sm font-medium">
        API key
      </label>
      <input
        id="key"
        name="key"
        type="password"
        autoComplete="off"
        required
        className="w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-sm"
      />
      {state.error && (
        <p role="alert" className="text-sm text-fail">
          {state.error}
        </p>
      )}
      <button
        disabled={pending}
        className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-bg disabled:opacity-60"
      >
        {pending ? "Checking…" : "Sign in"}
      </button>
    </form>
  );
}
