# PayRight — for the judges

Cashfree x Sarvam Buildathon, 21 Nov 2026, Problem Statement 3: *Pay the right bill, to the right person.*
Team: Chirag, Abhijeet, Bhumika, Ayush. Full problem and architecture: `docs/PayRight_Problem_and_Solution.pdf`.

**In one line:** across 21 invoices in three scripts, read by the live Sarvam reader, **8 of 8 traps were caught, 0 of 13 good bills were stopped (1 was asked about once), and 0 wrong payments were approved.**

---

## 1. Design note

**Our rule: a model reads, code decides, a person approves, and money only goes to the account we already have on file.**

**What we chose**
- **Sarvam Document AI reads; it never decides.** It turns each invoice (printed or handwritten; Tamil, Hindi or English) into fixed fields with a confidence for each. If a critical field (vendor, invoice number, total, account, IFSC) is low-confidence, it is marked *unsure*. The bill then goes to a person instead of being silently fixed.
- **Plain, tested code decides PAY / ASK / STOP** (`payright/check.py`). Every decision carries a reason a shop owner can read aloud. The checks are:
  - Does the arithmetic hold, including the amount in words against the figures?
  - Who is the vendor? Matched by GSTIN, or by name across scripts.
  - Is the bank account on the invoice the one on file?
  - Does that account belong to a *different* vendor on file?
  - Is this a duplicate in disguise?
  - What is the legal deadline? 15 or 45 days for micro and small suppliers.
- **Money only to the account on file.** Bank details for a payment come from `vendors.json`, never from the invoice. The invoice's account is only *compared*. `send.py` also treats `decisions.json` as untrusted and refuses any row whose account differs from the vendor file.
- **One transfer ID per invoice, for life.** It is derived from vendor, invoice number and amount. A write-ahead ledger records each payment *before* it is sent. Running the same batch twice pays nothing the second time, and Cashfree rejects a repeated transfer ID as a second lock.
- **The owner approves by phone, in his language.** A Sarvam voice agent calls Raghu, tells him what is clean and what was stopped and why, and accepts a yes only if he says the total himself. One approval is good for one batch, once.

**What we chose not to use, and why**
- **No LLM deciding about money.** Its answers are not repeatable and not auditable. Code gives the same answer every time, and a test proves it.
- **No trusting bank details printed on an invoice.** A familiar vendor with a new account is the oldest fraud there is.
- **No automatic payment retries.** A failed or reversed payout goes back to a person as ASK. It never becomes a second payment.
- **No payments backend of our own.** Verification and payouts run inside Cashfree Relay, so every run is visible in its Runs tab.
- **No website first.** Time went into the problem, the voice, the money and the live demo.

---

## 2. One success case and one failure case

Both cases come from a real run on 21 Nov 2026: our 8 test invoices went through the live Sarvam reader (advanced mode) and our checker. Results: `payright/scoresheet.md`.

### Success: a handwritten bill, photographed on a counter, read and cleared
`payright/invoices/inv08_wells.jpg` is a red-ruled bill-book page from Wells Paints and Chemicals, filled in by hand. It was photographed at an angle, in uneven light. The date is in short form (`18/11/26`).
- Sarvam read every field the checker needs correctly:
  - invoice no `512`
  - two line items
  - subtotal `8000`, GST `1440`, total `9440`
  - the amount in words, converted to `9440`
  - account `1233943142`, IFSC `ICIC0000009`
- No field was flagged unsure. The arithmetic held, words matched figures, the GSTIN matched Wells, and the account matched the one on file.
- **Decision: PAY**, queued for the owner's approval call.

The Tamil invoice (`inv02`) and the Hindi invoice (`inv03`) were also read correctly, including amounts written in Tamil and Hindi words. Those words were converted to the right numbers.

### Failure caught: a familiar vendor asks to be paid into a new account
`payright/invoices/inv04_hope.png` is a well-formed invoice from Hope Electricals. Everything adds up. The GSTIN and name are right. It carries a polite note: *"our bank account has changed. Kindly pay only to the new account below."* The account is `026291800001190` at Yes Bank. The account on file is `388108022658` at ICICI.
- Nothing about the bill *looks* wrong, and that is the danger.
- The checker compares the invoice's account with the account on file and **STOPs**:


  > The bank account on this invoice is not the account we have on file for Hope Electricals. Call the vendor on the number we already have before paying.

- On the call, the agent tells Raghu in Hindi that the bank account changed and he should call the vendor on the old number first. The bill is not in the batch he approves. Even if someone edited the decision file, `send.py` would refuse it, because the account is not the one on file.

Two other traps were stopped with their own reasons:
- **A duplicate in disguise:** `DH-0101` came back as `dh/101`, with a new date format and layout.
- **A borrowed account:** Jane D Traders asked to be paid into John Doe's account.

**Score on our set:** traps caught **4 / 4**, good invoices wrongly blocked **0 / 4**.

---

## 3. Evidence: 21 invoices, scored field by field

We did not stop at the demo set. We built 21 invoices ourselves, so we know every value truly printed on each one. Each went through the live Sarvam reader and our real checker. Full report, with every invoice image beside what was read: `docs/evidence/PayRight_Evidence.pdf`.

