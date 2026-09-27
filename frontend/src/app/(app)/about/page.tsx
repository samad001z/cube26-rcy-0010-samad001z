import type { Metadata } from "next";

import { DecisionChip } from "@/components/status";
import { Card, CardBody } from "@/components/ui/card";
import type { DecisionValue } from "@/lib/types";

export const metadata: Metadata = { title: "About" };

const OUTCOMES: { d: DecisionValue; text: string }[] = [
  {
    d: "CLAIM",
    text: "Upstream records contradict the charge for every charged unit, or the fee is a repeat of an earlier line. The claim is the charge minus anything already reimbursed.",
  },
  {
    d: "DO_NOT_CLAIM",
    text: "The records support the charge, it has already been paid back, it is a refund line, or a sourced filing deadline has passed.",
  },
  {
    d: "REVIEW",
    text: "The evidence is missing, conflicting, outside the relevant dates, or cannot settle the charge. A person decides. REVIEW is a normal outcome, never a failure to hide.",
  },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="space-y-2 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  );
}

export default function AboutPage() {
  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">About Alibi</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Alibi is the Recovery Manager. It reads fee, reimbursement and adjustment reports, matches each charge to
          records from Receiving, Prep, Pack and Returns, and answers one question per charge: should it be
          recovered, and can you show why?
        </p>
      </div>

      <Card>
        <CardBody className="divide-y divide-border p-0">
          {OUTCOMES.map((o) => (
            <div key={o.d} className="grid gap-2 p-4 sm:grid-cols-[150px_minmax(0,1fr)] sm:gap-4">
              <div>
                <DecisionChip value={o.d} />
              </div>
              <p className="text-sm">{o.text}</p>
            </div>
          ))}
        </CardBody>
      </Card>

      <Section title="Who decides">
        <p>
          Every decision comes from a fixed, ordered set of rules in the backend. The first rule that matches fires,
          and the decision records the rule, the checks it read, the evidence it cited and a content hash. No
          language model sets a decision, an amount or a citation. This page only shows what the backend returns;
          it does not compute amounts.
        </p>
        <p>
          <span className="font-medium text-foreground">Routing confidence</span> says how directly the recorded
          data settles the check a decision rests on: 1.00 for an exact comparison of ingested data, 0.90 for an
          operator&apos;s recorded check. It is not the chance that a decision is right. Accuracy is measured only on
          a held-out set labelled by two people.
        </p>
      </Section>

      <Section title="Evidence and dates">
        <p>
          A record counts only if it was made inside its pod&apos;s custody window around the date the charge was
          posted. Filing deadlines come only from the channel&apos;s published documentation, stored with the
          source; where none has been sourced yet, the deadline shows as not verified.
        </p>
      </Section>

      <Section title="Overrides">
        <p>
          A reviewer can change a decision with a written reason. The override is stored next to the engine&apos;s
          record, which is kept, and both appear in the history. The backend refuses a CLAIM it cannot support, for
          example on a loss event or when the amount is not the charge itself.
        </p>
        <p>
          The reviewer name is typed by the person making the change: the API key identifies an organisation, not a
          person.
        </p>
      </Section>

      <Section title="Demo data">
        <p>
          <span className="font-medium text-foreground">Run a report → Load demo data</span> decides a small,
          made-up report built to show all three outcomes. It is not the sample data and not the evaluation set, and
          no result from it is an accuracy figure.
        </p>
      </Section>
    </div>
  );
}
