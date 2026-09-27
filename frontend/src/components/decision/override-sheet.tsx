"use client";

import { Ban, CircleAlert, CircleCheck, LoaderCircle, Lock, UserPen } from "lucide-react";
import { type ReactNode, useActionState, useEffect, useRef, useState } from "react";

import { type FormState, overrideDecision } from "@/app/actions";
import { DECISION, DecisionChip } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import type { DecisionValue } from "@/lib/types";
import { cn } from "@/lib/utils";

const OPTIONS: { value: DecisionValue; text: string }[] = [
  { value: "CLAIM", text: "File for the part of the charge not yet reimbursed." },
  { value: "DO_NOT_CLAIM", text: "The charge stands; nothing is filed." },
  { value: "REVIEW", text: "Send it back to review." },
];

const initial: FormState = { error: null };

/**
 * Side sheet to change a decision. The backend checks every rule again and refuses what is
 * not allowed; this form only mirrors its answer (claimRefusal) so CLAIM is not offered.
 */
export function OverrideSheet({
  recordId,
  current,
  claimRefusal,
  blocked,
  history,
}: {
  recordId: string;
  current: DecisionValue;
  claimRefusal: string | null;
  blocked: string | null;
  history: ReactNode;
}) {
  const [state, action, busy] = useActionState(overrideDecision, initial);
  const [choice, setChoice] = useState<string>("");
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.ok) {
      form.current?.reset();
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear the choice after a saved override
      setChoice("");
    }
  }, [state]);

  const choices = OPTIONS.filter((o) => o.value !== current);

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="primary">
          <UserPen aria-hidden />
          Override decision
        </Button>
      </SheetTrigger>
      <SheetContent
        title="Override decision"
        description="Your change is stored next to the engine's decision, with your reason. The engine's record is kept."
      >
        <div className="space-y-6 p-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            Current decision <DecisionChip value={current} size="sm" />
          </div>

          {blocked ? (
            <p className="flex items-start gap-2 rounded-md border border-fail-line bg-fail-soft p-3 text-sm text-fail">
              <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
              {blocked}
            </p>
          ) : (
            <form ref={form} action={action} className="space-y-5">
              <input type="hidden" name="record_id" value={recordId} />
              <fieldset className="space-y-2">
                <legend className="mb-2 text-sm font-medium">New decision</legend>
                <RadioGroup name="new_decision" required value={choice} onValueChange={setChoice}>
                  {choices.map((o) => {
                    const refused = o.value === "CLAIM" && claimRefusal !== null;
                    const id = `opt-${o.value}`;
                    return (
                      <div
                        key={o.value}
                        className={cn(
                          "flex gap-3 rounded-md border p-3",
                          refused ? "border-dashed border-border bg-surface-2" : "border-border",
                          choice === o.value && "border-accent ring-1 ring-accent",
                        )}
                      >
                        <RadioGroupItem value={o.value} id={id} disabled={refused} aria-describedby={`${id}-text`} />
                        <div className="min-w-0 flex-1">
                          <Label htmlFor={id} className={cn(refused && "opacity-70")}>
                            <DecisionChip value={o.value} size="sm" />
                          </Label>
                          <p id={`${id}-text`} className="mt-1 text-xs text-muted-foreground">
                            {refused ? (
                              <span className="flex items-start gap-1.5 text-foreground">
                                <Ban className="mt-px size-3.5 shrink-0 text-fail" aria-hidden />
                                <span>
                                  <span className="font-medium">Not available:</span> {claimRefusal}.
                                </span>
                              </span>
                            ) : (
                              o.text
                            )}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </RadioGroup>
              </fieldset>

              <div className="space-y-1.5">
                <Label htmlFor="reason">
                  Reason <span className="font-normal text-muted-foreground">(required)</span>
                </Label>
                <Textarea
                  id="reason"
                  name="reason"
                  required
                  minLength={3}
                  maxLength={2000}
                  rows={4}
                  placeholder="What you checked and why the decision should change"
                  aria-describedby="reason-hint"
                />
                <p id="reason-hint" className="text-xs text-muted-foreground">
                  Stored with the override and shown in its history.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="reviewer">Reviewer</Label>
                <Input
                  id="reviewer"
                  name="reviewer"
                  required
                  maxLength={64}
                  autoComplete="name"
                  pattern="[A-Za-z0-9][A-Za-z0-9 ._@\-]{0,63}"
                  aria-describedby="reviewer-hint"
                />
                <p id="reviewer-hint" className="text-xs text-muted-foreground">
                  Your name as you type it; the API key identifies the organisation, not you.
                </p>
              </div>

              {state.error && (
                <p role="alert" className="flex items-start gap-2 text-sm text-fail">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {state.error}
                </p>
              )}
              {state.ok && (
                <p role="status" className="flex items-start gap-2 text-sm text-pass">
                  <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {state.ok}
                </p>
              )}

              <Button type="submit" variant="primary" className="w-full" disabled={busy || !choice}>
                {busy && <LoaderCircle className="animate-spin" aria-hidden />}
                {busy ? "Saving…" : choice ? `Save as ${DECISION[choice as DecisionValue].word}` : "Save override"}
              </Button>
            </form>
          )}

          <section aria-labelledby="sheet-history" className="border-t border-border pt-5">
            <h3 id="sheet-history" className="mb-3 text-sm font-semibold">
              History
            </h3>
            {history}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
