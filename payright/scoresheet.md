# Score sheet — demo invoice set

Run on 21 Nov 2026 with the real Sarvam reader (`mode: advanced`, `ta-IN`), then
`python payright/run.py payright/invoices.json --no-pay --cash 100000`.

Run output: `SCORE  PAY 3  LATER 1  STOP 4   |   traps caught 4/4, good invoices wrongly blocked 0/4`
Invoices: `payright/invoices/` (made by `make_invoices.py`). Expected outcomes: `invoice_answer_key.json`.

| | Result |
|---|---|
| Invoices read | **8 / 8** (no reader failures) |
| Traps planted | **4** |
| Traps caught (not paid) | **4 / 4**, all STOP |
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
| inv07_jane.png | JDT-21 | English | mismatched name: John Doe's account on Jane D Traders' bill | STOP | **STOP** | The bank account on this invoice belongs to John Doe (Doe Hardware Supplies), but the bill is from Jane D Traders. Do not pay until both vendors confirm. |
| inv08_wells.jpg | 512 | generated handwritten-style bill book, made to look like a phone photo | clean | PAY | **PAY** | |
| inv09_hope.png | HE-312 | English | account one digit off (388108022659) | STOP | **STOP** | The bank account on this invoice is not the account we have on file for Hope Electricals. Call the vendor on the number we already have before paying. |

## What the numbers say
- The reader got every amount, account number and IFSC right, including Tamil and Hindi amounts in words and the handwritten photo.
- Every trap was held before money moved, and no clean bill was blocked.
- inv07 was first only an ASK ("vendor not in our list"), which hid the real danger. `check.py` now also STOPs any bill whose account belongs to a *different* vendor on file, and says whose account it is. Self-test covers it.
- On inv05 the reader also flagged its own confidence on `total` as low. That was the right instinct: the total is the number that is wrong.

## Honest notes
- inv08 is a generated handwritten-style page made to look like a phone photo, not a real pen-and-paper photo. A real photographed handwritten bill is still to be added (NOW.md task 9).
- LATER on inv02 depends on the `--cash 100000` limit and today's date (MSME 45-day rule for Wells). With more cash it is PAY.

## Beyond the demo set: 44 invoices in 23 languages, scored field by field

Counting rule: a *trap* is a bill planted to be refused. Every other bill is *genuine*, however bad its photo,
and counts as not paid if it is asked about or stopped.

`python payright/evidence.py all` re-scores the saved reads; full report with every image:
`docs/evidence/PayRight_Evidence.pdf`.

| | Demo (9) | Stress (8) | Fail-safe ladder (5) | 20 languages (20) | Real bills (2) | All 44 |
|---|---|---|---|---|---|---|
| Planted traps caught | 5/5 | 3/3 | none planted | none planted | none planted | **8/8** |
| Genuine bills cleared to pay | 4/4 | 5/5 | 4/5 (1 stopped) | 19/20 (1 stopped) | both ASK (unknown vendors) | **32/34** (2 stopped) |
| Wrong payments approved | 0 | 0 | 0 | 0 | 0 | **0** |
| Critical fields read right | 87/90 | 77/80 | 45/50 | 193/200 | 20/20 | **422/440 (96%)** |
| Money fields (total, account, IFSC) read right | | | | 60/60 | 6/6 | **130/132 (98%)** |

- `st03` (Devanagari digits): read right with Sarvam's confidence at 0.5; arithmetic and words confirm it, so it is paid.
- The two money-field misses are both on `lad4`, the barely readable photo. Sarvam invented the account and IFSC there; the checker refused the bill.
- Bug found by this test and fixed in `extract.py`: a confidence of 0 was treated as fully sure (`0 or 1` is `1`).
- Languages: 23 (all 22 Indian languages of the Eighth Schedule + English). In the 20-language set, 9 clean bills were
  at first asked about because Sarvam scores non-English vendor names at 0.5. The checker now asks only when nothing
  confirms a shaky reading (GSTIN or account on file proves the vendor): all 9 are paid, nothing else changed.
  The Assamese bill is still stopped (vendor not identified).
