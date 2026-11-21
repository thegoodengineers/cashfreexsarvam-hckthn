# Score sheet — demo invoice set

Run on 21 Nov 2026 with the real Sarvam reader (`mode: advanced`, `ta-IN`) and `check.py --cash 100000`.
Invoices: `payright/invoices/` (made by `make_invoices.py`). Expected outcomes: `invoice_answer_key.json`.

| | Result |
|---|---|
| Invoices read | **8 / 8** (no reader failures) |
| Traps planted | **4** |
| Traps caught (not paid) | **4 / 4**: 3 STOP, 1 ASK |
| Clean invoices wrongly stopped | **0 / 4** |
| Clean invoices paid | 3 PAY + 1 LATER (cash limit; nearer deadlines paid first) |
| Reader field errors | 1 character in 1 field: Hope's GSTIN `33KLMNO…` read as `33KLMN0…` (letter O read as zero) on both Hope invoices. It did not change any decision: the checker fell back to the vendor name. |

## Invoice by invoice

| File | Invoice | Language / form | Trap | Expected | Got | Why (checker's words) |
|---|---|---|---|---|---|---|
| inv01_doe.png | DH-0101 | English, printed | clean | PAY | **PAY** | |
| inv02_wells.png | WP/77 | Tamil name, Tamil labels, amount in Tamil words | clean | PAY | **LATER** | Not enough cash today after paying the invoices with nearer deadlines. |
| inv03_hope.png | HE-305 | Hindi name, Hindi labels, amount in Hindi words | clean | PAY | **PAY** | |
| inv04_hope.png | HE-310 | English | changed account | STOP | **STOP** | The bank account on this invoice is not the account we have on file for Hope Electricals. Call the vendor on the number we already have before paying. |
| inv05_wells.png | WP/78 | English | wrong arithmetic | STOP | **STOP** | Subtotal 20000 plus tax 3600 is 23600, but the total says 26300. |
| inv06_doe.png | dh/101 | English, different layout | duplicate in disguise (number and date format changed) | STOP | **STOP** | Invoice number DH-0101 from Doe Hardware Supplies has already been queued. |
| inv07_jane.png | JDT-21 | English | mismatched name: John Doe's account on Jane D Traders' bill | STOP | **ASK** | This vendor is not in our vendor list. |
| inv08_wells.jpg | 512 | handwritten bill book, phone photo | clean | PAY | **PAY** | |

## What the numbers say
- The reader got every amount, account number and IFSC right, including Tamil and Hindi amounts in words and the handwritten photo.
- Every trap was held before money moved, and no clean bill was blocked.
- **Weak spot:** inv07 is held only because Jane D Traders is unknown. The checker does not say the real reason: the account on the bill belongs to John Doe, a vendor already on file. Fix: when an invoice's account matches a *different* vendor's account on file, STOP with that reason.
- On inv05 the reader also flagged its own confidence on `total` as low. That was the right instinct: the total is the number that is wrong.

## Honest notes
- inv08 is a generated handwritten page made to look like a phone photo, not a real pen-and-paper photo. A real photographed bill would be a stronger test.
- LATER on inv02 depends on the `--cash 100000` limit and today's date (MSME 45-day rule for Wells). With more cash it is PAY.
