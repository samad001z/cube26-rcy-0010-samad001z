# Labelling guide: Alibi evaluation

Read this once, fully, before you label anything. It takes about 10 minutes. You do not need to know anything about e-commerce beforehand.

---

## 1. What you are doing, in one paragraph

An online seller sends products to Amazon's warehouses. Amazon sometimes charges the seller fees, or reports that it lost or damaged the seller's products. Some of those charges are wrong. The seller's own team keeps records at every step (what arrived, how it was packed, what came back from customers). Your job: for each case, read the charge and the records, and decide **should the seller dispute this charge (CLAIM), accept it (DO NOT CLAIM), or does a person need to look closer (REVIEW)?**

You are the "answer key". An AI agent will be scored against your answers, so **your honest judgement matters more than speed**.

---

## 2. The three answers

| Answer | Use it when | The question to ask yourself |
|---|---|---|
| **CLAIM** | The records clearly prove the charge is wrong, you can tell how much money to ask for, and it is not too late to ask. | "Could the seller file this dispute today and win it with these records?" |
| **DO NOT CLAIM** | The records show the charge is correct, or the seller is owed nothing, or it is too late to file. | "Would disputing this be wrong or pointless?" |
| **REVIEW** | Records are missing, unclear, contradict each other, or the amount owed cannot be worked out. | "Do I need more information before I could decide?" |

### The golden rule
**A wrong CLAIM is much worse than a missed one.** Filing a false dispute damages the seller's reputation with Amazon. Missing a valid one only costs money. **If you are unsure between CLAIM and REVIEW, choose REVIEW.**

---

## 3. The charge line: what each field means

Each case starts with one line from Amazon's report.

| Field | Meaning |
|---|---|
| `line_id` | The ID of this charge line |
| `charge_type` | What Amazon is charging for (see section 4) |
| `unit_id`, `sku` | Which product unit this is about |
| `fba_shipment_id` | The shipment the seller sent to Amazon's warehouse |
| `order_id` | The customer order, if there was one |
| `quantity` | How many units the line covers |
| `amount_usd` | For fees: money Amazon **took**. For losses: money Amazon **already paid back** (0.00 means Amazon paid nothing) |
| `posted_date` | When the line appeared on the report |
| `defect_category` | For defect fees only: which problem Amazon says it found (may be blank) |

---

## 4. The five charge types, in plain words

**1. Inbound defect fee.** Amazon says the product arrived at its warehouse badly prepared (wrong label, missing plastic bag, missing warning sticker) and charges a fee.
Ask: *Does the line say which defect? Did the seller's prep team check exactly that thing, and did it pass, before the shipment left?*

**2. Fulfilment fee (weight tier).** Amazon charges a shipping fee based on how heavy or big it thinks the product is.
Ask: *Is there any record of the product's actual measured weight or size? Without a measurement, you cannot prove the fee is wrong.*

**3. Lost inbound.** Amazon says a unit went missing after the seller sent it.
Ask: *Is there proof the seller actually sent it? Is there any later record showing the unit turned up again (for example, a customer returned it)? Do we know what the unit is worth?*

**4. Damaged in warehouse.** Amazon says a unit was damaged inside its warehouse.
Ask: *Did the unit leave the seller in good condition? Do we know what it is worth? Is it still within the time allowed to file?*

**5. Refund issued, item not returned.** Amazon refunded a customer, and says the customer never sent the item back.
Ask: *Does the returns record show the item came back? If it came back complete and in good condition, the seller has their item and is owed nothing. If it came back damaged or incomplete, that is a different problem: REVIEW.*

---

## 5. The evidence records

You will see a short summary of records from up to four teams:

| Team | What they record |
|---|---|
| **Receiving** | What arrived from the supplier: counts, damage on arrival |
| **Prep** | How each unit was prepared before going to Amazon: label, plastic bag, warning stickers, barcode |
| **Pack** | What went into a box for orders the seller ships themselves |
| **Returns** | What came back from customers: right item, all parts, condition |

Each check in a record is one of:
- **PASS**: checked and fine
- **FAIL**: checked and not fine
- **UNCERTAIN**: the person could not tell (bad photo, unclear). Treat it as "we don't know", never as a pass.

---

## 6. Things that change the answer

1. **Timing.** Evidence only counts if it was recorded at the right moment. A prep check recorded *after* the shipment left cannot prove the unit was fine when it left.
2. **Same unit, same shipment.** A record about a *different* product or shipment proves nothing about this charge, even if it looks similar.
3. **Duplicates.** If Amazon charged the exact same fee twice for the same thing, the second one is wrong: CLAIM for the second.
4. **Already paid back.** If a separate line shows Amazon already refunded this charge, there is nothing left to claim: DO NOT CLAIM.
5. **Deadlines.** Some claims can only be filed within a time window. The case summary will say if a deadline is known to have passed (DO NOT CLAIM) or not yet opened (REVIEW).
6. **Unknown amount.** If the charge is probably wrong but nobody can say how much money is owed, the answer is REVIEW, not CLAIM.

---

## 7. Three worked examples

**Example A**
Charge: inbound defect fee, $2.00, defect_category = "missing suffocation warning".
Prep record for this unit and shipment, recorded before shipping: suffocation warning = PASS, all other checks PASS.
**Answer: CLAIM.** Reason: the exact defect Amazon charged for was checked and passed before the shipment left.

**Example B**
Charge: refund issued, item not returned, $0.00 paid to seller.
Returns record: the ordered item came back, all parts present, condition good.
**Answer: DO NOT CLAIM.** Reason: the item came back, so the seller has it. Nothing is owed.

**Example C**
Charge: inbound defect fee, $1.00, defect_category blank.
Prep record: all checks PASS.
**Answer: REVIEW.** Reason: prep looks fine, but we don't know which defect Amazon found, so we can't prove the records cover it.

---

## 8. How to label

1. Open **your own copy** of the sheet: Labeller A uses `labels_A.csv`, Labeller B uses `labels_B.csv`.
2. For each case, fill two columns:
   - `label`: exactly one of `CLAIM`, `DO_NOT_CLAIM`, `REVIEW`
   - `reason`: one short sentence, in your own words
3. Aim for about 1 minute per case. If a case takes more than 3 minutes, choose REVIEW and note why.

### The rules that make this a fair test
- **Do not discuss cases with the other labeller** until both of you have finished and saved.
- **Do not look at the other person's sheet**, or at anything the AI agent produced.
- **Do not go back and change answers** after you finish. First instinct, written down, is what we measure.
- Disagreeing with the other labeller is **fine and expected**. Disagreements are recorded and discussed afterwards. They show which cases are genuinely hard.

Thank you. Your careful answers are what make the evaluation honest.

---

## 9. Reading the sheet

- **Treat 2026-09-27 as today** for every deadline. Each case's last line gives its deadline status as of that date.
- **"the work order did not require X"**: that check was not needed for this product, so it was never checked. It is not a PASS or a FAIL.
- **"recorded: ..."** after a PASS, FAIL or UNCERTAIN: the exact value the team wrote down.
- **Operator decision** (Returns records): what the team did with the returned item.
  - **restock**: put back into stock as sellable.
  - **refurbish**: needs repair before it can be sold.
  - **liquidate**: sold off cheaply.
  - **dispose**: thrown away.
- **PENDING**: the team has not finalised this record yet.
- **"Other report line for this unit"**: another line on Amazon's report about the same unit.
