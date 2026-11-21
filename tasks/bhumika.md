# Bhumika — invoices, proof, pitch

> Current list: `tasks/NOW.md`. Where it differs from anything below, NOW.md wins.

## Now: make 8 fake invoices (photos or PDFs) into `payright/invoices/`
The Cashfree sandbox only answers to these accounts, so use only these vendors:

| Vendor on invoice | Account holder | Account number | IFSC |
|---|---|---|---|
| Doe Hardware Supplies | John Doe | 026291800001191 | YESB0000262 |
| Wells Paints and Chemicals | Tom Wells | 1233943142 | ICIC0000009 |
| Hope Electricals | Bob Hope | 388108022658 | ICIC0000009 |

Mix Tamil, Hindi and English; at least one handwritten and photographed.
- [x] 4 clean invoices (one with the vendor name in Tamil or Hindi script)
- [x] Changed account: Hope Electricals with account 026291800001190
- [x] Duplicate in disguise: copy a clean one, change number format
      (DH-0101 -> dh/101) and date format
- [x] Wrong arithmetic: total not equal to subtotal + tax
- [x] Mismatched name: John Doe's account on a bill from "Jane D Traders"

You do not need a Sarvam or Cashfree account. Push the files to the repo (or
send them to Chirag); he runs the reader on his laptop.

Done: 8 invoices in `payright/invoices/`, regenerate with `python payright/make_invoices.py`;
expected results in `payright/invoice_answer_key.json`.

## By 1:45
- [x] Chirag runs the reader and checker on your invoices and sends you the
      output table.
      Done: reader and checker run on the real Sarvam API; results in
      `payright/scoresheet.md`.
- [x] Fill the score sheet: traps planted, traps caught, clean invoices
      wrongly stopped. Real numbers only.

## By 2:45: what the judges must receive
- [x] Design note, half a page: what we chose, what we chose NOT to use and
      why (a model reads, code decides; money only to the account on file;
      one transfer ID per invoice so a retry cannot pay twice).
- [x] One success case and one failure case the agent handled.
- [ ] 6-minute demo script, then run the timer in three rehearsals:
      problem (40 s) -> doctored invoice goes in -> agent refuses and says
      why -> owner approves by phone -> payouts show as successful ->
      run the batch again, nothing is paid twice -> our numbers.
      Written: `docs/judges_pack.md` (PDF: `docs/PayRight_Judges_Pack.pdf`,
      rebuild with `python docs/make_judges_pdf.py`). Still to do: the three timed
      rehearsals; write the times in the table at the end of the pack.

## Extra (done): proof beyond the demo set
- [x] Stress set (8) and fail-safe photo ladder (5) in `payright/test_sets/`,
      made by `python payright/make_invoices.py all`; every invoice has its
      true values in the answer key.
- [x] `python payright/evidence.py all` scores the reader field by field and
      the checker's decisions: `docs/evidence/PayRight_Evidence.pdf`.
      21 invoices: traps 8/8, clean stopped 0/13, wrong payments 0, fields 95%.
- [x] Invoices in all 22 Indian languages + English (`payright/test_sets/languages/`),
      each read with its own language code. 41 invoices in total, 23 languages.

## Update 1:50 PM (from review of your work)
Your numbers reproduce from the committed files. Fix these before anyone reads the pack:
- [ ] `docs/judges_pack.md:40-41` says an invoice was "filled in by hand, photographed".
      None was: all 21 are generated. Either photograph ONE real handwritten bill now and
      run it, or change the sentence. This matters; judges will bring handwritten ones.
- [ ] Lines 6, 77-78: "8/8 traps, 0/13 good stopped" counts a clean bill that got STOP as
      a trap. Honest count: 7/7 traps caught, 2 of 14 good bills not paid.
- [ ] Lines 24, 30, 31, 61, 121 claim things that have not happened: a completed payout,
      bank verification in Relay, Cashfree rejecting a repeated ID, a recorded Hindi call,
      failed payouts going back as ASK. Mark each "planned" or "not yet tested", then
      rebuild the PDF.
- [ ] New trap (Abhijeet's idea): Hope Electricals with account 388108022659 (one digit
      off from 388108022658). Add it to the demo set and the answer key as STOP.
- [ ] The rehearsal table is empty. Three timed runs after 2:45.

## Done at 2 PM (NOW.md tasks 10 and 11)
- [x] Task 10: `payright/invoices/inv09_hope.png`, Hope Electricals with account 388108022659
      (one digit off), in the answer key as STOP. On its true values the checker STOPs it.
      NOT READ YET: my Sarvam account is out of credits (402). Chirag, please run
      `python payright/evidence.py demo --read` (or the reader) on your account.
- [x] Task 11: judges' pack corrected. Generated handwriting is called generated. Counts are honest:
      7/7 planted traps caught, 32/34 genuine bills cleared to pay (2 stopped; was 22/34 before the
      checker's 2:20 PM change), 0 wrong
      payments. Payout, bank verification, repeated-ID rejection, the recorded call and failed-payout
      handling are marked planned / not yet tested. PDF rebuilt.
- [x] Task 9: real handwritten bill pushed: `payright/test_sets/real/real01_samsuddin.jpg`
      (PAN, phones, customer details and signatures blacked out; the repo is public). Truth transcribed
      in `invoice_answer_key.json`: bill 287, 28/10/2024, 9 lines, total 7,226; unknown vendor, no bank
      details, so the right result is ASK. NOT READ YET (no credits). Chirag: run
      `python payright/evidence.py real --read en-IN`. The photo is only 400x541; a full-size original
      would be a fairer test.
      Also added `payright/test_sets/real/real02_amazon.jpg`: a real printed Amazon tax invoice (my own;
      addresses, order number and payment IDs blacked out). Truth: BOM5-540667, 08.05.2025,
      18,880.50 + 3,398.50 GST = 22,279.00. Seller not on our list: right result ASK. Not read yet.
- [ ] Task 14: run the timer at the three rehearsals.
