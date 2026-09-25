# PR/FAQ: Alibi, the Recovery Manager

## Press release

**Alibi turns a seller's own warehouse records into claims Amazon can't wave away**

*Day 14 of the CUBE Buildathon*

Ecommerce sellers are charged fees they don't owe and are owed reimbursements they never claim. The reason isn't lack of effort. Charges post weeks after the event, and by then the proof of what happened is scattered across the teams that received, prepped, packed and handled returns for each unit.

Alibi is the fifth step in a chain of five agents that follow a single unit from supplier delivery to money back. It reads the records the other four Managers produce, matches them against the channel's fee and reimbursement reports, and decides for each charge whether the seller's evidence **contradicts** it, **supports** it, or is **silent**. Where evidence contradicts a charge, Alibi assembles a claim: the dollar figure with its arithmetic, and the exact records attached. Where it can't, it says so, and names the record that would have changed the answer.

"The goal is not the most claims," said the builder. "It's claims a seller can stand behind. A wrongly filed claim costs a seller standing with the channel. A missed one only costs money. So we measure precision first."

Alibi was evaluated on a held-out set of charges, each labelled independently by two people. The eval report lists precision, false positives and false negatives per charge type, and the failure modes behind them.

## External FAQ (sellers)

**What does Alibi need from me?**
The fee and reimbursement reports from your channel, and the records your team (or your prep partner and 3PL) already capture at receiving, prep, pack and returns.

**Will it file claims for me?**
No. It prepares the claim and the evidence. A person reviews it and files it. Every claim can be overridden, and the override and its reason are kept.

**What happens when it isn't sure?**
It says UNCERTAIN, and shows you which records disagree. Uncertain is an answer, not a failure.

**Where do the fee rules come from?**
From the channel's published documentation, retrieved and cited. Not from memory, and not from example data.

**Can another seller see my data?**
No. Every table is isolated per organisation at the database level, and that isolation is tested.

## Internal FAQ (the questions we'd rather not answer)

**What if the other four pods don't hold their record shape?**
Then Alibi can't match. This is the biggest dependency in the whole product. We are proposing a contract in week one and will report every day a field changed.

**What if the records we need don't exist?**
Some don't. The sample Prep records don't capture weight or dimensions, so a weight-tier fulfilment fee can't be contradicted by anything upstream today. Alibi will mark those SILENT. If most charges end up SILENT, the product doesn't work yet, and that is one of our kill conditions.

**Is "unit" really one physical unit?**
Not in the sample data. A Receiving record covers a purchase-order line of dozens of units, while a fee line covers one. If the pods can't agree what a unit is, matching becomes ambiguous. We've raised this as a finding.

**Why should a seller trust a claim the AI wrote?**
The AI doesn't decide. Verdicts come from explicit rules over the records; the model reads messy text and writes the explanation. Every claim shows the rule that fired and the records it used.

**Isn't this just what recovery agencies already do?**
Agencies are paid a percentage of what they recover, so the incentive is volume. Alibi's metric is precision, and it tells you what it chose not to claim.

**How good is it, honestly?**
We will report the number we measure, broken down by charge type, including where it fails. If two human labellers can't agree on the right verdict, we'll report that too, because it means the task itself is ambiguous.

**What happens to a claim on a unit whose evidence is changed later?**
Every record Alibi cites is stored with a content hash, so we can show whether the record it used is the one you're looking at now. That is a content hash, not a tamper-proof ledger.