| | Demo set (8) | Stress set (8) | Fail-safe ladder (5) | **All 21** |
|---|---|---|---|---|
| Traps caught before money moved | 4 / 4 | 3 / 3 | 1 / 1 | **8 / 8** |
| Clean invoices wrongly stopped | 0 / 4 | 0 / 5 (1 asked) | 0 / 4 | **0 / 13** (1 asked) |
| Wrong payments approved | 0 | 0 | 0 | **0** |
| Critical fields read exactly right | 78 / 80 | 77 / 80 | 45 / 50 | **200 / 210 (95%)** |

- **Stress set:** each invoice targets a check the demo set does not:
  - the amount in words disagrees with the figures
  - one line multiplied wrong
  - a Hindi bill in Devanagari digits
  - a misspelt vendor name
  - the same bill re-sent with a new number
  - a dim handwritten photo
  - a total above one lakh, with the words in lakh notation
- **Fail-safe ladder:** the same kind of clean bill, photographed from a flat scan down to barely readable. The first four were all paid correctly. The fifth was refused.
- **What the ladder taught us.** On the unreadable photo, Sarvam invented a bank account (`0123456789012345`), a GSTIN and a 2023 date. It scored that account at confidence 0. Our reader was treating a 0 as fully sure, because in Python `0 or 1` is `1`. We fixed it, and a 0 now marks the field unsure. The bill was never at risk: code compares every account with the one on file. **This is our design working. We do not trust the model's confidence; we cross-check what it reads.**
- **Honest gaps:**
  - On the Devanagari-digit bill, Sarvam read the total right but was unsure of it (0.5), so the owner gets asked once. That is a cautious result, not a wrong one.
  - The letter O inside one vendor's GSTIN is read as zero every time. That is harmless, because the vendor is then matched by name.
  - We first expected the worst photo to be PAY or ASK. Paying on a photo nobody can read would be wrong, so it now expects ASK or STOP.

---

## 4. Six-minute demo script

**Roles:** Chirag drives the laptop. Bhumika narrates. Ayush has Raghu's phone. Abhijeet watches the terminal for errors and calls the fallback.

**Before the judges sit down**
- Terminal open in the repo root.
- Relay Runs tab open, and the Cashfree Payouts test dashboard open.
- `payright/ledger.json` cleared, so the first run pays and the second run proves no double pay.
- Phone charged, volume up, on speaker.

| Time | Who | On screen | What we say |
|---|---|---|---|
| 0:00 to 0:40 | Bhumika | the 8 invoice images, side by side | **Problem.** "Raghu runs a hardware wholesale in Chennai. Sixty invoices a week, in Tamil, Hindi and English, some handwritten. One of these eight is from a real vendor asking to be paid into a new account. It looks perfect. Last month a bill like that would have been paid." |
| 0:40 to 1:40 | Chirag | `python payright/run.py payright/invoices ta-IN --cash 100000` | **The doctored invoice goes in.** "Sarvam reads all eight, including the handwritten photo and the Tamil and Hindi amounts in words. The model only reads. Plain code decides." |
| 1:40 to 2:40 | Bhumika | the PAY / LATER / STOP table, pointing at row HE-310 | **The agent refuses and says why.** Read the STOP reason aloud. Then point at the duplicate `dh/101` and at Jane D Traders using John Doe's account. "Every refusal has a reason a shop owner understands. Money only ever goes to the account on file." |
| 2:40 to 4:00 | Ayush | phone on speaker, the call live | **The owner approves by phone.** The agent says how many bills are clean and the total, which were stopped and why, in Hindi. Raghu must say the total aloud. The terminal prints `APPROVED`. |
| 4:00 to 4:50 | Chirag | Relay Runs tab, then the Payouts test dashboard | **The payouts show as successful.** Open one transfer and show its transfer ID. "That ID comes from the invoice itself, not from this attempt." |
| 4:50 to 5:20 | Chirag | run the same command again | **Nothing is paid twice.** Every row comes back as already sent. Nothing new appears in Relay. |
| 5:20 to 6:00 | Bhumika | the `SCORE` line, then the top of `docs/evidence/PayRight_Evidence.pdf` | **Our numbers.** "Twenty-one invoices, scored field by field against what is truly printed: eight of eight traps caught, zero good bills stopped, zero wrong payments. On a photo nobody could read, the AI invented a bank account. Our code refused it." Then the judges' fresh batch numbers, if we got one. Close: "A model reads, code decides, a person approves, and money only goes to the account on file." |

**Fallbacks**
- **Reading is slow** (more than about 60 s): stop it and run `python payright/run.py payright/invoices.json --cash 100000`. That uses the invoices already read this afternoon. Say so honestly.
- **The call does not connect:** show `python payright/run.py payright/invoices.json --dry-run` to show what the agent would say, and play the recorded test call. Do not use `--fake` on stage without saying it is a simulated answer.
- **Payouts fail** (IP whitelist, or no test balance): show the failed run in Relay's Runs tab. Say that a failed payout goes back to a person and is never retried. That *is* our design.

**Rehearsals: write the real times here**

| Run | Problem | Read and check | Refusal | Call | Payouts | Re-run | Numbers | Total |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
