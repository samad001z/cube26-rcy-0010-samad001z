"use client";

import { useActionState } from "react";

import { type FormState, overrideDecision } from "@/app/actions";
import type { DecisionValue } from "@/lib/types";

const OPTIONS: { value: DecisionValue; text: string }[] = [
  { value: "CLAIM", text: "Claim: file for the charge not yet reimbursed" },
  { value: "DO_NOT_CLAIM", text: "Do not claim" },
  { value: "REVIEW", text: "Back to review" },
];

const initial: FormState = { error: null };

export function OverrideForm({
  recordId,
  current,
  pending,
  blocked,
}: {
  recordId: string;
  current: DecisionValue;
  pending: boolean;
  blocked: boolean;
}) {
  const [state, action, busy] = useActionState(overrideDecision, initial);
  if (blocked) {
    return <p className="text-sm text-fail">Overrides are blocked: the stored history does not verify.</p>;
  }
  const choices = OPTIONS.filter((o) => o.value !== current && !(pending && o.value === "CLAIM"));
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="record_id" value={recordId} />
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium text-muted">Change the decision to</legend>
        {choices.map((o) => (
          <label key={o.value} className="flex items-start gap-2 text-sm">
            <input type="radio" name="new_decision" value={o.value} required className="mt-1" />
            <span>{o.text}</span>
          </label>
        ))}
        {pending && (
          <p className="text-[11px] text-muted">
            Claim is not offered: the engine did not finish on this charge, so amounts already reimbursed are unknown.
          </p>
        )}
      </fieldset>
      <div>
        <label htmlFor="reason" className="text-xs font-medium text-muted">
          Reason (stored with the override)
        </label>
        <textarea
          id="reason"
          name="reason"
          required
          minLength={3}
          maxLength={2000}
          rows={3}
          className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-sm"
        />
      </div>
      <div>
        <label htmlFor="reviewer" className="text-xs font-medium text-muted">
          Reviewer
        </label>
        <input
          id="reviewer"
          name="reviewer"
          required
          maxLength={64}
          pattern="[A-Za-z0-9][A-Za-z0-9 ._@\-]{0,63}"
          className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-sm"
        />
      </div>
      {state.error && (
        <p role="alert" className="text-sm text-fail">
          {state.error}
        </p>
      )}
      {state.ok && (
        <p role="status" className="text-sm text-pass">
          {state.ok}
        </p>
      )}
      <button disabled={busy} className="rounded-md bg-ink px-3 py-1.5 text-sm font-medium text-bg disabled:opacity-60">
        {busy ? "Saving…" : "Save override"}
      </button>
    </form>
  );
}
